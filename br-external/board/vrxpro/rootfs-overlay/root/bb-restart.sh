#!/bin/sh
# Restart the AR8030 baseband daemon.
#
# Use this when kestrel-gnd comes up with no video and the log stops after
#     ar8030: subscribe event 12 -> 0
# with no "video socket open" line. That is bb_socket_open() hanging: it sends
# the open request to the daemon and never returns if no reply comes back -
# observed blocking indefinitely, with no timeout. Restarting the daemon resets
# the state it is waiting on.
#
# The wait matters. Coming back too early looks exactly like the restart did not
# work - that misled us more than once. Default 75s; override with an argument:
#     /root/bb-restart.sh 90

WAIT="${1:-75}"

echo "bb-restart: stopping kestrel-gnd if running"
if pidof kestrel-gnd >/dev/null 2>&1; then
    kill -INT "$(pidof kestrel-gnd)" 2>/dev/null
    sleep 6
    # It may be parked inside the vendor client library and unkillable
    # politely; force it.
    pidof kestrel-gnd >/dev/null 2>&1 && kill -9 "$(pidof kestrel-gnd)" 2>/dev/null
fi

echo "bb-restart: restarting baseband"
/etc/init.d/S60ar8030 restart >/dev/null 2>&1

i=0
while [ "$i" -lt "$WAIT" ]; do
    sleep 5
    i=$((i + 5))
    printf "\rbb-restart: settling %ss/%ss" "$i" "$WAIT"
done
printf "\n"

if pidof daemon >/dev/null 2>&1; then
    echo "bb-restart: daemon up (pid $(pidof daemon)) - start kestrel-gnd now"
else
    echo "bb-restart: WARNING daemon is not running"
    exit 1
fi
