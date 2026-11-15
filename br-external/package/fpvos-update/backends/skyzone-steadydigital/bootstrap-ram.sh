#!/bin/sh
# All writable state is quiesced before touching the inactive UBI volume.
set -eu
work=${1:?}
mode=${2:?}
case "$work" in /tmp/fpvos-bootstrap.*) ;; *) exit 1;; esac
[ "$0" = "$work/prepare.sh" ]
[ "$mode" = update ]
root=$work/root
PATH=$root/bin:$root/usr/sbin:$root/usr/libexec
export PATH
exec >"$work/bootstrap.log" 2>&1
for process in ar_lowdelay ota_upgrade auto_sync daemon servicemanager; do
    ! pidof "$process" >/dev/null || { echo "Unexpected stock application: $process"; exit 1; }
done
# Only the normal early clean boot is supported, before stock starts media.
for binding in /sys/kernel/config/usb_gadget/*/UDC; do
    [ ! -e "$binding" ] || [ -z "$(cat "$binding")" ] || exit 1
done
umount /tmp/usrlog
umount /factory
umount /usrdata
sync
if [ ! -d /sys/kernel/config/usb_gadget ]; then mount -t configfs none /sys/kernel/config; fi
gadget=/sys/kernel/config/usb_gadget/fpvos-bootstrap
mkdir "$gadget"
echo 0x1d6b >"$gadget/idVendor"
echo 0x0104 >"$gadget/idProduct"
echo 0x0200 >"$gadget/bcdUSB"
echo 0xef >"$gadget/bDeviceClass"
echo 0x02 >"$gadget/bDeviceSubClass"
echo 0x01 >"$gadget/bDeviceProtocol"
mkdir -p "$gadget/strings/0x409" "$gadget/configs/c.1/strings/0x409"
echo Skyzone >"$gadget/strings/0x409/manufacturer"
echo 'SteadyDigital - fpvOS [bootstrap]' >"$gadget/strings/0x409/product"
echo fpvos-steadydigital >"$gadget/strings/0x409/serialnumber"
echo 'RAM recovery' >"$gadget/configs/c.1/strings/0x409/configuration"
echo 250 >"$gadget/configs/c.1/MaxPower"
mkdir "$gadget/functions/rndis.usb0" "$gadget/functions/acm.usb0"
echo 02:93:11:00:02:01 >"$gadget/functions/rndis.usb0/dev_addr"
echo 02:93:11:00:02:02 >"$gadget/functions/rndis.usb0/host_addr"
ln -s "$gadget/functions/rndis.usb0" "$gadget/configs/c.1/rndis.usb0"
ln -s "$gadget/functions/acm.usb0" "$gadget/configs/c.1/acm.usb0"
echo 8000000.usb >"$gadget/UDC"
ip address add 192.168.3.104/24 dev usb0
ip link set usb0 up
# Stock SSH is retained for diagnostics with its existing credentials/host key.
/bin/dropbear
mount --bind /dev "$root/dev"
mount --bind /proc "$root/proc"
mount --bind /sys "$root/sys"
: >"$root/run/fpvos-clean-boot"
exec chroot "$root" /bin/sh -c 'PATH=/bin:/usr/sbin:/usr/libexec; export PATH; exec /usr/sbin/fpvos-update receive /dev/ttyGS0 /run/fpvos-update /usr/libexec/fpvos-update-backend'
