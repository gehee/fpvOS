#!/bin/sh
# The fpvOS air app, started by the hook in the stock fpv_run_cx482.sh once the
# USB gadget, the PC tool's updater and the MPP modules are up, in place of the
# stock radio driver, daemon and air app. Output goes to /tmp/air.log.
#
#   $1 board_type  $2 board_ver  $3 HW_VER  $4 rf_board
#
# It never touches the updater, and never blocks the caller.

board_type=$1
board_ver=$2
HW_VER=$3
rf_board=$4
air=/usrdata/fpv/air

echo "air: fpvOS $(cat $air/VERSION) board_type=$board_type board_ver=$board_ver hw=$HW_VER rf=$rf_board"

# The USB network (192.168.2.1 and a DHCP server) is set up by our
# usb_ip.sh, which the stock config_ether.sh runs when the link is switched to
# network.

# SSH when the image carries keys (FPVOS_AIR_SSH_KEYS at build time) or a root
# password (FPVOS_AIR_ROOT_PASSWORD, root by default); reachable once the USB link is switched to
# network (enable_rndis.py). The password goes in a copy of /etc/shadow
# mounted over the stock one, in RAM: the stock rootfs is never written. The
# host key is made on the first boot, in the writable app volume. First, so a
# stuck air app cannot keep you out.
ssh=$air/ssh
pwopt="-s -g"                     # no password login
if [ -s $ssh/root.hash ]; then
	awk -F: -v OFS=: -v h="$(cat $ssh/root.hash)" '$1 == "root" { $2 = h } { print }' \
		/etc/shadow > /tmp/shadow && chmod 0600 /tmp/shadow &&
		mount --bind /tmp/shadow /etc/shadow && pwopt="" &&
		echo "air: root password set"
fi
if [ -s $ssh/authorized_keys ] || [ -z "$pwopt" ]; then
	[ -s $ssh/dropbear_ed25519_host_key ] ||
		$air/bin/dropbearkey -t ed25519 -f $ssh/dropbear_ed25519_host_key
	$air/bin/dropbear -r $ssh/dropbear_ed25519_host_key -D $ssh $pwopt -P /tmp/dropbear.pid &&
		echo "air: ssh on port 22"
fi

# The stock radio start, with ar_libre's arlink.ko in place of artosyn_sdio.ko
# and no daemon: the same chip firmware and config, picked the same way as
# boot_ar8030/boot_ar8030.sh does (rf_board 17 is the cx472 v1.1 board).
if [ "$board_type" = 472 ]; then
	if [ "$rf_board" = 17 ]; then bb_cfg=bb_config_sky_cx472_v11.json; else bb_cfg=bb_config_sky_cx472.json; fi
	bb_fw=bb_demo_sky_cx472.img
else
	bb_fw=bb_demo_sky_3v3.img
	bb_cfg=bb_config_sky.json
fi
echo -n /usrdata/fpv/boot_ar8030 > /sys/module/firmware_class/parameters/path

# Open8030, the open radio firmware, when open8030/always says so, with the
# board's own stock radio config ($bb_cfg): both are copied to one directory for
# the firmware loader. One image serves the Lite and the Lite+ - their radio
# chips boot the same way (pins, pads, I/O domains), so their profiles are the
# same. If the copy fails the boot stays on stock's firmware. Remove the flag to
# go back.
if [ -e $air/open8030/always ] && { [ "$board_type" = 472 ] || [ "$board_type" = 482 ]; } &&
   [ -s $air/open8030/open8030-ap.img ]; then
	mkdir -p /tmp/o8030 && cp $air/open8030/open8030-ap.img /usrdata/fpv/boot_ar8030/$bb_cfg /tmp/o8030/ &&
		echo -n /tmp/o8030 > /sys/module/firmware_class/parameters/path && bb_fw=open8030-ap.img &&
		echo "air: Open8030 radio firmware $(cat $air/open8030/version 2>/dev/null) ($bb_cfg)"
fi

# kestrel-air runs the Lite (482) and the Lite+ (472), as told apart by the
# stock board script (fpv_run_by_type.sh); any other board keeps stock.
export KA_BOARD_TYPE=$board_type
case $board_type in
482|472) ours=1 ;;
*) ours=0; echo "air: board type $board_type is not a Lite or Lite+" ;;
esac

if [ $ours = 1 ] && [ -x $air/kestrel-air ] && insmod $air/arlink.ko fw_name=$bb_fw cfg_name=$bb_cfg; then
	echo "air: arlink $(cat $air/ar-libre.version 2>/dev/null)"
	for i in 1 2 3 4 5 6 7 8 9 10 11 12 13 14 15; do
		[ -e /dev/arlink0 ] && break
		sleep 1
	done
	[ -e /dev/arlink0 ] && echo "air: /dev/arlink0 after $i s" || echo "air: NO /dev/arlink0 after 15 s"
	echo "air: kestrel-air $(cat $air/kestrel-air.version 2>/dev/null)"
	$air/run-kestrel-air.sh &
else
	# Not a Lite or Lite+, arlink.ko did not load (before it touches the chip),
	# or there is no kestrel-air: the stock radio driver, daemon and air app.
	echo "air: running the stock radio and air app"
	cd /usrdata/fpv/boot_ar8030 && ./boot_ar8030.sh $board_type $rf_board
	sleep 3
	telnetd &
	cd /usrdata/fpv
	./daemon_sdiov12 -i 1 &
	sleep 0.1
	./ar_ldyhs_sky --board_type $board_type --board_ver $board_ver &
	./ar_fpvhs_mp_service --hwver $HW_VER --board_type $board_type &
fi
