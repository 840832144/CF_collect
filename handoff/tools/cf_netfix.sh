#!/system/bin/sh
# Route blocked Google + Meta(Facebook) IPv4 ranges into the host SNI relay (10.0.2.2:443),
# and REJECT their IPv6 ranges so clients fall back to IPv4.
# The relay reads the TLS SNI and tunnels to that host through the host proxy (29290).

GOOGLE4="172.217.0.0/16 216.239.32.0/20 142.250.0.0/15 142.251.0.0/16 74.125.0.0/16 173.194.0.0/16"
META4="31.13.24.0/21 31.13.64.0/18 45.64.40.0/22 66.220.144.0/20 69.63.176.0/20 69.171.224.0/19
74.119.76.0/22 102.132.96.0/20 103.4.96.0/22 129.134.0.0/16 157.240.0.0/16 173.252.64.0/18
179.60.192.0/22 185.60.216.0/22 204.15.20.0/22 163.70.128.0/17"

for r in $GOOGLE4 $META4; do
  iptables -t nat -D OUTPUT -p tcp --dport 443 -d $r -j DNAT --to-destination 10.0.2.2:443 2>/dev/null
  iptables -t nat -A OUTPUT -p tcp --dport 443 -d $r -j DNAT --to-destination 10.0.2.2:443 || echo "FAIL4 $r"
done

for p in 2001:4860::/32 2607:f8b0::/32 2404:6800::/32 2a00:1450::/32 2a03:2880::/32 2620:0:1c00::/40; do
  ip6tables -D OUTPUT -d $p -j REJECT 2>/dev/null
  ip6tables -A OUTPUT -d $p -j REJECT || echo "FAIL6 $p"
done

echo "--- nat OUTPUT count ---"
iptables -t nat -L OUTPUT -n | grep -c DNAT
echo "--- ip6 REJECT count ---"
ip6tables -L OUTPUT -n | grep -c REJECT
