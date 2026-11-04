#!/bin/sh
# Runs kestrel-air, and gets the unit back to video if it dies.
#
# The camera pipeline cannot be started a second time until the unit reboots
# (OT_MPI_ISP_MemInit fails), so a crashed kestrel-air cannot just be run again:
# the unit reboots instead. At most 3 times in a row, so that a kestrel-air that
# crashes at once cannot make the unit reboot forever, which would also keep the
# Caddx PC tool from reflashing it. After that it stays up and idle, for ssh.
# A minute of running well resets the count. Stopping it on purpose (exit 0,
# SIGINT, SIGTERM, which is also how a reboot or a reflash ends it) does not
# reboot. What happened is also kept in $air/crash.log, which a reboot does not
# wipe, unlike /tmp/air.log.
air=/usrdata/fpv/air
count=$air/crashes
log=$air/crash.log
max=3

note() {
	echo "air: $*" >> /tmp/air.log
	echo "up $(cut -d. -f1 /proc/uptime) s: $*" >> $log
}

cd $air
[ -f $log ] && [ "$(wc -c < $log)" -gt 20000 ] && tail -n 50 $log > $log.new && mv $log.new $log

# "Running well" is a minute without exiting; the timer is dropped when it exits.
( sleep 60; echo 0 > $count ) &
timer=$!

start=$(cut -d. -f1 /proc/uptime)
# --imu wakes the unit's IMU and carries its samples in the video as SEI
LD_LIBRARY_PATH=$air/lib ./kestrel-air --imu
rc=$?
kill $timer 2>/dev/null
up=$(( $(cut -d. -f1 /proc/uptime) - start ))
note "kestrel-air exited, status $rc, after ${up} s"

case $rc in 0|130|143) exit 0 ;; esac

n=$(cat $count 2>/dev/null || echo 0)
if [ $n -ge $max ]; then
	note "$n reboots in a row without a good run: staying up, not rebooting again"
	sync
	exit 1
fi
echo $((n + 1)) > $count
note "rebooting ($((n + 1)) of $max)"
sync
reboot
