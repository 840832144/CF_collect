# cf_bootstrap_gadget.py — Cash Frenzy Houdini namespace Gadget 加载
# 改编自 Huuuge `bootstrap_houdini_gadget.py`（D:\huuuge-research\artifacts\live_probe\），
# 仅替换 package / target module / gadget 路径。逻辑与已验证的 Android 9 路径一致。
#
# 作用：冷启动 Cash Frenzy，在 libnativebridge.so 加载目标 arm64 模块
# （libcocos2dlua.so）时，把 arm64 Frida Gadget 加载进同一 native-bridge namespace，
# 使 outer x86_64 frida 视角下也能观察 arm64 进程内的 Lua dispatch。
#
# 用法（由 cf_run_session.ps1 调用，或手动）：
#   python cf_bootstrap_gadget.py --device-id 127.0.0.1:5585 \
#       --gadget-path <app lib/arm64/libcash-gadget.so> --timeout 120
from __future__ import annotations

import argparse
import json
import time

import frida


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Load an ARM64 Frida Gadget through BlueStacks Houdini "
                    "using the Cash Frenzy app namespace (Android 9)."
    )
    parser.add_argument('--device-id', required=True, default='127.0.0.1:5585')
    parser.add_argument('--package', default='slots.pcg.casino.games.free.android')
    parser.add_argument('--module', default='libcocos2dlua.so')
    parser.add_argument('--gadget-path', required=True,
                        help='Absolute Android path to the ARM64 Gadget inside the app '
                             'native-library directory, e.g. '
                             '/data/app/.../lib/arm64/libcash-gadget.so')
    parser.add_argument('--flags', type=int, default=2,
                        help='dlopen-style flags for NativeBridgeLoadLibraryExt '
                             '(2=RTLD_NOW, 1=RTLD_LAZY). Default 2.')
    parser.add_argument('--timeout', type=int, default=120)
    args = parser.parse_args()

    device = frida.get_device_manager().get_device(args.device_id, timeout=10)
    try:
        device.kill(device.get_process(args.package).pid)
        time.sleep(1)
    except frida.ProcessNotFoundError:
        pass

    pid = device.spawn([args.package])
    session = device.attach(pid)
    source = r'''
'use strict';
const targetModule = __TARGET_MODULE__;
const gadgetPath = __GADGET_PATH__;
const loadFlags = __FLAGS__;
let installed = false;
let scheduled = false;

function install(module) {
  if (installed) return;
  installed = true;
  const address = module.getExportByName(
    '_ZN7android26NativeBridgeLoadLibraryExtEPKciPNS_25native_bridge_namespace_tE'
  );
  const loadLibraryExt = new NativeFunction(
    address, 'pointer', ['pointer', 'int', 'pointer']
  );
  Interceptor.attach(address, {
    onEnter(args) {
      this.path = '';
      try { this.path = args[0].readCString(); } catch (_) {}
      this.flags = args[1].toInt32();
      this.namespace = args[2];
    },
    onLeave(result) {
      if (!this.path.endsWith('/' + targetModule)) return;
      send({
        kind: 'target-load',
        path: this.path,
        flags: this.flags,
        namespace: this.namespace.toString(),
        handle: result.toString()
      });
      if (scheduled) return;
      scheduled = true;
      const namespace = this.namespace;
      setImmediate(function () {
        try {
          send({kind: 'gadget-load-started',
                namespace: namespace.toString(), path: gadgetPath});
          const handle = loadLibraryExt(
            Memory.allocUtf8String(gadgetPath), loadFlags, namespace
          );
          send({kind: 'gadget-load', handle: handle.toString(),
                namespace: namespace.toString()});
        } catch (error) {
          send({kind: 'gadget-error', error: error.stack,
                namespace: namespace.toString()});
        }
      });
    }
  });
  send({kind: 'bridge-hook-installed', base: module.base.toString()});
}

const existing = Process.findModuleByName('libnativebridge.so');
if (existing !== null) install(existing);
Process.attachModuleObserver({
  onAdded(module) {
    if (module.name === 'libnativebridge.so') install(module);
  },
  onRemoved(module) {}
});
'''.replace('__TARGET_MODULE__', json.dumps(args.module))
    source = source.replace('__GADGET_PATH__', json.dumps(args.gadget_path))
    source = source.replace('__FLAGS__', json.dumps(args.flags))

    messages: list[dict] = []

    def on_message(message, data) -> None:
        messages.append(message)
        print(json.dumps(message, ensure_ascii=False), flush=True)

    script = session.create_script(source)
    script.on('message', on_message)
    script.load()
    device.resume(pid)
    print(json.dumps({'kind': 'spawned', 'pid': pid}), flush=True)

    deadline = time.monotonic() + args.timeout
    try:
        while time.monotonic() < deadline:
            kinds = {
                item.get('payload', {}).get('kind')
                for item in messages if item.get('type') == 'send'
            }
            if 'gadget-load' in kinds or 'gadget-error' in kinds:
                break
            time.sleep(0.25)
        else:
            raise TimeoutError('Timed out waiting for Gadget load completion')
    finally:
        try:
            script.unload()
        except frida.InvalidOperationError:
            pass
        try:
            session.detach()
        except frida.InvalidOperationError:
            pass


if __name__ == '__main__':
    main()
