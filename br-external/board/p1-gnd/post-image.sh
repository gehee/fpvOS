#!/bin/sh
# The P1 ground image: one guarded kernel and one root filesystem for every
# unit, and a bundle per unit, each carrying that unit's device tree as
# p1-gnd.dtb (the updater writes it to the bank's dtb partition):
#   fpvos-p1-gnd-goggles-<version>.fwu   BETAFPV P1 goggles (panel)
#   fpvos-p1-gnd-vrx-<version>.fwu       BETAFPV P1 VRX and Nano VRX (HDMI):
#                                        stock's one P1_GND_VRX product, one board
#   fpvos-p1-gnd-goggles-pro-<version>.fwu   BETAFPV VR04 HD Pro goggles (a
#                                        panel behind a GM8773C bridge)
set -eu
boot="$BR2_EXTERNAL_FPVOS_PATH/../boot"
"$boot/recovery-current.sh"
"$HOST_DIR/bin/aarch64-buildroot-linux-musl-gcc" -c "$boot/p1-bootguard.S" -o "$BINARIES_DIR/p1-bootguard.o"
"$HOST_DIR/bin/aarch64-buildroot-linux-musl-objcopy" -O binary -j .text "$BINARIES_DIR/p1-bootguard.o" "$BINARIES_DIR/p1-bootguard.bin"
python3 "$boot/p1-bootguard.py" "$BINARIES_DIR/Image" "$BINARIES_DIR/p1-bootguard.bin" "$BINARIES_DIR/Image.guarded"
"$HOST_DIR/bin/lz4" -9 -B7 -BI -f "$BINARIES_DIR/Image.guarded" "$BINARIES_DIR/Image.guarded.lz4"
"$HOST_DIR/bin/mkimage" -A arm64 -O linux -T kernel -C lz4 -a 0x20200000 -e 0x20200000 \
    -n 'fpvOS P1 ground recovery' -d "$BINARIES_DIR/Image.guarded.lz4" "$BINARIES_DIR/uImage"
python3 "$boot/mkar9311img.py" "$BINARIES_DIR/uImage" "$BINARIES_DIR/kernel.img"
[ "$(stat -c %s "$BINARIES_DIR/kernel.img")" -le 6291456 ]
# Its label and its file names carry the fpvOS version (scripts/fpvos-version).
version=$(cat "$TARGET_DIR/etc/fpvos-version")
for unit in goggles:betafpv-p1-goggle vrx:betafpv-p1-nano-vrx goggles-pro:betafpv-p1-goggle-pro; do
    name=${unit%%:*} dtb=${unit#*:}.dtb
    [ -s "$BINARIES_DIR/$dtb" ] || { echo "p1-gnd: no $dtb in $BINARIES_DIR" >&2; exit 1; }
    work="$BINARIES_DIR/p1-gnd-$name"
    rm -rf "$work"
    mkdir -p "$work"
    cp "$BINARIES_DIR/kernel.img" "$BINARIES_DIR/rootfs.cpio.gz" "$work/"
    cp "$BINARIES_DIR/$dtb" "$work/p1-gnd.dtb"
    python3 "$BR2_EXTERNAL_FPVOS_PATH/../tools/fpvos-update/package.py" --board p1-gnd --release "$version" \
        "$work" "$BINARIES_DIR/fpvos-p1-gnd-$name.fwu" --replace
    "$boot/versioned-name.sh" "$BINARIES_DIR/fpvos-p1-gnd-$name.fwu" "$version"
done
