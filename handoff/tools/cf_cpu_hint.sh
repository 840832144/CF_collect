#!/system/bin/sh
# Is the CF process actually working (CPU busy) or just parked?
PKG=slots.pcg.casino.games.free.android
P=$(pidof $PKG)
if [ -z "$P" ]; then echo "not running"; exit 1; fi
echo "pid=$P"
a=$(cat /proc/$P/stat | sed 's/.*) //' | cut -d' ' -f12,13)
sleep 20
b=$(cat /proc/$P/stat | sed 's/.*) //' | cut -d' ' -f12,13)
echo "utime1/stime1: $a"
echo "utime2/stime2: $b"
echo "state: $(cat /proc/$P/stat | sed 's/.*) //' | cut -d' ' -f1)"
