#!/bin/sh
# The slim upload recovery kernel: images/kernel-recovery.img, the kernel a
# stock P1 Air boots from RAM through the Artosyn HID loader (the one-time
# stock->fpvOS step). Built from a copy of the source build's kernel tree with
# linux-recovery.fragment merged in, so the installed kernel (kernel.img, in
# fpvos-p1-air.fwu) keeps the camera and encoder and is never touched. Same
# embedded fpvOS recovery initramfs and P1 boot guard as the installed kernel.
#   ./build.sh p1-air-source recovery   (after ./build.sh p1-air-source)
set -eu

board_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
repo_dir=$(CDPATH= cd -- "$board_dir/../../.." && pwd)
boot="$repo_dir/boot"
out=$1
src="$out/build/linux-custom"
rec="$out/build/linux-recovery"
images="$out/images"
host="$out/host"

[ -f "$src/.config" ] && [ -f "$images/kernel.img" ] && [ -f "$images/p1-bootguard.bin" ] || {
    echo "build the source image first: ./build.sh p1-air-source" >&2
    exit 1; }

gcc=$(ls "$host/bin/"*-linux-*-gcc | head -1)
cross=${gcc%gcc}
export PATH="$host/bin:$PATH"

# Mirror the full tree (objects too, so only what the fragment changes rebuilds).
rsync -a --delete "$src/" "$rec/"
cd "$rec"
./scripts/kconfig/merge_config.sh -m -O . .config "$board_dir/linux-recovery.fragment" >/dev/null
make ARCH=arm64 CROSS_COMPILE="$cross" olddefconfig >/dev/null
# Every fragment line must have taken, or this is not the kernel it claims. A
# disabled symbol may drop out of .config entirely (its dependency is off too),
# so for those check only that it is not enabled.
grep -E '^(# )?CONFIG_' "$board_dir/linux-recovery.fragment" | while read -r line; do
    case $line in
        "# CONFIG_"*) sym=${line#\# }; sym=${sym%% *}
                      ! grep -qE "^$sym=[ym]" .config ;;
        *)            grep -qxF "$line" .config ;;
    esac || { echo "recovery fragment not applied: $line" >&2; exit 1; }
done
make ARCH=arm64 CROSS_COMPILE="$cross" -j"$(nproc)" Image

# Guarded and wrapped exactly as source-post-image.sh does the installed kernel.
python3 "$boot/p1-bootguard.py" arch/arm64/boot/Image "$images/p1-bootguard.bin" "$images/Image-recovery.guarded"
lz4 -f -q -9 -B7 -BI "$images/Image-recovery.guarded" "$images/Image-recovery.guarded.lz4"
mkimage -A arm64 -O linux -T kernel -C lz4 -a 0x20200000 -e 0x20200000 \
    -n 'fpvOS P1 recovery' \
    -d "$images/Image-recovery.guarded.lz4" "$images/kernel-recovery.uImage" >/dev/null
python3 "$boot/mkar9311img.py" "$images/kernel-recovery.uImage" "$images/kernel-recovery.img"
[ "$(stat -c %s "$images/kernel-recovery.img")" -le 6291456 ]
echo "kernel-recovery.img: $(stat -c %s "$images/kernel-recovery.img") bytes, sha256 $(sha256sum "$images/kernel-recovery.img" | cut -d' ' -f1)"
