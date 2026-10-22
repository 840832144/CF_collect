"""Log every URL Cash Frenzy asks libcurl to fetch (finds the resource CDN that 95% is waiting on).

    python cf_urlwatch.py [seconds]

Hooks curl_easy_setopt in libcocos2dlua.so and prints CURLOPT_URL arguments.
Works on whichever instance PS_CF_FRIDA points at (default: frida on 127.0.0.1:27043 = instance 5605).
"""
import os, sys, time

import frida

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

DEV = os.environ.get("PS_CF_FRIDA", "127.0.0.1:27043")
PKG = "slots.pcg.casino.games.free.android"
SECS = int(sys.argv[1]) if len(sys.argv) > 1 else 90

JS = r"""
setImmediate(function () {
  var mods = Process.enumerateModules().filter(function (m) {
    return /cocos2dlua|cocos/i.test(m.name);
  }).map(function (m) { return m.name; });
  send({mods: mods});
  var targets = Process.enumerateModules().filter(function (m) {
    return /cocos2dlua/i.test(m.name);
  });
  if (!targets.length) { send({err: 'libcocos2dlua not loaded'}); return; }
  var m = targets[0];
  var setopt = Module.findExportByName(m.name, 'curl_easy_setopt');
  if (!setopt) { send({err: 'curl_easy_setopt missing in ' + m.name}); return; }
  Interceptor.attach(setopt, {
    onEnter: function (a) {
      try {
        var opt = a[1].toInt32();
        // 10002 = CURLOPT_URL, 10004 = CURLOPT_PROXY, 10243 = CURLOPT_USERAGENT
        if (opt === 10002 || opt === 10004) {
          var s = a[2].readCString();
          if (s) send({opt: opt, url: s});
        }
      } catch (e) {}
    }
  });
  send({ready: true, mod: m.name})
});
"""

dev = frida.get_device_manager().add_remote_device(DEV)
sess = dev.attach(PKG)
urls = []
script = sess.create_script(JS)
script.on("message", lambda m, d: (print("[js]", m.get("payload"), flush=True)
                                   if m.get("type") == "send" else print("[err]", m.get("description"), flush=True)))
script.load()
t0 = time.time()
last = 0
try:
    while time.time() - t0 < SECS:
        time.sleep(1)
finally:
    sess.detach()
print("done")
