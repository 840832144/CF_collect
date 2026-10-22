#!/system/bin/sh
# Force clients onto IPv4 for Google: drop IPv6 routes to Google so they fall back to the
# IPv4 path, which we DNAT into the host SNI relay (10.0.2.2:443).
for p in 2001:4860::/32 2607:f8b0::/32 2404:6800::/32 2a00:1450::/32; do
  ip6tables -D OUTPUT -d $p -j REJECT 2>/dev/null
  ip6tables -A OUTPUT -d $p -j REJECT || echo "FAIL6 $p"
done
# keep IPv4 DNAT rules in place
for r in 172.217.0.0/16 216.239.32.0/20 142.250.0.0/15 142.251.0.0/16 74.125.0.0/16 173.194.0.0/16; do
  iptables -t nat -C OUTPUT -p tcp --dport 443 -d $r -j DNAT --to-destination 10.0.2.2:443 2>/dev/null || \
  iptables -t nat -A OUTPUT -p tcp --dport 443 -d $r -j DNAT --to-destination 10.0.2.2:443
done
echo "--- ip6 OUTPUT ---"
ip6tables -L OUTPUT -n | head -8
echo "--- nat OUTPUT ---"
iptables -t nat -L OUTPUT -n | head -10
