#!/bin/sh
set -eu

board_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
repo_dir=$(CDPATH= cd -- "$board_dir/../../.." && pwd)
images=$1

# Independent 4 MiB LZ4 blocks match the vendor U-Boot decompressor.
"$HOST_DIR/bin/lz4" -f -q -9 -B7 -BI "$images/Image" "$images/Image.lz4"
"$HOST_DIR/bin/mkimage" -A arm64 -O linux -T kernel -C lz4 \
    -a 0x20200000 -e 0x20200000 -n 'fpvOS AR9311' \
    -d "$images/Image.lz4" "$images/kernel.uImage"
python3 "$repo_dir/boot/mkar9311img.py" \
    "$images/kernel.uImage" "$images/kernel.img"

# Development bundle uses vendor USB framing, without release/signature policy.
python3 "$repo_dir/tools/fpvos-update/package.py" \
    --board ascent-gnd485 "$images" "$images/fpvos-ar9311.fwu" --replace
