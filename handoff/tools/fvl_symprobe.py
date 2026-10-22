"""Probe which SSL/curl/Lua symbols are actually resolvable in the running Pop! Slots process."""
import sys

import frida

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

JS = r"""
setImmediate(function () {
  var out = {gl: [], mods: []};
  ['SSL_read','SSL_write','BIO_read','BIO_write','curl_easy_perform',
   'luaL_loadbuffer','lua_load','lua_pcall'].forEach(function (n) {
    var p = Module.findExportByName(null, n);
    if (p) out.gl.push(n + '@' + Process.findModuleByAddress(p).name);
  });
  Process.enumerateModules().forEach(function (m) {
    if (m.name.toLowerCase().indexOf('bigcasino') >= 0) {
      out.mods.push({name: m.name, size: m.size, base: m.base.toString()});
      try {
        var ex = m.enumerateExports().filter(function (e) {
          return /ssl_|SSL_|curl_|lua/i.test(e.name);
        }).map(function (e) { return e.name; });
        out.mods[out.mods.length - 1].hits = ex.slice(0, 60);
        out.mods[out.mods.length - 1].hitCount = ex.length;
      } catch (e) { out.mods[out.mods.length - 1].err = String(e); }
    }
  });
  send(out);
});
"""

dev = frida.get_device_manager().add_remote_device("127.0.0.1:27042")
sess = dev.attach("com.playstudios.popslots")
got = []
script = sess.create_script(JS)
script.on("message", lambda m, d: got.append(m))
script.load()
import time
for _ in range(50):
    if got:
        break
    time.sleep(0.2)
if got:
    p = got[0]["payload"]
    print("global exports:", p.get("gl"))
    for m in p.get("mods", []):
        print("module:", m["name"], "size=%d" % m["size"], "hitCount=%s" % m.get("hitCount"), m.get("err", ""))
        print("   ", m.get("hits"))
else:
    print("no reply")
sess.detach()
