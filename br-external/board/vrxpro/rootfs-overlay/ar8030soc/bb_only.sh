#!/bin/sh
# Bring up the AR8030 baseband + daemon ONLY (no ar_ldy_gnd), for kestrel-gnd --link ar8030.
#
# The chip boots in bootloader mode (4152:8030). Loading artosyn_drv with
# fw_name/cfg_name uploads the baseband firmware; the chip then re-enumerates
# as 1d6b:8030 ("HS Mode") and the *resident* driver probes it again, creating
# /dev/ar_mdev0 + /dev/ar_net0. Those nodes are what the daemon exports on
# :50000 and what bb_dev_getlist() finds.
#
# Do NOT rmmod after the upload: loading the driver once the chip is already in
# HS mode produces no probe event (no hotplug), so the device nodes never
# appear and bb_dev_getlist() returns 0.

# Which baseband profile to upload with the firmware.
#
#   caddx  - the stock Ascent/Caddx profile, for the original air unit.
#
# Boot always uses `caddx` unless /usrdata/bb_profile says otherwise. Experiment
# without touching the boot path by passing the profile in the environment:
#
#   BB_PROFILE=try BB_CFG=bb_config_try.json /ar8030soc/bb_only.sh   # ad-hoc config
#
# A config the baseband firmware cannot run does NOT fail cleanly: the chip
# resets back into BL1, the resident driver re-probes it and re-uploads, and
# the two spin at ~2 Hz flooding the console. See the guard after the wait loop.
BB_PROFILE="${BB_PROFILE:-$(cat /usrdata/bb_profile 2>/dev/null || echo caddx)}"
case "$BB_PROFILE" in
    caddx) BB_CFG="${BB_CFG:-bb_config_gnd_pro.json}" ;;
    try)   BB_CFG="${BB_CFG:-bb_config_try.json}" ;;
    *)     echo ">> unknown bb profile '$BB_PROFILE', falling back to caddx"
           BB_PROFILE=caddx; BB_CFG=bb_config_gnd_pro.json ;;
esac

# The firmware blob is not profile-dependent; only the config changes.
# Overridable so a newer baseband build can be tried without a rebuild:
#   BB_FW=bb_demo_cx485_2PA_18.21.10.img BB_PROFILE=try /ar8030soc/bb_only.sh
# The driver uploads this to the chip's RAM on every bring-up - nothing is
# written to the AR8030 permanently, so a reboot always returns to the default.
BB_FW="${BB_FW:-bb_demo_cx485_2PA.img}"

mkdir -p /usrdata/record
mountpoint -q /usrdata/record || mount -t tmpfs -o size=64M tmpfs /usrdata/record

gpio_lo() {
    echo "$1" > /sys/class/gpio/export 2>/dev/null
    echo out > /sys/class/gpio/gpio"$1"/direction
    echo 0 > /sys/class/gpio/gpio"$1"/value
}

echo ">> state before: $(lsusb | grep -i 8030 || echo 'no 8030 on USB')"

echo ">> pwm_ctl.sh (fan/led/buzzer) - stock does this before the radio"
/ar8030soc/pwm_ctl.sh > /dev/null 2>&1

# Other bits stock sets before the radio comes up.
sysctl -w net.core.wmem_max=4194304 > /dev/null 2>&1
sysctl -w net.ipv4.tcp_wmem="4096 2097152 8388608" > /dev/null 2>&1
echo 40000000 > /proc/sys/vm/dirty_bytes 2>/dev/null

echo ">> enable_rf (GPIO power-on)"
for g in 154 83 84 82; do gpio_lo "$g"; done
usleep 100000
echo 1 > /sys/class/gpio/gpio83/value
echo 1 > /sys/class/gpio/gpio84/value
usleep 50000
echo 1 > /sys/class/gpio/gpio154/value
usleep 50000
echo 1 > /sys/class/gpio/gpio82/value
usleep 280000
echo in > /sys/class/gpio/gpio84/direction
echo in > /sys/class/gpio/gpio83/direction
echo in > /sys/class/gpio/gpio82/direction

[ -e /usr/lib/firmware ] || { mkdir -p /usr/lib; ln -s /lib/firmware /usr/lib/firmware; }
echo ">> baseband profile: $BB_PROFILE ($BB_CFG)"

# Stock also starts ar_fpv_upgrade here, twice: -c 1, its firmware upgrade
# agent (flash_erase / nandwrite / mtd_write, reboot to recovery), and -x, a
# merge of /factory/fpv_bb_freq.json into the channel list. fpvOS runs
# neither and does not ship the binary: it upgrades by reflashing the SD card
# and never writes the NAND, and the merge never ran here anyway (it gave up
# on the missing /factory/app.version) while the link worked without it.

echo ">> insmod artosyn_drv (uploads fw, stays resident for the HS-mode re-probe)"
insmod /ar8030soc/artosyn_drv.ko fw_name=$BB_FW cfg_name=$BB_CFG 2>&1

# Wait for the chip to come back as HS mode and the driver to re-probe it.
n=0
while [ ! -e /dev/ar_mdev0 ] && [ "$n" -lt 30 ]; do
    sleep 1
    n=$((n + 1))
done

if [ -e /dev/ar_mdev0 ]; then
    echo ">> ar_mdev0 present after ${n}s"
else
    # The chip never reached HS mode. Leaving the driver resident here is not
    # harmless: it keeps re-probing the BL1 device and re-uploading, which locks
    # the console into a scroll of ar_usb_probe / upgrade bb_cfg lines and never
    # converges. Unload it so the failure is quiet and recoverable.
    echo ">> ERROR: ar_mdev0 never appeared (${n}s) with profile '$BB_PROFILE' ($BB_CFG)"
    echo ">> unloading artosyn_drv to stop the BL1 re-upload loop"
    rmmod artosyn_drv 2>/dev/null
    echo ">> recover with: BB_PROFILE=caddx /ar8030soc/bb_only.sh"
    exit 1
fi

echo ">> starting daemon (broker on :50000)   [note: -l is NOT a valid option]"
setsid nice -n -5 /ar8030soc/daemon -i 0 < /dev/null > /tmp/daemon.log 2>&1 &
sleep 3

echo "--- usb ---";     lsusb | grep -i 8030
echo "--- driver ---";  lsmod | grep artosyn || echo "NOT LOADED"
echo "--- devices ---"; ls /dev/ar_* 2>&1
echo "--- daemon ---";  ps w | grep '[a]r8030soc/daemon' | head -2
echo "--- :50000 ---";  netstat -ltn 2>/dev/null | grep 50000 || echo "NOT LISTENING"
echo "--- daemon log ---"; head -5 /tmp/daemon.log
