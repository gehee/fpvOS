#!/bin/sh
# Embedded in fpvos-update. Executed by its embedded BusyBox after RAM re-exec.
set -eu
fail() { echo "fpvOS RAM bootstrap failed: $*; no automatic reboot" >&2; exit 1; }
work=${1:?missing RAM directory}
case "$work" in /tmp/fpvos-bootstrap.*) ;; *) fail 'invalid RAM directory' ;; esac
[ "$0" = "$work/prepare.sh" ] || fail 'not executing embedded RAM script'
root=$work/root
PATH=$root/bin:$root/usr/sbin:$root/usr/libexec
export PATH
[ "$(id -u)" = 0 ] || fail 'root required'
cd "$work"
[ -x /etc/ota-prepare.sh ] || fail 'missing stock preparation'
/bin/sh /etc/ota-prepare.sh real_do || fail 'stock storage preparation'
# The stock media and upgrade processes must never compete with our receiver.
for process in ar_fpv_upgrade ar_ldy_gnd GlassesUI daemon_sdio; do
    if pidof "$process" >/dev/null; then fail "unexpected active process $process"; fi
done
for gpio in 9 10; do
    [ -d "/sys/class/gpio/gpio$gpio" ] || echo "$gpio" >/sys/class/gpio/export
    echo out >"/sys/class/gpio/gpio$gpio/direction"
done
echo 1 >/sys/class/gpio/gpio9/value
echo 0 >/sys/class/gpio/gpio10/value
# Do not call stock usb_gadget_configfs.sh: it adds an askfirst shell on ttyGS0.
[ -d /sys/class/udc/8000000.usb ] || fail 'unexpected USB controller'
if [ ! -d /sys/kernel/config/usb_gadget ]; then
    mount -t configfs none /sys/kernel/config || fail 'configfs'
fi
for binding in /sys/kernel/config/usb_gadget/*/UDC; do
    [ ! -e "$binding" ] || [ -z "$(cat "$binding")" ] || fail 'USB controller already owned'
done
gadget=/sys/kernel/config/usb_gadget/fpvos-bootstrap
mkdir "$gadget" || fail 'gadget already exists'
echo 0x1d6b >"$gadget/idVendor"
echo 0x0104 >"$gadget/idProduct"
echo 0x0200 >"$gadget/bcdUSB"
echo 0x02 >"$gadget/bDeviceClass"
mkdir -p "$gadget/strings/0x409" "$gadget/configs/c.1/strings/0x409"
echo fpvOS >"$gadget/strings/0x409/manufacturer"
echo 'fpvOS AR9311 bootstrap' >"$gadget/strings/0x409/product"
echo fpvos-ar9311 >"$gadget/strings/0x409/serialnumber"
echo 'RAM updater' >"$gadget/configs/c.1/strings/0x409/configuration"
echo 250 >"$gadget/configs/c.1/MaxPower"
mkdir "$gadget/functions/acm.usb0"
ln -s "$gadget/functions/acm.usb0" "$gadget/configs/c.1/acm.usb0"
echo 8000000.usb >"$gadget/UDC"
if [ ! -e /dev/ttyGS0 ]; then
    IFS=: read -r major minor </sys/class/tty/ttyGS0/dev
    case "$major:$minor" in *[!0-9:]*|:*) fail 'invalid serial device numbers';; esac
    mknod -m 600 /dev/ttyGS0 c "$major" "$minor"
fi
[ -c /dev/ttyGS0 ] || fail 'missing USB serial'
[ "$(cat "$gadget/strings/0x409/serialnumber")" = fpvos-ar9311 ] || fail 'USB identity'
[ "$(cat "$gadget/UDC")" = 8000000.usb ] || fail 'USB not bound'
for fd in /proc/[0-9]*/fd/*; do
    [ "$(readlink "$fd" 2>/dev/null || :)" != /dev/ttyGS0 ] || fail 'USB serial already in use'
done
mount --bind /dev "$root/dev" || fail 'RAM device view'
mount --bind /proc "$root/proc" || fail 'RAM process view'
mount --bind /sys "$root/sys" || fail 'RAM sysfs view'
# Chroot isolates paths; the root itself lives entirely on the verified tmpfs.
# The receiver performs clean readiness once, before serving any requests.
: >"$root/run/fpvos-clean-boot"
# Host-side absolute paths above do not exist inside the chroot. The receiver
# launches md5sum via PATH, unlike the backend shell which sets its own PATH.
exec chroot "$root" /bin/sh -c 'export PATH=/bin:/usr/sbin:/usr/libexec; exec /usr/sbin/fpvos-update receive /dev/ttyGS0 /run/fpvos-update /usr/libexec/fpvos-update-backend'
