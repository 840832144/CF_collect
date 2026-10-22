"""Passive Cocos Java downloader diagnostics on the dedicated 5605 instance.

Uses the existing root Frida server forwarded to 27605. Does not alter requests,
responses, certificates or game values. Query strings and response bodies are omitted.
"""
import json
import time
from pathlib import Path

import frida

PACKAGE = "slots.pcg.casino.games.free.android"
OUTPUT = Path(__file__).resolve().parents[1] / "result" / "diagnostics_20261022"
RUN_ID = str(time.time_ns())
SCRIPT = r"""
function safeUrl(value) {
  return String(value).replace(/[?#].*$/, '').replace(/(https?:\/\/)[^/@]*@/, '$1');
}
Java.perform(function () {
  const D = Java.use('org.cocos2dx.lib.Cocos2dxDownloader');
  const paths = {};
  const create = D.createTask.overload('org.cocos2dx.lib.Cocos2dxDownloader', 'int', 'java.lang.String', 'java.lang.String', 'int');
  create.implementation = function (downloader, id, url, path, option) {
    paths[id] = String(path);
    send({event:'download_start', id:id, url:safeUrl(url), query_present:String(url).indexOf('?') >= 0, path:String(path), option:option});
    return create.call(this, downloader, id, url, path, option);
  };
  const finish = D.onFinish.overload('int', 'int', 'java.lang.String', '[B');
  finish.implementation = function (id, code, error, data) {
    let file = paths[id] ? Java.use('java.io.File').$new(paths[id]) : null;
    send({event:'download_finish', id:id, code:code, error_present:error !== null && String(error).length > 0, bytes:data === null ? null : data.length, file_exists:file === null ? null : file.exists(), file_size:file === null ? null : String(file.length())});
    return finish.call(this, id, code, error, data);
  };
  const nativeFinish = D.nativeOnFinish.overload('int', 'int', 'int', 'java.lang.String', '[B');
  nativeFinish.implementation = function (downloader, id, code, error, data) {
    send({event:'native_finish_enter', id:id, code:code});
    const result = nativeFinish.call(this, downloader, id, code, error, data);
    send({event:'native_finish_return', id:id});
    return result;
  };
  const H = Java.use('com.loopj.android.http.AsyncHttpResponseHandler');
  const response = H.sendResponseMessage.overload('cz.msebera.android.httpclient.HttpResponse');
  response.implementation = function (http) {
    const uri = this.getRequestURI();
    if (uri !== null && String(uri).indexOf('cloudfront.net') >= 0) {
      const entity = http.getEntity();
      const headers = http.getAllHeaders();
      send({event:'http_response',url:safeUrl(uri),status:http.getStatusLine().getStatusCode(),content_length:entity === null ? null : String(entity.getContentLength()),header_names:headers.map(h=>String(h.getName()))});
    }
    return response.call(this,http);
  };
  const success = H.sendSuccessMessage.overload('int','[Lcz.msebera.android.httpclient.Header;','[B');
  success.implementation = function (code,headers,data) {
    const uri = this.getRequestURI();
    if (uri !== null && String(uri).indexOf('cloudfront.net') >= 0)
      send({event:'http_success',url:safeUrl(uri),status:code,bytes:data === null ? null : data.length});
    return success.call(this,code,headers,data);
  };
  const A = Java.use('com.loopj.android.http.AsyncHttpClient');
  A.sendRequest.overloads.forEach(function (overload) {
    const index=overload.argumentTypes.findIndex(t=>/HttpUriRequest|HttpRequestBase/.test(t.className));
    if(index < 0) return;
    overload.implementation = function () {
      const args=Array.from(arguments),request=args[index],uri=String(request.getURI());
      if(uri.indexOf('cloudfront.net') >= 0)
        send({event:'http_request',url:safeUrl(uri),method:String(request.getMethod()),query_keys:uri.indexOf('?')<0?[]:uri.split('?')[1].split('&').map(x=>x.split('=')[0])});
      return overload.apply(this,args);
    };
  });
  const C = Java.use('org.cocos2dx.lib.Cocos2dxHttpURLConnection');
  const open = C.createHttpURLConnection.overload('java.lang.String');
  open.implementation = function (url) {
    send({event:'cocos_http_open',url:safeUrl(url),query_present:String(url).indexOf('?')>=0});
    return open.call(this,url);
  };
  const status = C.getResponseCode.overload('java.net.HttpURLConnection');
  status.implementation = function (connection) {
    const code=status.call(this,connection);
    send({event:'cocos_http_status',url:safeUrl(connection.getURL()),code:code});
    return code;
  };
  let captured=0;
  const request = C.sendRequest.overload('java.net.HttpURLConnection','[B');
  request.implementation = function(connection,data) {
    const url=String(connection.getURL());
    if(url==='https://collector-v2.spinxgames.com/send_cf_log' && data!==null && data.length <= 65536 && captured++ < 60)
      send({event:'startup_log_body',index:captured},new Uint8Array(Array.from(data,x=>x&255)).buffer);
    return request.call(this,connection,data);
  };
  send({event:'ready', arch:Process.arch});
});
"""


def main():
    OUTPUT.mkdir(parents=True, exist_ok=True)
    device = frida.get_device_manager().add_remote_device("127.0.0.1:27605")
    pid = device.spawn([PACKAGE])
    session = None
    resumed = False
    try:
        session = device.attach(pid)
        with (OUTPUT / ("5605_startup_downloads_" + RUN_ID + ".jsonl")).open("x", encoding="utf-8") as output:
            def message(item, _data):
                if item.get('type') == 'send' and item.get('payload', {}).get('event') == 'startup_log_body':
                    index = item['payload']['index']
                    with (OUTPUT / ('startup_log_local_' + RUN_ID + '_%02d.bin' % index)).open('xb') as raw:
                        raw.write(_data)
                    return
                row = {"time": time.time(), "message": item}
                line = json.dumps(row, ensure_ascii=False)
                output.write(line + "\n")
                output.flush()
                print(line, flush=True)

            script = session.create_script(SCRIPT)
            script.on("message", message)
            script.load()
            device.resume(pid)
            resumed = True
            time.sleep(35)
    finally:
        if not resumed:
            device.resume(pid)
        if session:
            session.detach()


if __name__ == "__main__":
    main()
