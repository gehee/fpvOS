#!/bin/sh
# Assemble the Caddx PC-tool image for the Ascent Lite and Lite+ (Ascent_H_Sky_*.img):
# the stock image from vendor/stock/air/ with a new app volume (/usrdata), made
# of the stock one, plus everything the build put under $TARGET_DIR/usrdata,
# plus fpv_run-hook.sh in the stock board script. U-Boot, env, kernel and
# rootfs stay byte-identical to stock. mkascentimg.py refuses a volume that
# would lose the PC tool's updater.
set -eu

BOARD=$(cd "$(dirname "$0")" && pwd)
ROOT=$(cd "$BOARD/../../.." && pwd)
MKIMG=$ROOT/boot/mkascentimg.py
STOCK=$(ls "$ROOT"/vendor/stock/air/Ascent_H_Sky_*.img 2>/dev/null | tail -n 1)
[ -n "$STOCK" ] || { echo "no stock air image: run scripts/extract-ascent-vrx-pro-firmware.py" >&2; exit 1; }

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
# "Vendor Ethernet": "Caddx Ascent Lite+" (or Lite) in normal mode, with
# "(update)" in the clean system (which runs a copy from /tmp) and "(network)"
# for RNDIS. The IDs and serial number stay stock's: the PC tool and the
# flasher go by them, never by the name. fpvOS_usb names bridge mode the same
# way (PRODUCT in its board settings).
name='case $1 in 472) PRODUCT="Caddx Ascent Lite+" ;; 482) PRODUCT="Caddx Ascent Lite" ;; *) PRODUCT="Caddx Ascent" ;; esac'
rename() { # script, sed program
	grep -q 'MANUFACTURER="Vendor"' "$1" && grep -q "$2" "$1" ||
		{ echo "$1: no stock USB name to replace" >&2; exit 1; }
	sed -i 's/MANUFACTURER="Vendor"/MANUFACTURER="Caddx"/' "$1"
}
f=$WORK/fpv/fpv/config_serial.sh
rename "$f" '^export PRODUCT="SerialGadget"$'
sed -i "s|^export PRODUCT=\"SerialGadget\"\$|set -- \"\$board_type\"; $name\ncase \$0 in /tmp/*) PRODUCT=\"\$PRODUCT (update)\" ;; esac\nexport PRODUCT|" "$f"
f=$WORK/fpv/fpv/config_ether.sh
rename "$f" '^PRODUCT="Ethernet"$'
sed -i "s|^PRODUCT=\"Ethernet\"\$|set -- \"\$(cat /usrdata/fpv/fpv_board_type /tmp/fpv_board_type 2>/dev/null \| head -n 1)\" \"\$@\"; $name\nshift\nPRODUCT=\"\$PRODUCT (network)\"|" "$f"

# fpvOS's updater (fpvos-update) takes the stock one's path: the stock rootfs
# starts whatever is there, in the normal and the clean system. Stock's stays
# beside it for a hand recovery.
if [ -f "$TARGET_DIR/usrdata/fpv/ar_fpvhs_upgrade" ]; then
	mv "$WORK/fpv/fpv/ar_fpvhs_upgrade" "$WORK/fpv/fpv/ar_fpvhs_upgrade.stock"
fi
cp -a "$TARGET_DIR/usrdata/." "$WORK/fpv/"
# The USB network: our address and a DHCP server, in place of stock's usb_ip.sh.
install -m 0755 "$BOARD/usb_ip.sh" "$WORK/fpv/fpv/usb_ip.sh"

# SSH keys from FPVOS_AIR_SSH_KEYS, a public-key file, at build time. They are
# personal: never committed, and an image built with them is not for sharing.
if [ -n "${FPVOS_AIR_SSH_KEYS:-}" ]; then
	install -d -m 0700 "$WORK/fpv/fpv/air/ssh"
	install -m 0600 "$FPVOS_AIR_SSH_KEYS" "$WORK/fpv/fpv/air/ssh/authorized_keys"
	echo "*** air: SSH keys from $FPVOS_AIR_SSH_KEYS - this image carries your public keys; do not share it" >&2
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
