"""SNI relay: lets the BlueStacks guest reach blocked Google hosts through the host's HTTP proxy.

Why this exists: the guest's native stack (Cocos/libcurl) and Google Play services both ignore
`settings put global http_proxy`, so they connect straight to Google IPs and hang. This relay
listens on the host loopback, reads the TLS ClientHello to learn which host the guest wants,
then tunnels to that host through the proxy that already works (default 127.0.0.1:29290).

In the guest we DNAT only the Google ranges into it:

    iptables -t nat -A OUTPUT -p tcp --dport 443 -d 172.217.0.0/16   -j DNAT --to-destination 10.0.2.2:443
    iptables -t nat -A OUTPUT -p tcp --dport 443 -d 216.239.32.0/20 -j DNAT --to-destination 10.0.2.2:443
    iptables -t nat -A OUTPUT -p tcp --dport 443 -d 142.250.0.0/15  -j DNAT --to-destination 10.0.2.2:443
    iptables -t nat -A OUTPUT -p tcp --dport 443 -d 142.251.0.0/16  -j DNAT --to-destination 10.0.2.2:443

usage:  python google_sni_relay.py [--port 443] [--proxy 127.0.0.1:29290]
"""
import argparse, select, socket, struct, sys, threading, time

sys.stdout.reconfigure(encoding="utf-8", errors="replace")


def read_client_hello_sni(buf):
    """Return the SNI hostname from a TLS ClientHello, or None if not yet complete."""
    if len(buf) < 5 or buf[0] != 0x16:
        return None
    rec_len = struct.unpack("!H", buf[3:5])[0]
    if len(buf) < 5 + rec_len:
        return None
    p = 5 + 4 + 2 + 32          # handshake hdr + version + random
    if len(buf) < p + 1:
        return None
    sid_len = buf[p]
    p += 1 + sid_len
    if len(buf) < p + 2:
        return None
    cs_len = struct.unpack("!H", buf[p:p + 2])[0]
    p += 2 + cs_len
    if len(buf) < p + 1:
        return None
    cm_len = buf[p]
    p += 1 + cm_len
    if len(buf) < p + 2:
        return None
    ext_total = struct.unpack("!H", buf[p:p + 2])[0]
    p += 2
    end = min(p + ext_total, len(buf))
    while p + 4 <= end:
        etype, elen = struct.unpack("!HH", buf[p:p + 4])
        p += 4
        if etype == 0x00 and p + elen <= end:            # server_name
            q = p + 2
            name_type = buf[q]
            nlen = struct.unpack("!H", buf[q + 1:q + 3])[0]
            if name_type == 0:
                return buf[q + 3:q + 3 + nlen].decode("ascii", "replace")
        p += elen
    return None


def connect_via_proxy(proxy_host, proxy_port, target_host, target_port=443, timeout=20):
    s = socket.create_connection((proxy_host, proxy_port), timeout=timeout)
    req = "CONNECT %s:%d HTTP/1.1\r\nHost: %s:%d\r\nProxy-Connection: keep-alive\r\n\r\n" % (
        target_host, target_port, target_host, target_port)
    s.sendall(req.encode())
    head = b""
    s.settimeout(timeout)
    while b"\r\n\r\n" not in head:
        chunk = s.recv(4096)
        if not chunk:
            raise OSError("proxy closed during CONNECT")
        head += chunk
        if len(head) > 16384:
            raise OSError("CONNECT response too large")
    status = head.split(b"\r\n", 1)[0].decode("latin-1")
    if " 200" not in status:
        raise OSError("proxy refused: %s" % status)
    rest = head.split(b"\r\n\r\n", 1)[1]
    return s, rest


def pipe(a, b, leftover=b""):
    if leftover:
        b.sendall(leftover)
    socks = [a, b]
    try:
        while True:
            r, _, _ = select.select(socks, [], [], 60)
            if not r:
                continue
            for s in r:
                data = s.recv(65536)
                if not data:
                    return
                (b if s is a else a).sendall(data)
    except Exception:
        pass
    finally:
        for s in (a, b):
            try:
                s.close()
            except Exception:
                pass


def handle(conn, addr, proxy, log):
    conn.settimeout(20)
    buf = b""
    try:
        while True:
            chunk = conn.recv(4096)
            if not chunk:
                return
            buf += chunk
            sni = read_client_hello_sni(buf)
            if sni:
                break
            if len(buf) > 65536:
                log("  no SNI, drop %s" % (addr[0],))
                return
        log("  %s -> %s" % (addr[0], sni))
        upstream, leftover = connect_via_proxy(proxy[0], proxy[1], sni)
        upstream.sendall(buf)                    # replay the ClientHello
        if leftover:
            conn.sendall(leftover)
        pipe(conn, upstream)
    except Exception as e:
        log("  fail: %s" % e)
        try:
            conn.close()
        except Exception:
            pass


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=443)
    ap.add_argument("--bind", default="127.0.0.1")
    ap.add_argument("--proxy", default="127.0.0.1:29290")
    a = ap.parse_args()
    ph, pp = a.proxy.split(":")
    proxy = (ph, int(pp))
    lock = threading.Lock()

    def log(msg):
        with lock:
            print(time.strftime("%H:%M:%S"), msg, flush=True)

    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind((a.bind, a.port))
    srv.listen(128)
    log("SNI relay on %s:%d  -> proxy %s:%d" % (a.bind, a.port, proxy[0], proxy[1]))
    while True:
        c, addr = srv.accept()
        threading.Thread(target=handle, args=(c, addr, proxy, log), daemon=True).start()


if __name__ == "__main__":
    main()
