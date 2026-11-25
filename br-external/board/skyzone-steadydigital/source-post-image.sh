#!/bin/sh
# Flashable SteadyDigital image: the installed kernel.img (for whichever NAND
# bank the updater picks) and a packaged .fwu (kernel.img + board DTB + main
# root). This kernel runs the goggle, so it has the full driver set (display,
# decoder, HDMI). Its initramfs is the fpvOS recovery (set by external.mk when
# fpvos-recovery is enabled); the main root is rootfs.squashfs, written to that
# bank's userapp by the updater and mounted from there by the recovery. The
# slim kernel the flasher uploads over the HID loader is a separate build:
# recovery-kernel.sh.
set -eu

board_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
repo_dir=$(CDPATH= cd -- "$board_dir/../../.." && pwd)
images=$1

# The installed kernel must be the full one: a kernel tree left configured with
# the slim recovery fragment (Buildroot does not reconfigure a configured kernel
# when the fragment list changes - run `./build.sh skyzone-steadydigital-flash
# kernel`) would install a goggle with no display or decoder.
kconfig="$BUILD_DIR/linux-custom/.config"
for sym in CONFIG_DRM CONFIG_DRM_ARTOSYN CONFIG_DRM_LONTIUM_LT9611; do
    grep -qx "$sym=y" "$kconfig" || {
        echo "installed kernel lacks $sym=y ($kconfig): refusing to package the .fwu;" \
             "reconfigure with ./build.sh skyzone-steadydigital-flash kernel" >&2
        exit 1; }
done
# ...and its out-of-tree modules must be built against it: one built before the
# kernel was last rebuilt (another config) is rejected at load - artosyn_gpio
# missing leaves the LT9611 without its reset GPIO, so no display at all.
stale=$(find "$TARGET_DIR/lib/modules" -name '*.ko' ! -newer "$BUILD_DIR/linux-custom/vmlinux" 2>/dev/null)
[ -z "$stale" ] || {
    echo "kernel modules older than the kernel, refusing to package the .fwu:" $stale >&2
    echo "rebuild them with ./build.sh skyzone-steadydigital-flash kernel" >&2
    exit 1; }

# Independent 4 MiB LZ4 blocks match the vendor U-Boot decompressor.
"$HOST_DIR/bin/lz4" -f -q -9 -B7 -BI "$images/Image" "$images/Image.lz4"
"$HOST_DIR/bin/mkimage" -A arm64 -O linux -T kernel -C lz4 \
    -a 0x20200000 -e 0x20200000 -n 'fpvOS SteadyDigital recovery' \
    -d "$images/Image.lz4" "$images/kernel.uImage"
python3 "$repo_dir/boot/mkar9311img.py" "$images/kernel.uImage" "$images/kernel.img"
# kernel.img must fit the GPT kernel1 partition (0x600000).
[ "$(stat -c %s "$images/kernel.img")" -le 6291456 ]

# Its label and its file name carry the fpvOS version (scripts/fpvos-version).
version=$(cat "$TARGET_DIR/etc/fpvos-version")
python3 "$repo_dir/tools/fpvos-update/package.py" --board skyzone-steadydigital --release "$version" \
    "$images" "$images/fpvos-steadydigital.fwu" --replace
"$repo_dir/boot/versioned-name.sh" "$images/fpvos-steadydigital.fwu" "$version"
