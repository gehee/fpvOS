#!/bin/sh
# Restart the AR8030 baseband by hand, with kestrel-gnd stopped around it.
#
# kestrel-gnd restarts the baseband itself when it cannot connect, so this is
# for when you want it done now: a stuck link, or after changing the baseband
# profile (/usrdata/bb_profile). kestrel-gnd is stopped through S70kestrel - it
# is supervised, and killing the process alone just starts it again, holding
# /dev/arlinkN so arlink cannot be unloaded - and started again once the radio
# is back.
#
# Waits up to 60s for the radio; override with an argument:
#     /root/bb-restart.sh 90

WAIT="${1:-60}"

echo "bb-restart: stopping kestrel-gnd"
/etc/init.d/S70kestrel stop

echo "bb-restart: restarting baseband"
/etc/init.d/S60ar8030 restart >/dev/null 2>&1

i=0
while [ "$i" -lt "$WAIT" ] && ! ls /dev/arlink[0-9]* >/dev/null 2>&1; do
    sleep 1
    i=$((i + 1))
    printf "\rbb-restart: waiting for the radio %ss/%ss" "$i" "$WAIT"
done
printf "\n"

if ls /dev/arlink[0-9]* >/dev/null 2>&1; then
    echo "bb-restart: $(ls /dev/arlink[0-9]* | head -1) up after ${i}s - starting kestrel-gnd"
else
    echo "bb-restart: WARNING no /dev/arlinkN after ${WAIT}s (see /var/log/ar8030-boot.log);" \
         "starting kestrel-gnd anyway, it retries the baseband itself"
fi
/etc/init.d/S70kestrel start
