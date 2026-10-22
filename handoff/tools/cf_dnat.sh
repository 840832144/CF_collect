#!/system/bin/sh
# Route the blocked Google ranges into the host SNI relay (10.0.2.2:443).
# The relay reads the TLS SNI and tunnels to that host through the working host proxy.
CLEAR=0
for r in 172.217.0.0/16 216.239.32.0/20 142.250.0.0/15 142.251.0.0/16 74.125.0.0/16 173.194.0.0/16; do
  iptables -t nat -D OUTPUT -p tcp --dport 443 -d $r -j DNAT --to-destination 10.0.2.2:443 2>/dev/null
  iptables -t nat -A OUTPUT -p tcp --dport 443 -d $r -j DNAT --to-destination 10.0.2.2:443 || echo "FAIL $r"
done
iptables -t nat -L OUTPUT -n | head -12
