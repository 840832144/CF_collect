#!/usr/bin/env python3
# cf_probe.py — Cash Frenzy scoped inbound 只读探针 + batch_spin 提取 + 会话清单
# 改编自 TASK-0024 `task0024_inbound_probe.py`（D:\AI-Workspace\reviews\cash-frenzy\tools\），
# 序列化预算（depth 4 / 64 元素 / 64KiB / 32 pcalls / 2KiB string）原样保留，不做任何放宽。
# 新增：batch_spin direct 字段提取 -> spin_records.jsonl；会话清单 -> session_manifest.json。
#
# 铁律：hook 只读；仅 inbound dispatch 线程 scope 内激活；超限截断；不碰 signer/encryptor。
#
# 用法（由 cf_run_session.ps1 调用，或手动）：
#   python cf_probe.py --session-dir <dir> --endpoint 127.0.0.1:27043 --duration 600 --mode lua
from __future__ import annotations

import argparse
import json
import re
import signal
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import frida

SAFE_CMD = re.compile(r"^[A-Za-z_][A-Za-z0-9_.:/-]{0,127}$")

MAX_DEPTH = 4
MAX_ELEMENTS = 64
MAX_MESSAGE_BYTES = 64 * 1024
MAX_STRING_BYTES = 2 * 1024
MAX_PCALLS_PER_SCOPE = 32
PACKAGE = "slots.pcg.casino.games.free.android"
APP_VERSION = "4.78 / 478"
INSTANCE = "Pie64_3 / AppResearch2"
ADB_SERIAL = "127.0.0.1:5585"

# batch_spin direct 结果字段（TASK-0024 5/5 复现确认），路径在 arg[2].[2].list.[1] 之下
SPIN_DIRECT_FIELDS = {
    "base_win", "bonus_base_win", "total_win", "coins",
    "win_lines", "win_pos_list", "feature", "result",
}
# spin 结果的判据：至少出现一个"赢"字段（仅 coins 的余额更新不算 spin）
WIN_SIGNATURE = {"base_win", "bonus_base_win", "total_win", "win_lines", "win_pos_list"}
# 数值型直采字段（写 spin_records.jsonl 时取值）
SPIN_VALUE_FIELDS = {"base_win", "bonus_base_win", "total_win", "coins"}
# 表型直采字段（写 spin_records.jsonl 时记元素数）
SPIN_TABLE_FIELDS = {"win_lines", "win_pos_list"}


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


# ---------- batch_spin 提取（Python 侧，纯读） ----------

def table_field(node: Any, key: str) -> Any:
    """在探针序列化后的 table 节点中按 key 取值（key 形如 '[1]' 或 'list'）。"""
    if not isinstance(node, dict) or node.get("type") != "table":
        return None
    for field in node.get("fields", []):
        if isinstance(field, dict) and field.get("key") == key:
            return field.get("value")
    return None


def walk_direct_fields(node: Any, path: str, out: dict[str, Any]) -> None:
    """收集 arg[2].[2] 之下的 direct 字段（按字段名，含 list 索引链）。"""
    if not isinstance(node, dict):
        return
    if node.get("type") == "table":
        for field in node.get("fields", []):
            if not isinstance(field, dict):
                continue
            key = str(field.get("key", ""))
            child_path = f"{path}.{key}" if path else key
            walk_direct_fields(field.get("value"), child_path, out)
        return
    last = path.rsplit(".", 1)[-1] if path else ""
    if last in SPIN_DIRECT_FIELDS:
        if node.get("type") == "number":
            out[last] = node.get("value")
        elif node.get("type") == "string":
            out[last] = node.get("value")
        elif node.get("type") == "table":
            out[last] = {"element_count": len(node.get("fields", []))}
        else:
            out[last] = {"type": node.get("type")}


def extract_spin(record: dict[str, Any]) -> dict[str, Any] | None:
    """从 lua-pcall-args 事件提取 spin 直采字段。

    触发条件：任意参数下出现 SPIN_DIRECT_FIELDS 中的结果字段（base_win/total_win/coins/...），
    不绑定具体命令名（不同机台/版本命令名可能不同，如 batch_spin / BATCH_SPIN / 其它）。
    command 若可安全读取则一并记录。
    """
    direct: dict[str, Any] = {}
    command = None
    for argument in record.get("arguments", []):
        if not isinstance(argument, dict):
            continue
        idx = argument.get("index")
        val = argument.get("value")
        if idx == 1:
            cn = table_field(val, "[1]")
            if isinstance(cn, dict) and cn.get("type") == "string":
                cval = cn.get("value")
                if isinstance(cval, str) and SAFE_CMD.fullmatch(cval):
                    command = cval
        walk_direct_fields(val, f"arg[{idx}]", direct)
    if not direct:
        return None
    # 必须有赢字段才算一次 spin 结果；仅 coins（余额更新）不算
    if not (set(direct) & WIN_SIGNATURE):
        return None
    rec: dict[str, Any] = {
        "seq": record.get("seq"),
        "captured_at": record.get("captured_at"),
        "scope_id": record.get("scopeId"),
    }
    if command:
        rec["command"] = command
    for name in SPIN_VALUE_FIELDS:
        if name in direct:
            rec[name] = direct[name]
    for name in SPIN_TABLE_FIELDS:
        if name in direct and isinstance(direct[name], dict):
            rec[name + "_count"] = direct[name].get("element_count")
    for name in ("feature", "result"):
        if name in direct:
            rec[name] = direct[name]
    return rec


# ---------- 主流程 ----------

def main() -> None:
    parser = argparse.ArgumentParser(description="Cash Frenzy scoped inbound probe (read-only)")
    parser.add_argument("--session-dir", required=True)
    parser.add_argument("--endpoint", default="127.0.0.1:27043")
    parser.add_argument("--duration", type=int, default=600)
    parser.add_argument("--mode", choices=("stability", "lua"), default="lua")
    parser.add_argument("--max-depth", type=int, default=MAX_DEPTH,
                        help="Lua table serialization depth limit (default %d). "
                             "Increase to ~6-7 to fully reproduce deep spin-result/"
                             "jackpot payloads (arg[2].[2].list.[1].*)." % MAX_DEPTH)
    args = parser.parse_args()

    session_dir = Path(args.session_dir)
    session_dir.mkdir(parents=True, exist_ok=False)
    events_path = session_dir / "events.jsonl"
    spin_path = session_dir / "spin_records.jsonl"
    state_path = session_dir / "state.json"
    manifest_path = session_dir / "session_manifest.json"
    stop_path = session_dir / "STOP"
    counts = {"events": 0, "lua_pcall_args": 0, "scope_summaries": 0,
              "batch_spin": 0, "errors": 0}
    stopping = False
    finishing = False
    detached: dict[str, Any] | None = None
    start_utc = utc_now()

    def persist(status: str) -> None:
        state = {
            "status": status,
            "mode": args.mode,
            "limits": {
                "max_depth": args.max_depth,
                "max_elements": MAX_ELEMENTS,
                "max_message_bytes": MAX_MESSAGE_BYTES,
                "max_string_bytes": MAX_STRING_BYTES,
                "max_pcalls_per_scope": MAX_PCALLS_PER_SCOPE,
            },
            "counts": counts,
            "detached": detached,
        }
        state_path.write_text(json.dumps(state, indent=2) + "\n", encoding="utf-8")

    def record(payload: dict[str, Any]) -> None:
        item = bounded_record({"captured_at": utc_now(), **payload})
        with events_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(item, ensure_ascii=False, separators=(",", ":")) + "\n")
        counts["events"] += 1
        kind = item.get("kind")
        if kind == "lua-pcall-args":
            counts["lua_pcall_args"] += 1
            spin = extract_spin(item)
            if spin is not None:
                counts["batch_spin"] += 1
                with spin_path.open("a", encoding="utf-8") as handle:
                    handle.write(json.dumps(spin, ensure_ascii=False, separators=(",", ":")) + "\n")
        elif kind == "inbound-scope-summary":
            counts["scope_summaries"] += 1
        elif kind in {"probe-error", "probe-truncated", "host-truncated"}:
            counts["errors"] += 1

    def on_message(message: dict[str, Any], data: bytes | None) -> None:
        if message.get("type") == "send" and isinstance(message.get("payload"), dict):
            record(message["payload"])
        else:
            record({"kind": "frida-message", "message_type": message.get("type")})
            counts["errors"] += 1
        persist("ready")

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
    persist("starting")
    device = frida.get_device_manager().add_remote_device(args.endpoint)
    gadget = device.get_process("Gadget")
    session = device.attach(gadget.pid)
    session.on("detached", on_detached)
    script = session.create_script(build_javascript(args.mode, args.max_depth))
    script.on("message", on_message)
    script.load()
    persist("ready")
    print(f"READY mode={args.mode} session={session_dir}", flush=True)

    deadline = time.monotonic() + args.duration
    try:
        while not stopping and not stop_path.exists() and time.monotonic() < deadline:
            time.sleep(0.25)
    finally:
        finishing = True
        try:
            script.unload()
        except frida.InvalidOperationError:
            pass
        try:
            session.detach()
        except frida.InvalidOperationError:
            pass
        final_status = "detached" if detached else "stopped"
        persist(final_status)
        manifest = {
            "schema_version": 1,
            "session_id": session_dir.name,
            "package": PACKAGE,
            "app_version": APP_VERSION,
            "instance": INSTANCE,
            "adb_serial": ADB_SERIAL,
            "mode": args.mode,
            "start_utc": start_utc,
            "end_utc": utc_now(),
            "counts": counts,
            "final_status": final_status,
        }
        manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
                                 encoding="utf-8")
        print(f"STOPPED status={final_status} counts={counts}", flush=True)


if __name__ == "__main__":
    main()
