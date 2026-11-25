#!/bin/sh
# Bring up the AR8030 baseband ONLY (no ar_ldy_gnd), for kestrel-gnd --link ar8030.
#
# The chip boots in bootloader mode (4152:8030). Loading the driver with
# fw_name/cfg_name uploads the baseband firmware; the chip then re-enumerates
# as 1d6b:8030 ("HS Mode") and the resident driver probes it again.
#
# The driver is fpvOS's own arlink.ko (package ar-libre). The running chip is
# /dev/arlinkN and kestrel's client library talks to it directly: no daemon.
# (Artosyn's binary artosyn_drv.ko only loads into the stock 5.10 kernel, so
# an image with a kernel built from source has no other stack to fall back on.)

# The baseband firmware and the radio config uploaded with it. They come as a
# pair - a config is written for one firmware - and are chosen together:
#
#   Open8030, the open-source baseband firmware, with its own open8030.json:
#     the default when its image is on the unit and kestrel-gnd's RADIO >
#     Radio Firmware does not say STOCK (ar8030_firmware: 0). kestrel-gnd
#     decides the same way, so it knows which firmware it is talking to.
#   Stock's bb_demo_cx485_2PA.img otherwise, with the config of the baseband
#   profile:
#     caddx  - bb_config_gnd_pro.json, the stock Ascent/Caddx profile.
#     try    - bb_config_try.json, an ad-hoc config to experiment with.
#
# The profile is /usrdata/bb_profile, or caddx without one; an unknown one
# falls back to caddx, with a line in the log. The profiles are configs for
# stock's firmware: with Open8030 one other than caddx does not apply, and the
# log says so (RADIO > Radio Firmware: STOCK uses it).
#
# BB_FW / BB_CFG in the environment still win, each over its half of the pair,
# so a newer baseband build or a config can be tried without a rebuild:
#   BB_PROFILE=try /ar8030soc/bb_only.sh
#   BB_FW=bb_demo_cx485_2PA_18.21.10.img BB_PROFILE=try /ar8030soc/bb_only.sh
# The driver uploads both to the chip's RAM on every bring-up - nothing is
# written to the AR8030 permanently, so a reboot always returns to the default.
#
# A config the baseband firmware cannot run does NOT fail cleanly: the chip
# resets back into BL1, the resident driver re-probes it and re-uploads, and
# the two spin at ~2 Hz flooding the console. See the guard after the wait loop.
select_pair() {
    BB_PROFILE="${BB_PROFILE:-$(cat /usrdata/bb_profile 2>/dev/null || echo caddx)}"
    case "$BB_PROFILE" in
        caddx|try) ;;
        *) echo ">> unknown bb profile '$BB_PROFILE', falling back to caddx"
           BB_PROFILE=caddx ;;
    esac
    if [ -z "$BB_FW" ]; then
        if ! grep -q '^ar8030_firmware: 0$' /etc/kestrel/kestrel-gnd.yaml 2>/dev/null &&
           [ -f /lib/firmware/open8030.img ]; then
            BB_FW=open8030.img
        else
            BB_FW=bb_demo_cx485_2PA.img
        fi
    fi
    [ -n "$BB_CFG" ] && return 0
    case "$BB_FW" in
        open8030*)
            BB_CFG=open8030.json
            [ "$BB_PROFILE" = caddx ] ||
                echo ">> bb profile '$BB_PROFILE' is a config for stock's firmware; Open8030 runs with $BB_CFG (RADIO > Radio Firmware: STOCK to use it)" ;;
        *)
            case "$BB_PROFILE" in
                try) BB_CFG=bb_config_try.json ;;
                *)   BB_CFG=bb_config_gnd_pro.json ;;
            esac ;;
    esac
}
select_pair

# One bring-up at a time. kestrel-gnd asks for one (S60ar8030 restart) each
# time it cannot connect, and in a crash loop it can ask again before the last
# has finished: the second waits for the first, then does its own.
exec 9> /var/run/bb_only.lock
flock -w 90 9 || { echo ">> ERROR: another bring-up held the lock for 90s"; exit 1; }

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

# Unload a resident copy so this bring-up's firmware and config are the ones
# uploaded once the power cycle below sends the chip back to its boot ROM. If a
# program still has /dev/arlinkN open this fails, and the resident copy
# uploads with the parameters it was loaded with.
rmmod arlink 2>/dev/null

arlink_up() { ls /dev/arlink[0-9]* >/dev/null 2>&1; }

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
echo ">> baseband profile: $BB_PROFILE (firmware $BB_FW, config $BB_CFG)"

# Stock also starts ar_fpv_upgrade here, twice: -c 1, its firmware upgrade
# agent (flash_erase / nandwrite / mtd_write, reboot to recovery), and -x, a
# merge of /factory/fpv_bb_freq.json into the channel list. fpvOS runs
# neither and does not ship the binary: it upgrades by reflashing the SD card
# and never writes the NAND, and the merge never ran here anyway (it gave up
# on the missing /factory/app.version) while the link worked without it.

# modprobe finds the module wherever kbuild put it (extra/ on 5.10, updates/
# on 6.x).
echo ">> modprobe arlink (uploads fw, stays resident for the HS-mode re-probe)"
modprobe arlink fw_name=$BB_FW cfg_name=$BB_CFG 2>&1

# Wait for the chip to come back as HS mode and the driver to re-probe it.
n=0
while ! arlink_up && [ "$n" -lt 30 ]; do
    sleep 1
    n=$((n + 1))
done

if arlink_up; then
    echo ">> $(ls /dev/arlink[0-9]* | head -1) present after ${n}s"
else
    # The chip never reached HS mode. A config the firmware cannot run sends
    # the chip back to its boot ROM and the driver re-uploads, until it gives
    # up. Unload it so the failure is quiet and recoverable.
    echo ">> ERROR: no /dev/arlinkN after ${n}s with profile '$BB_PROFILE' ($BB_CFG)"
    echo ">> unloading arlink to stop the BL1 re-upload loop"
    rmmod arlink 2>/dev/null
    echo ">> recover with: BB_PROFILE=caddx /ar8030soc/bb_only.sh"
    exit 1
fi

echo "--- usb ---";     lsusb | grep -i 8030
echo "--- driver ---";  lsmod | grep arlink || echo "NOT LOADED"
echo "--- device ---";  ls -l /dev/arlink* 2>&1
dmesg | grep arlink | tail -3
