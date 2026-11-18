#!/bin/sh
# fpvOS: the unit's USB network mode, in place of the stock config_ether.sh.
# Run at boot (/factory/run_rndis_flag), live (the updater's network command,
# disable_config_serial.sh first) or from the clean system ("clean": the copy
# in /tmp, with /tmp/usb_ip.sh).
#
# CDC-NCM, which Windows 10 (1903 and later), Windows 11, macOS and Linux all
# take without a driver; stock's RNDIS has none on macOS. The stock kernel has
# no NCM, so usb_f_ncm.ko (ascent-lite-ffs) is loaded from the app volume. If
# it cannot be loaded or NCM does not bind, the gadget is stock's RNDIS.
#
# The IDs and serial number stay stock's: the PC tool and the flasher go by
# them. The name is the unit's, as in normal mode, with " [network]".

exec >/tmp/config_ether.log 2>&1

VID=0x1D6B
PID=0x0002
SERIALNUMBER=123456789012
case $(cat /usrdata/fpv/fpv_board_type /tmp/fpv_board_type 2>/dev/null | head -n 1) in
472) PRODUCT="Ascent Lite+ Air Unit - fpvOS" ;;
482) PRODUCT="Ascent Lite Air Unit - fpvOS" ;;
*) PRODUCT="Ascent Air Unit - fpvOS" ;;
esac
PRODUCT="$PRODUCT [network]"

USB_IP_SCRIPT=/usrdata/fpv/usb_ip.sh
[ "$1" = clean ] && USB_IP_SCRIPT=/tmp/usb_ip.sh

# The serial gadget's teardown (disable_config_serial.sh) runs at the same
# time, unbinds the controller and ends by unmounting configfs. So: mount it
# if it is not, and stand in it, until that holds (a mount in use is not
# unmounted).
for i in 1 2 3 4 5 6 7 8 9 10 11 12 13 14 15 16 17 18 19 20; do
	grep -q " /sys/kernel/config " /proc/mounts || mount -t configfs none /sys/kernel/config
	cd /sys/kernel/config/usb_gadget 2>/dev/null && [ -d ../usb_gadget ] && break
	usleep 100000
done
cd /sys/kernel/config/usb_gadget || exit 1
G=/sys/kernel/config/usb_gadget/ether

# The gadget with one network function, NCM or RNDIS, bound to the controller.
gadget() {
	fn=$1
	mkdir $G && cd $G || return 1
	echo 0x0200 > bcdUSB
	echo 0xef > bDeviceClass
	echo 2 > bDeviceSubClass
	echo 0x01 > bDeviceProtocol
	echo $VID > idVendor
	echo $PID > idProduct
	echo 0x3000 > bcdDevice
	mkdir strings/0x409
	echo Caddx > strings/0x409/manufacturer
	echo "$PRODUCT" > strings/0x409/product
	echo $SERIALNUMBER > strings/0x409/serialnumber
	mkdir configs/c.1
	echo 0xC0 > configs/c.1/bmAttributes
	echo 1 > configs/c.1/MaxPower
	mkdir configs/c.1/strings/0x409
	echo "$fn" | tr a-z A-Z > configs/c.1/strings/0x409/configuration
	# Microsoft OS descriptors: Windows binds RNDIS by them, and its NCM
	# driver too where it does not by class alone (Windows 10).
	echo 1 > os_desc/use
	echo 0xcd > os_desc/b_vendor_code
	echo MSFT100 > os_desc/qw_sign
	mkdir functions/$fn.usb0 || return 1
	if [ $fn = ncm ]; then
		# Fixed addresses: the computer keeps one interface for the unit.
		# The unit's own is usb_ip.sh's.
		echo 00:23:11:06:90:04 > functions/ncm.usb0/dev_addr
		echo 02:23:11:06:90:05 > functions/ncm.usb0/host_addr
		[ -d functions/ncm.usb0/os_desc/interface.ncm ] &&
			echo WINNCM > functions/ncm.usb0/os_desc/interface.ncm/compatible_id
	else
		echo RNDIS > functions/rndis.usb0/os_desc/interface.rndis/compatible_id
		echo 5162001 > functions/rndis.usb0/os_desc/interface.rndis/sub_compatible_id
	fi
	ln -s functions/$fn.usb0 configs/c.1
	ln -s configs/c.1 os_desc
	# The controller takes one gadget: wait for the serial one to let it go.
	# One write, as stock: busybox ls writes the name and its newline apart,
	# and the newline alone unbinds the gadget again.
	udc=$(ls /sys/class/udc/)
	for i in 1 2 3 4 5 6 7 8 9 10 11 12 13 14 15 16 17 18 19 20 21 22 23 24 25 26 27 28 29 30; do
		[ -z "$(cat ../acm/UDC 2>/dev/null)" ] && echo "$udc" > UDC 2>/dev/null &&
			[ -n "$(cat UDC)" ] && return 0
		usleep 100000
	done
	return 1
}

ungadget() {
	cd /sys/kernel/config/usb_gadget || return
	[ -d $G ] || return 0
	echo > $G/UDC
	rm -f $G/os_desc/c.1 $G/configs/c.1/*.usb0
	for d in $G/configs/c.1/strings/0x409 $G/configs/c.1 $G/functions/* $G/strings/0x409 $G; do
		[ -d "$d" ] && rmdir "$d"
	done
}

if { [ -d /sys/module/usb_f_ncm ] || insmod /usrdata/fpv/air/usb/usb_f_ncm.ko; } && gadget ncm; then
	echo "air: USB network as NCM"
else
	ungadget
	gadget rndis
	echo "air: USB network as RNDIS"
fi

if [ -x "$USB_IP_SCRIPT" ]; then
	"$USB_IP_SCRIPT"
else
	echo "Warning: $USB_IP_SCRIPT not found or not executable"
fi
