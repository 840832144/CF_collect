#!/usr/bin/env python3
# cf_probe.py — 【游戏】 scoped inbound 只读探针 + Collector 1.0 event pipeline
# 改编自 TASK-0024 `task0024_inbound_probe.py`（D:\AI-Workspace\reviews\cash-frenzy\tools\），
# 序列化预算（depth 4 / 64 元素 / 64KiB / 32 pcalls / 2KiB string）原样保留，不做任何放宽。
# Android 9 Hook/serializer 保持 TASK-0024 已验证路线；主机侧只新增 Adapter Registry 与固定产物。
#
# 铁律：hook 只读；仅 inbound dispatch 线程 scope 内激活；超限截断；不碰 signer/encryptor。
#
# 用法（由 cf_run_session.ps1 调用，或手动）：
#   python cf_probe.py --session-dir <dir> --endpoint 127.0.0.1:27043 --duration 600 --mode lua
from __future__ import annotations

import argparse
import json
import os
import signal
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import frida

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from adapters.registry import adapt_record
from collector.readiness import classify_ready_payload
from collector.session_artifacts import SessionArtifacts

MAX_DEPTH = 4
MAX_ELEMENTS = 64
MAX_MESSAGE_BYTES = 64 * 1024
MAX_STRING_BYTES = 2 * 1024
MAX_PCALLS_PER_SCOPE = 32
PACKAGE = "slots.pcg.casino.games.free.android"
APP_VERSION = "4.78 / 478"
INSTANCE = "Pie64_3 / AppResearch2"
ADB_SERIAL = "127.0.0.1:5585"

def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def bounded_record(payload: dict[str, Any]) -> dict[str, Any]:
    encoded = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    if len(encoded) <= MAX_MESSAGE_BYTES:
        return payload
    return {
        "kind": "host-truncated",
        "original_kind": str(payload.get("kind", "unknown")),
        "serialized_bytes": len(encoded),
        "limit_bytes": MAX_MESSAGE_BYTES,
        "truncated": True,
        "reason": "host-message-budget",
    }


def build_javascript(mode: str, max_depth: int = MAX_DEPTH) -> str:
    if mode == "stability":
        return r"""
        'use strict';
        const module = Process.findModuleByName('libcocos2dlua.so');
        send({
          kind: 'stability-ready',
          arch: Process.arch,
          modulePresent: module !== null,
          moduleName: module === null ? null : module.name
        });
        """

    source = r"""
    'use strict';
    const MAX_DEPTH = __MAX_DEPTH__;
    const MAX_ELEMENTS = __MAX_ELEMENTS__;
    const MAX_MESSAGE_BYTES = __MAX_MESSAGE_BYTES__;
    const MAX_STRING_BYTES = __MAX_STRING_BYTES__;
    const MAX_PCALLS_PER_SCOPE = __MAX_PCALLS_PER_SCOPE__;
    const module = Process.getModuleByName('libcocos2dlua.so');
    const gettop = new NativeFunction(module.getExportByName('lua_gettop'), 'int', ['pointer']);
    const settop = new NativeFunction(module.getExportByName('lua_settop'), 'void', ['pointer', 'int']);
    const type = new NativeFunction(module.getExportByName('lua_type'), 'int', ['pointer', 'int']);
    const pushnil = new NativeFunction(module.getExportByName('lua_pushnil'), 'void', ['pointer']);
    const next = new NativeFunction(module.getExportByName('lua_next'), 'int', ['pointer', 'int']);
    const tolstring = new NativeFunction(module.getExportByName('lua_tolstring'), 'pointer', ['pointer', 'int', 'pointer']);
    const tonumber = new NativeFunction(module.getExportByName('lua_tonumber'), 'double', ['pointer', 'int']);
    const toboolean = new NativeFunction(module.getExportByName('lua_toboolean'), 'int', ['pointer', 'int']);
    const topointer = new NativeFunction(module.getExportByName('lua_topointer'), 'pointer', ['pointer', 'int']);
    const typeNames = ['nil', 'boolean', 'lightuserdata', 'number', 'string', 'table', 'function', 'userdata', 'thread'];
    const scopes = {};
    let nextScopeId = 1;

    function utf8Bytes(text) {
      let total = 0;
      for (let i = 0; i < text.length; i += 1) {
        const code = text.charCodeAt(i);
        if (code < 0x80) total += 1;
        else if (code < 0x800) total += 2;
        else if (code >= 0xD800 && code <= 0xDBFF && i + 1 < text.length) {
          total += 4;
          i += 1;
        } else total += 3;
      }
      return total;
    }

    function sizeT(pointer) {
      return Process.pointerSize === 8 ? pointer.readU64().toNumber() : pointer.readU32();
    }

    function absoluteIndex(L, index) {
      return index > 0 ? index : gettop(L) + index + 1;
    }

    function typeName(valueType) {
      return typeNames[valueType] || ('type-' + valueType);
    }

    function pointerId(L, index) {
      try {
        const value = topointer(L, index);
        return value.isNull() ? null : value.toString();
      } catch (_) {
        return null;
      }
    }

    function readLuaString(L, index, includeValue) {
      const lengthPointer = Memory.alloc(Process.pointerSize);
      if (Process.pointerSize === 8) lengthPointer.writeU64(0);
      else lengthPointer.writeU32(0);
      const valuePointer = tolstring(L, index, lengthPointer);
      const length = sizeT(lengthPointer);
      const result = {type: 'string', length: length};
      if (valuePointer.isNull() || !includeValue) return result;
      const readable = Math.min(length, MAX_STRING_BYTES);
      try {
        result.value = valuePointer.readUtf8String(readable);
      } catch (_) {
        result.binary = true;
      }
      if (length > MAX_STRING_BYTES) {
        result.truncated = true;
        result.reason = 'string-budget';
      }
      return result;
    }

    function keyAt(L) {
      const keyType = type(L, -2);
      if (keyType === 3) {
        const value = tonumber(L, -2);
        return Number.isFinite(value) && Number.isInteger(value) ? '[' + value + ']' : '<number-key>';
      }
      if (keyType !== 4) return '<' + typeName(keyType) + '-key>';
      const item = readLuaString(L, -2, true);
      if (typeof item.value !== 'string') return '<string-key:' + item.length + '>';
      return /^[A-Za-z_][A-Za-z0-9_.:\/-]{0,127}$/.test(item.value)
        ? item.value : '<non-identifier-key:' + item.length + '>';
    }

    function serializeValue(L, index, depth, context, path) {
      if (context.stop) return {type: 'truncated', truncated: true, reason: context.reason};
      const valueType = type(L, index);
      const name = typeName(valueType);
      if (valueType === 0) return {type: name};
      if (valueType === 1) return {type: name, value: toboolean(L, index) !== 0};
      if (valueType === 3) return {type: name, value: tonumber(L, index)};
      if (valueType === 4) return readLuaString(L, index, true);
      if (valueType !== 5) return {type: name, identity: pointerId(L, index)};
      if (depth >= MAX_DEPTH) {
        return {type: 'table', truncated: true, reason: 'depth-budget', depth: depth, path: path};
      }
      const identity = pointerId(L, index);
      if (identity !== null && context.ancestors[identity]) {
        return {type: 'table', cycle: true, identity: identity};
      }
      if (identity !== null) context.ancestors[identity] = true;
      const tableIndex = absoluteIndex(L, index);
      const baseTop = gettop(L);
      const fields = [];
      let truncated = false;
      let reason = null;
      try {
        pushnil(L);
        while (next(L, tableIndex) !== 0) {
          const key = keyAt(L);
          const childPath = path + '.' + key;
          const child = serializeValue(L, -1, depth + 1, context, childPath);
          fields.push({key: key, value: child});
          settop(L, -2);
          if (fields.length >= MAX_ELEMENTS) {
            truncated = true;
            reason = 'element-budget';
            break;
          }
          if (context.stop) {
            truncated = true;
            reason = context.reason;
            break;
          }
        }
      } finally {
        settop(L, baseTop);
        if (identity !== null) delete context.ancestors[identity];
      }
      const result = {type: 'table', identity: identity, fields: fields};
      if (truncated) {
        result.truncated = true;
        result.reason = reason;
      }
      const currentBytes = utf8Bytes(JSON.stringify(result));
      context.usedBytes += currentBytes;
      if (context.usedBytes > MAX_MESSAGE_BYTES) {
        context.stop = true;
        context.reason = 'message-budget';
        return {type: 'table', truncated: true, reason: context.reason, path: path};
      }
      return result;
    }

    function emitBounded(payload) {
      const serialized = JSON.stringify(payload);
      const byteCount = utf8Bytes(serialized);
      if (byteCount <= MAX_MESSAGE_BYTES) {
        send(payload);
        return;
      }
      send({
        kind: 'probe-truncated',
        originalKind: payload.kind,
        serializedBytes: byteCount,
        limitBytes: MAX_MESSAGE_BYTES,
        truncated: true,
        reason: 'message-budget'
      });
    }

    const dispatch = module.getExportByName('_ZN7cocos2d7network8BLSocket24onUIThreadReceiveMessageEPNS_9BLMessageE');
    const pcall = module.getExportByName('lua_pcall');

    Interceptor.attach(dispatch, {
      onEnter(args) {
        const tid = Process.getCurrentThreadId();
        let messageType = -1;
        try { messageType = args[1].add(0x24).readS32(); } catch (_) {}
        let scope = scopes[tid];
        if (scope === undefined) {
          scope = {id: nextScopeId++, depth: 0, messageType: messageType, pcallCount: 0,
                   skippedPcalls: 0, errors: 0};
          scopes[tid] = scope;
        }
        scope.depth += 1;
        scope.messageType = messageType;
        this.tid = tid;
        this.scopeId = scope.id;
      },
      onLeave(result) {
        const tid = this.tid;
        const scope = scopes[tid];
        if (scope === undefined) return;
        scope.depth = Math.max(0, scope.depth - 1);
        if (scope.depth !== 0) return;
        emitBounded({kind: 'inbound-scope-summary', scopeId: scope.id, threadId: tid,
                     messageType: scope.messageType, pcallCount: scope.pcallCount,
                     skippedPcalls: scope.skippedPcalls, errors: scope.errors});
        delete scopes[tid];
      }
    });

    Interceptor.attach(pcall, {
      onEnter(args) {
        const tid = Process.getCurrentThreadId();
        const scope = scopes[tid];
        if (scope === undefined || scope.depth <= 0) return;
        if (scope.pcallCount >= MAX_PCALLS_PER_SCOPE) {
          scope.skippedPcalls += 1;
          return;
        }
        scope.pcallCount += 1;
        const L = args[0];
        const nargs = args[1].toInt32();
        const nresults = args[2].toInt32();
        const errfunc = args[3].toInt32();
        const top = gettop(L);
        const firstArgument = top - nargs + 1;
        const context = {usedBytes: 0, stop: false, reason: null, ancestors: {}};
        const argumentsOut = [];
        const originalTop = top;
        try {
          if (nargs < 0 || nargs > MAX_ELEMENTS || firstArgument < 1) {
            emitBounded({kind: 'lua-pcall-args', scopeId: scope.id, threadId: tid,
                         messageType: scope.messageType, nargs: nargs,
                         truncated: true, reason: 'invalid-or-oversized-nargs'});
            return;
          }
          for (let index = firstArgument; index <= top; index += 1) {
            argumentsOut.push({index: index - firstArgument + 1,
                               value: serializeValue(L, index, 0, context,
                                                     'arg[' + (index - firstArgument + 1) + ']')});
            if (context.stop) break;
          }
          emitBounded({kind: 'lua-pcall-args', scopeId: scope.id, threadId: tid,
                       messageType: scope.messageType, nargs: nargs,
                       nresults: nresults, errfunc: errfunc,
                       functionType: typeName(type(L, top - nargs)),
                       arguments: argumentsOut,
                       truncated: context.stop, reason: context.reason});
        } catch (error) {
          scope.errors += 1;
          emitBounded({kind: 'probe-error', stage: 'lua-pcall-args', scopeId: scope.id,
                       threadId: tid, messageType: scope.messageType,
                       error: error.message});
        } finally {
          settop(L, originalTop);
        }
      }
    });

    send({kind: 'hook-status', mode: 'lua', installed: ['onUIThreadReceiveMessage', 'lua_pcall'],
          limits: {maxDepth: MAX_DEPTH, maxElements: MAX_ELEMENTS,
                   maxMessageBytes: MAX_MESSAGE_BYTES, maxStringBytes: MAX_STRING_BYTES,
                   maxPcallsPerScope: MAX_PCALLS_PER_SCOPE}});
    """
    replacements = {
        "__MAX_DEPTH__": str(max_depth),
        "__MAX_ELEMENTS__": str(MAX_ELEMENTS),
        "__MAX_MESSAGE_BYTES__": str(MAX_MESSAGE_BYTES),
        "__MAX_STRING_BYTES__": str(MAX_STRING_BYTES),
        "__MAX_PCALLS_PER_SCOPE__": str(MAX_PCALLS_PER_SCOPE),
    }
    for marker, value in replacements.items():
        source = source.replace(marker, value)
    return source


# ---------- 主流程 ----------

def main() -> None:
    parser = argparse.ArgumentParser(description="【游戏】 scoped inbound probe (read-only)")
    parser.add_argument("--session-dir", required=True)
    parser.add_argument("--endpoint", default="127.0.0.1:27043")
    parser.add_argument("--duration", type=int, default=600)
    parser.add_argument("--ready-timeout", type=int, default=30)
    parser.add_argument("--mode", choices=("stability", "lua"), default="lua")
    parser.add_argument("--package", default=PACKAGE)
    parser.add_argument("--app-version", default=os.environ.get("CF_APP_VERSION", APP_VERSION))
    parser.add_argument("--instance", default=INSTANCE)
    parser.add_argument("--adb-serial", default=ADB_SERIAL)
    parser.add_argument("--max-depth", type=int, default=MAX_DEPTH,
                        help="Lua table serialization depth limit (default %d). "
                             "Increase to ~6-7 to fully reproduce deep spin-result/"
                             "jackpot payloads (arg[2].[2].list.[1].*)." % MAX_DEPTH)
    args = parser.parse_args()

    session_dir = Path(args.session_dir)
    artifacts = SessionArtifacts(session_dir)
    artifacts.prepare_new()
    state_path = session_dir / "state.json"
    stop_path = session_dir / "STOP"
    counts = {
        "source_events": 0,
        "events": 0,
        "lua_pcall_args": 0,
        "scope_summaries": 0,
        "batch_spin": 0,
        "keepalive": 0,
        "adapter_skipped": 0,
        "errors": 0,
    }
    stopping = False
    finishing = False
    detached: dict[str, Any] | None = None
    ready = False
    readiness: dict[str, Any] = {"status": "pending", "mode": args.mode}
    failure: str | None = None
    start_utc = utc_now()
    limits = {
        "max_depth": args.max_depth,
        "max_elements": MAX_ELEMENTS,
        "max_message_bytes": MAX_MESSAGE_BYTES,
        "max_string_bytes": MAX_STRING_BYTES,
        "max_pcalls_per_scope": MAX_PCALLS_PER_SCOPE,
    }

    def persist(status: str) -> None:
        state = {
            "status": status,
            "mode": args.mode,
            "limits": limits,
            "counts": counts,
            "detached": detached,
            "readiness": readiness,
            "failure": failure,
        }
        state_path.write_text(json.dumps(state, indent=2) + "\n", encoding="utf-8")

    def record(payload: dict[str, Any]) -> None:
        item = bounded_record({"captured_at": utc_now(), **payload})
        source_event_index = counts["source_events"]
        artifacts.append_source(item)
        counts["source_events"] += 1
        kind = item.get("kind")
        if kind == "lua-pcall-args":
            counts["lua_pcall_args"] += 1
        elif kind == "inbound-scope-summary":
            counts["scope_summaries"] += 1
        elif kind in {"probe-error", "probe-truncated", "host-truncated"}:
            counts["errors"] += 1

        event = adapt_record(item, source_event_index, counts["events"])
        if event is None:
            return
        artifacts.append_event(event)
        counts["events"] += 1
        adapter_name = event["adapter"]["name"]
        status = event["payload"]["status"]
        if status != "ok":
            counts["adapter_skipped"] += 1
            return
        if adapter_name == "batch_spin":
            counts["batch_spin"] += 1
            artifacts.append_spin(event)
        elif adapter_name == "keepalive":
            counts["keepalive"] += 1

    def on_message(message: dict[str, Any], data: bytes | None) -> None:
        nonlocal ready, readiness, failure, stopping
        if message.get("type") == "send" and isinstance(message.get("payload"), dict):
            payload = message["payload"]
            record(payload)
            if not ready:
                candidate = classify_ready_payload(args.mode, payload)
                if candidate is not None:
                    readiness = candidate
                    if candidate["status"] == "verified":
                        ready = True
                        persist("ready")
                    else:
                        failure = "probe READY signal rejected"
                        stopping = True
                        persist("failed")
                else:
                    persist("starting")
            else:
                persist("ready")
        else:
            record({"kind": "frida-message", "message_type": message.get("type")})
            counts["errors"] += 1
            failure = f"frida message before clean stop: {message.get('type')}"
            stopping = True
            if not ready:
                readiness = {
                    "status": "rejected",
                    "mode": args.mode,
                    "kind": "frida-message",
                }
            persist("failed")

    def on_detached(reason: str, crash: Any) -> None:
        nonlocal detached, stopping
        if finishing and reason == "application-requested":
            return
        detached = {"reason": reason, "crash_present": crash is not None}
        stopping = True
        persist("detached")

    def request_stop(signum: int, frame: object) -> None:
        nonlocal stopping
        stopping = True

    signal.signal(signal.SIGINT, request_stop)
    signal.signal(signal.SIGTERM, request_stop)
    session = None
    script = None
    final_status = "failed"
    persist("starting")
    try:
        device = frida.get_device_manager().add_remote_device(args.endpoint)
        gadget = device.get_process("Gadget")
        session = device.attach(gadget.pid)
        session.on("detached", on_detached)
        script = session.create_script(build_javascript(args.mode, args.max_depth))
        script.on("message", on_message)
        script.load()

        ready_deadline = time.monotonic() + args.ready_timeout
        while not ready and not stopping and time.monotonic() < ready_deadline:
            time.sleep(0.05)
        if not ready:
            if failure is None:
                if detached is not None:
                    failure = f"probe detached before READY: {detached['reason']}"
                    failure_kind = "detached"
                else:
                    failure = f"probe READY timeout after {args.ready_timeout}s"
                    failure_kind = "timeout"
                readiness = {
                    "status": "rejected",
                    "mode": args.mode,
                    "kind": failure_kind,
                }
            persist("failed")
            raise RuntimeError(failure)

        print(
            f"READY verified mode={args.mode} kind={readiness['kind']} session={session_dir}",
            flush=True,
        )
        deadline = time.monotonic() + args.duration
        while not stopping and not stop_path.exists() and time.monotonic() < deadline:
            time.sleep(0.25)
        if failure is not None:
            final_status = "failed"
        else:
            final_status = "detached" if detached else "stopped"
    finally:
        finishing = True
        if script is not None:
            try:
                script.unload()
            except Exception:
                pass
        if session is not None:
            try:
                session.detach()
            except Exception:
                pass
        if detached and final_status == "failed" and failure is None:
            final_status = "detached"
        persist(final_status)
        artifacts.write_manifest(
            session_id=session_dir.name,
            runtime={
                "package": args.package,
                "app_version": args.app_version,
                "instance": args.instance,
                "adb_serial": args.adb_serial,
            },
            mode=args.mode,
            limits=limits,
            start_utc=start_utc,
            end_utc=utc_now(),
            counts=counts,
            final_status=final_status,
        )
        print(f"STOPPED status={final_status} counts={counts}", flush=True)


if __name__ == "__main__":
    main()
