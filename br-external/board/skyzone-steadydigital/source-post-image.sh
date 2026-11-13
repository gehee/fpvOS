#!/bin/sh
# Flashable SteadyDigital image: a recovery kernel.img for NAND bank B and a
# packaged .fwu (kernel.img + board DTB + main root). The kernel's initramfs is
# the fpvOS recovery (set by external.mk when fpvos-recovery is enabled); the
# main root is rootfs.squashfs, written to userapp1 by the updater and mounted
# from there by the recovery.
set -eu

board_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
repo_dir=$(CDPATH= cd -- "$board_dir/../../.." && pwd)
images=$1

# Independent 4 MiB LZ4 blocks match the vendor U-Boot decompressor.
"$HOST_DIR/bin/lz4" -f -q -9 -B7 -BI "$images/Image" "$images/Image.lz4"
"$HOST_DIR/bin/mkimage" -A arm64 -O linux -T kernel -C lz4 \
    -a 0x20200000 -e 0x20200000 -n 'fpvOS SteadyDigital recovery' \
    -d "$images/Image.lz4" "$images/kernel.uImage"
python3 "$repo_dir/boot/mkar9311img.py" "$images/kernel.uImage" "$images/kernel.img"
# kernel.img must fit the GPT kernel1 partition (0x600000).
[ "$(stat -c %s "$images/kernel.img")" -le 6291456 ]

python3 "$repo_dir/tools/fpvos-update/package.py" --board skyzone-steadydigital \
    "$images" "$images/fpvos-steadydigital.fwu" --replace
