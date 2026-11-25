#!/bin/bash
# Assemble the VRX Pro SD image, rootless: no loop mounts, no sudo. Uses the
# populated rootfs.ext2 that Buildroot emits and mtools for the FAT partition,
# so this runs anywhere (including CI). Reproduces the layout of the known-good
# stock card.
#
# Two non-obvious things make this boot:
#   1. The loader at sector 0x4000 must be the PATCHED u-boot
#      (uboot-patched.bin). Its stubs let U-Boot finish PMIC/vdd_logic/dmc init
#      on an SD boot; the stock loader skips that and the decoder hangs.
#   2. A third partition "boot" holds the FIT (boot-sd3.img) - the
#      live boot path. U-Boot reads bootargs from the resource image inside it,
#      not from extlinux. p1 is only the fallback.
#
# The boot chain comes from Buildroot's images directory, where the
# fpvos-bootchain package writes it (boot/mkbootchain.py, from the stock boot
# images in vendor/stock/). Nothing here is redistributable on its own.
#
# Writes the raw image ($OUT, for dd) and, next to it, $OUT.xz - the one to
# flash with balenaEtcher or Raspberry Pi Imager, which both take .img.xz as
# is. COMPRESS=0 skips the .xz (release.sh does, and compresses only after it
# has checked the image).
set -e

ROOT=$(cd "$(dirname "$0")/.." && pwd)
BR="${BR_IMAGES:-$ROOT/output/ascent-vrx-pro/images}"
V="$BR"   # boot chain: fpvos-bootchain installs it next to rootfs.ext2
OUT="${OUT:-$BR/sdcard.img}"
COMPRESS="${COMPRESS:-1}"

IMG_MB=1100
LOADER_SECTOR=16384; LOADER_SIZE=8192  # the patched loader, at 0x4000, 4M
P1_START=32768;   P1_SIZE=131072     # bootfat, 64M
P2_START=163840;  P2_SIZE=1267712    # rootfs,  619M
P3_START=2000896; P3_SIZE=131072     # boot,    64M  (the FIT)
# p1 is FAT32: what its tables and directories take, at most, besides the files.
P1_OVERHEAD=$((4 * 1024 * 1024))

for f in "$V/uboot-patched.bin" "$V/boot-sd3.img" "$V/boot-sd3.img.kernel-sha256" "$V/Image" \
         "$V/rk3568-pro-patched.dtb" "$BR/rootfs.ext2"; do
    [ -f "$f" ] || { echo "MISSING: $f" >&2
        echo "  run ./build.sh - it builds the boot chain and rootfs.ext2 (after" >&2
        echo "  scripts/extract-ascent-vrx-pro-firmware.py has filled vendor/)" >&2; exit 1; }
done

# The FIT's kernel must be the kernel the rootfs's modules were built for:
# Buildroot rebuilds the kernel (a changed config fragment) without rebuilding
# fpvos-bootchain, which leaves the card booting the old one - with the new
# modules and none of its drivers (a VRX Pro with no USB network, 2026-11-24).
fit_kernel=$(cat "$V/boot-sd3.img.kernel-sha256")
image_kernel=$(sha256sum "$V/Image" | cut -d' ' -f1)
[ "$fit_kernel" = "$image_kernel" ] || {
    echo "mk-sd-image.sh: boot-sd3.img boots another kernel than images/Image (the build's):" >&2
    echo "  rebuild the boot chain first: make -C output/ascent-vrx-pro fpvos-bootchain-rebuild" >&2
    echo "  (./build.sh and ./build.sh image do this)" >&2
    exit 1; }

# Everything below is a plain write at an offset, which would run over the
# next region without a word: check each piece fits where it goes first.
size() { wc -c < "$1" | tr -d ' '; }
fits() {   # what, its bytes, the room in bytes, where
    [ "$2" -le "$3" ] || { echo "TOO BIG: $1 is $2 bytes; $4 holds $3" >&2; exit 1; }
}
# The layout itself: in order, apart, and inside the image with room for the
# backup GPT (33 sectors) at its end.
[ $((LOADER_SECTOR + LOADER_SIZE)) -le $P1_START ] &&
[ $((P1_START + P1_SIZE)) -le $P2_START ] &&
[ $((P2_START + P2_SIZE)) -le $P3_START ] &&
[ $((P3_START + P3_SIZE + 33)) -le $((IMG_MB * 2048)) ] ||
    { echo "mk-sd-image.sh: the partition layout overlaps itself" >&2; exit 1; }
fits uboot-patched.bin "$(size "$V/uboot-patched.bin")" $((LOADER_SIZE * 512)) "the loader area"
fits rootfs.ext2 "$(size "$BR/rootfs.ext2")" $((P2_SIZE * 512)) "p2 (rootfs)"
fits boot-sd3.img "$(size "$V/boot-sd3.img")" $((P3_SIZE * 512)) "p3 (boot)"
fits "Image + rk3568-pro.dtb" $(( $(size "$V/Image") + $(size "$V/rk3568-pro-patched.dtb") )) \
     $((P1_SIZE * 512 - P1_OVERHEAD)) "p1 (bootfat), after FAT32's own tables,"

for t in sfdisk mformat mcopy mmd dd truncate $([ "$COMPRESS" = 1 ] && echo xz); do
    command -v "$t" >/dev/null || { echo "need '$t' (Debian/Ubuntu: apt install mtools fdisk xz-utils)" >&2; exit 1; }
done

# On any failure: no temporary files left behind, and no half-written image
# where a finished one is expected.
P1=; EXT=; finished=
trap 'rm -f ${P1:+"$P1"} ${EXT:+"$EXT"}; [ -n "$finished" ] || rm -f "$OUT"' EXIT
trap 'exit 1' HUP INT TERM

rm -f "$OUT"; truncate -s ${IMG_MB}M "$OUT"
sfdisk "$OUT" >/dev/null <<EOF
label: gpt
unit: sectors
start=${P1_START}, size=${P1_SIZE}, type=0FC63DAF-8483-4772-8E79-3D69D8477DE4, name="bootfat"
start=${P2_START}, size=${P2_SIZE}, type=0FC63DAF-8483-4772-8E79-3D69D8477DE4, name="rootfs"
start=${P3_START}, size=${P3_SIZE}, type=0FC63DAF-8483-4772-8E79-3D69D8477DE4, name="boot"
EOF

# Patched loader at sector 0x4000, and the FIT into p3 - plain byte writes.
dd if="$V/uboot-patched.bin" of="$OUT" bs=512 seek=${LOADER_SECTOR} count=${LOADER_SIZE} conv=notrunc status=none
dd if="$V/boot-sd3.img"      of="$OUT" bs=512 seek=${P3_START}            conv=notrunc status=none

# p1: a FAT32 fallback boot partition, built with mtools then blitted in.
P1=$(mktemp); EXT=$(mktemp)
truncate -s $((P1_SIZE*512)) "$P1"
mformat -i "$P1" -F ::
mmd   -i "$P1" ::/extlinux
mcopy -i "$P1" "$V/Image" ::/Image
mcopy -i "$P1" "$V/rk3568-pro-patched.dtb" ::/rk3568-pro.dtb
cat > "$EXT" <<CONF
timeout 10
default fpvos
label fpvos
    menu label fpvOS VRX Pro
    kernel /Image
    fdt /rk3568-pro.dtb
    append earlycon=uart8250,mmio32,0xfe660000 console=ttyFIQ0 root=/dev/mmcblk1p2 rootfstype=ext4 rootwait rw
CONF
mcopy -i "$P1" "$EXT" ::/extlinux/extlinux.conf
dd if="$P1" of="$OUT" bs=512 seek=${P1_START} conv=notrunc status=none

# p2: the populated ext4 image straight into the partition region.
dd if="$BR/rootfs.ext2" of="$OUT" bs=512 seek=${P2_START} conv=notrunc status=none

rm -f "$P1" "$EXT"
finished=1
echo "=== SD image: $OUT ($(du -h "$OUT" | cut -f1)) ==="

if [ "$COMPRESS" = 1 ]; then
    # Keep the raw image (-k) for dd and for iterating; the .xz is what gets
    # flashed with a GUI tool or handed to someone else.
    xz -T0 -k -f "$OUT"
    # Its release name carries the fpvOS version, when the build left one
    # (fpvos-vrxpro-<version>.img.xz; $OUT.xz stays, as a link to it).
    flash=$OUT.xz
    VERSION_FILE=${VERSION_FILE:-$BR/../target/etc/fpvos-version}
    if [ -f "$VERSION_FILE" ]; then
        flash=$("$ROOT/boot/versioned-name.sh" "$OUT.xz" "$(cat "$VERSION_FILE")" fpvos-vrxpro)
    fi
    echo "=== compressed: $flash ($(du -hL "$flash" | cut -f1)) ==="
    echo "flash:  balenaEtcher -> Flash from file -> $(basename "$flash")"
fi
echo "   or:  sudo dd if=$OUT of=/dev/sdX bs=4M conv=fsync"
