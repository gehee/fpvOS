#!/bin/sh
set -eu
boot="$BR2_EXTERNAL_FPVOS_PATH/../boot"
"$HOST_DIR/bin/aarch64-buildroot-linux-musl-gcc" -c "$boot/p1-bootguard.S" -o "$BINARIES_DIR/p1-bootguard.o"
"$HOST_DIR/bin/aarch64-buildroot-linux-musl-objcopy" -O binary -j .text "$BINARIES_DIR/p1-bootguard.o" "$BINARIES_DIR/p1-bootguard.bin"
python3 "$boot/p1-bootguard.py" "$BINARIES_DIR/Image" "$BINARIES_DIR/p1-bootguard.bin" "$BINARIES_DIR/Image.guarded"
"$HOST_DIR/bin/lz4" -9 -B7 -BI -f "$BINARIES_DIR/Image.guarded" "$BINARIES_DIR/Image.guarded.lz4"
"$HOST_DIR/bin/mkimage" -A arm64 -O linux -T kernel -C lz4 -a 0x20200000 -e 0x20200000 \
    -n 'fpvOS P1 recovery' -d "$BINARIES_DIR/Image.guarded.lz4" "$BINARIES_DIR/uImage"
python3 "$boot/mkar9311img.py" "$BINARIES_DIR/uImage" "$BINARIES_DIR/kernel.img"
[ "$(stat -c %s "$BINARIES_DIR/kernel.img")" -le 6291456 ]
python3 "$BR2_EXTERNAL_FPVOS_PATH/../tools/fpvos-update/package.py" --board p1-air \
    "$BINARIES_DIR" "$BINARIES_DIR/fpvos-p1-air.fwu" --replace
