#!/bin/sh
# Assemble the Caddx PC-tool image for the Ascent Lite and Lite+ (Ascent_H_Sky_*.img):
# the stock image from vendor/stock/air/ with a new app volume (/usrdata), made
# of the stock one, plus everything the build put under $TARGET_DIR/usrdata,
# plus fpv_run-hook.sh in the stock board script. U-Boot, env, kernel and
# rootfs stay byte-identical to stock. mkascentimg.py refuses a volume that
# would lose the PC tool's updater.
#
#   FPVOS_AIR_STOCK=PATH  build on another stock image than 18.21.10, on purpose
#                         only: arlink.ko, the SDK libraries and start.sh's
#                         copy of the stock run script are made for 18.21.10
#   FPVOS_RELEASE=1       a release build: no personal SSH keys, no
#                         FPVOS_AIR_STOCK, a clean tree exactly on a tag
set -eu

BOARD=$(cd "$(dirname "$0")" && pwd)
ROOT=$(cd "$BOARD/../../.." && pwd)
MKIMG=$ROOT/boot/mkascentimg.py
RELEASE=${FPVOS_RELEASE:-0}
die() { echo "post-image (air): $*" >&2; exit 1; }

# The stock image it is built on: 18.21.10, the one everything in the app
# volume is made for - arlink.ko's vermagic is its kernel's, kestrel-air links
# its SDK libraries, start.sh repeats what its fpv_run_cx482.sh does. Any other
# is refused unless FPVOS_AIR_STOCK names it.
STOCK_NAME=Ascent_H_Sky_18_21_10.img
STOCK_SHA256=78d9e73ce8ffe3b42991b12cdecca0b7b1140c3f8cbbba484deeedae51301907
if [ -n "${FPVOS_AIR_STOCK:-}" ]; then
	STOCK=$FPVOS_AIR_STOCK
	[ -f "$STOCK" ] || die "FPVOS_AIR_STOCK=$STOCK: no such file"
	[ "$RELEASE" != 1 ] || die "FPVOS_AIR_STOCK is set: a release is built on stock $STOCK_NAME only"
	echo "*** air: built on $STOCK (FPVOS_AIR_STOCK), not on stock $STOCK_NAME: arlink.ko, the SDK libraries and the run script may not match it" >&2
else
	STOCK=$ROOT/vendor/stock/air/$STOCK_NAME
	[ -f "$STOCK" ] ||
		die "no $STOCK: run scripts/extract-ascent-vrx-pro-firmware.py (or set FPVOS_AIR_STOCK to build on another stock image on purpose)"
	sum=$(sha256sum "$STOCK" | cut -d' ' -f1)
	[ "$sum" = "$STOCK_SHA256" ] ||
		die "$STOCK has SHA-256 $sum, not stock 18.21.10's $STOCK_SHA256: extract it again (or set FPVOS_AIR_STOCK to build on another image on purpose)"
fi

# A release: no personal keys, and a clean tree exactly on its tag, so the
# version the unit reports (air/VERSION, below: the SDK field of FIND_DEVICE,
# the boot log) names exactly what is in the image.
if [ "$RELEASE" = 1 ]; then
	[ -z "${FPVOS_AIR_SSH_KEYS:-}" ] ||
		die "FPVOS_AIR_SSH_KEYS is set ($FPVOS_AIR_SSH_KEYS): a release must not carry personal SSH keys - unset it"
	[ -z "$(git -C "$ROOT" status --porcelain --untracked-files=no)" ] ||
		die "FPVOS_RELEASE=1 with uncommitted changes in $ROOT: commit or drop them first"
	git -C "$ROOT" describe --exact-match --tags HEAD > /dev/null 2>&1 ||
		die "FPVOS_RELEASE=1 but HEAD is not exactly on a tag ($(git -C "$ROOT" describe --always --tags --dirty))"
fi

WORK=$BUILD_DIR/air-image
rm -rf "$WORK"
"$MKIMG" extract "$STOCK" "$WORK/stock" >/dev/null
cp -a "$WORK/stock/fpv" "$WORK/fpv"

# The hook goes just before the stock script starts the radio (the line that
# changes into boot_ar8030/): after the updater, the MPP modules and the 2 s wait
# for the baseband to reset, which is everything the PC tool needs and the radio
# needs. Past it, the stock radio driver and air app run as they always did.
run=$WORK/fpv/fpv/fpv_run_cx482.sh
n=$(grep -n '^cd /usrdata/fpv/boot_ar8030' "$run" | head -n 1 | cut -d: -f1)
[ -n "$n" ] || { echo "fpv_run_cx482.sh: no 'cd /usrdata/fpv/boot_ar8030' line to hook before" >&2; exit 1; }
{ head -n $((n - 1)) "$run"; cat "$BOARD/fpv_run-hook.sh"; tail -n +"$n" "$run"; } > "$WORK/run.new"
cat "$WORK/run.new" > "$run"

# The unit's name on USB, in place of stock's "Vendor SerialGadget" and
# "Vendor Ethernet": "Ascent Lite+ Air Unit - fpvOS" (or Lite) by Caddx in
# normal mode, with " [update]" in the clean system (which runs a copy from
# /tmp) and " [network]" for the USB network (config_ether.sh, below). The
# IDs and serial number stay stock's:
# the PC tool and the flasher go by them, never by the name. fpvOS_usb names
# bridge mode the same way, " [bridge]" (PRODUCT in its board settings).
name='case $1 in 472) PRODUCT="Ascent Lite+ Air Unit - fpvOS" ;; 482) PRODUCT="Ascent Lite Air Unit - fpvOS" ;; *) PRODUCT="Ascent Air Unit - fpvOS" ;; esac'
rename() { # script, sed program
	grep -q 'MANUFACTURER="Vendor"' "$1" && grep -q "$2" "$1" ||
		{ echo "$1: no stock USB name to replace" >&2; exit 1; }
	sed -i 's/MANUFACTURER="Vendor"/MANUFACTURER="Caddx"/' "$1"
}
f=$WORK/fpv/fpv/config_serial.sh
rename "$f" '^export PRODUCT="SerialGadget"$'
sed -i "s|^export PRODUCT=\"SerialGadget\"\$|set -- \"\$board_type\"; $name\ncase \$0 in /tmp/*) PRODUCT=\"\$PRODUCT [update]\" ;; esac\nexport PRODUCT|" "$f"

# fpvOS's updater (fpvos-update) takes the stock one's path: the stock rootfs
# starts whatever is there, in the normal and the clean system. Stock's stays
# beside it for a hand recovery.
if [ -f "$TARGET_DIR/usrdata/fpv/ar_fpvhs_upgrade" ]; then
	mv "$WORK/fpv/fpv/ar_fpvhs_upgrade" "$WORK/fpv/fpv/ar_fpvhs_upgrade.stock"
fi
cp -a "$TARGET_DIR/usrdata/." "$WORK/fpv/"
# The USB network: CDC-NCM in place of stock's RNDIS (config_ether.sh and
# disable_config_ether.sh), our address and a DHCP server in place of stock's
# usb_ip.sh. Stock's clean system copies all three to /tmp by these names.
for f in config_ether.sh disable_config_ether.sh usb_ip.sh; do
	[ -f "$WORK/fpv/fpv/$f" ] || { echo "app volume: no stock $f to replace" >&2; exit 1; }
	install -m 0755 "$BOARD/$f" "$WORK/fpv/fpv/$f"
done

# SSH keys from FPVOS_AIR_SSH_KEYS, a public-key file, at build time. They are
# personal: never committed, never in a release, and an image built with them
# is not for sharing (whoever holds the private half logs in to every unit
# flashed with it).
if [ -n "${FPVOS_AIR_SSH_KEYS:-}" ]; then
	install -d -m 0700 "$WORK/fpv/fpv/air/ssh"
	install -m 0600 "$FPVOS_AIR_SSH_KEYS" "$WORK/fpv/fpv/air/ssh/authorized_keys"
	{
		echo
		echo "**********************************************************************"
		echo "*** WARNING: this air image carries YOUR SSH public keys, from"
		echo "***   FPVOS_AIR_SSH_KEYS=$FPVOS_AIR_SSH_KEYS"
		echo "*** Whoever holds the matching private keys logs in as root to every"
		echo "*** unit flashed with it. Do NOT share or publish this image."
		echo "**********************************************************************"
		echo
	} >&2
else
	echo "air: no FPVOS_AIR_SSH_KEYS, so no SSH login with a key in this image" >&2
fi
# A root password, for SSH password login and the console: root unless
# FPVOS_AIR_ROOT_PASSWORD says otherwise at build time, none if it is set
# empty. The stock rootfs is not touched: at boot air/start.sh mounts a copy of
# /etc/shadow with this hash over it.
FPVOS_AIR_ROOT_PASSWORD=${FPVOS_AIR_ROOT_PASSWORD-root}
if [ -n "$FPVOS_AIR_ROOT_PASSWORD" ]; then
	install -d -m 0700 "$WORK/fpv/fpv/air/ssh"
	openssl passwd -6 "$FPVOS_AIR_ROOT_PASSWORD" > "$WORK/fpv/fpv/air/ssh/root.hash"
	chmod 0600 "$WORK/fpv/fpv/air/ssh/root.hash"
	echo "air: root password set (FPVOS_AIR_ROOT_PASSWORD, root by default) - SSH password login is on" >&2
else
	echo "air: FPVOS_AIR_ROOT_PASSWORD empty, so no password login in this image" >&2
fi
git -C "$ROOT" describe --always --dirty > "$WORK/fpv/fpv/air/VERSION"

# The PC tool matches the file name against the version in the header, so the
# image keeps the stock version and name.
ver=$("$MKIMG" info "$STOCK" | sed -n '1s/.* version \([0-9.]*\)$/\1/p')
name=Ascent_H_Sky_$(echo "$ver" | tr . _).img
"$MKIMG" pack --base "$STOCK" --fpv "$WORK/fpv" -o "$BINARIES_DIR/$name"
