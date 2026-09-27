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
set -e

ROOT=$(cd "$(dirname "$0")/.." && pwd)
BR="${BR_IMAGES:-$ROOT/buildroot/output/images}"
V="$BR"   # boot chain: fpvos-bootchain installs it next to rootfs.ext2
OUT="${OUT:-$ROOT/sdcard.img}"

IMG_MB=1100
P1_START=32768;   P1_SIZE=131072     # bootfat, 64M
P2_START=163840;  P2_SIZE=1267712    # rootfs,  619M
P3_START=2000896; P3_SIZE=131072     # boot,    64M  (the FIT)

for f in "$V/uboot-patched.bin" "$V/boot-sd3.img" "$V/Image" \
         "$V/rk3568-pro-patched.dtb" "$BR/rootfs.ext2"; do
    [ -f "$f" ] || { echo "MISSING: $f" >&2
        echo "  run ./build.sh - it builds the boot chain and rootfs.ext2 (after" >&2
        echo "  scripts/extract-vendor.py has filled vendor/)" >&2; exit 1; }
done
for t in sfdisk mformat mcopy mmd dd truncate; do
    command -v "$t" >/dev/null || { echo "need '$t' (Debian/Ubuntu: apt install mtools fdisk)" >&2; exit 1; }
done

rm -f "$OUT"; truncate -s ${IMG_MB}M "$OUT"
sfdisk "$OUT" >/dev/null <<EOF
label: gpt
unit: sectors
start=${P1_START}, size=${P1_SIZE}, type=0FC63DAF-8483-4772-8E79-3D69D8477DE4, name="bootfat"
start=${P2_START}, size=${P2_SIZE}, type=0FC63DAF-8483-4772-8E79-3D69D8477DE4, name="rootfs"
start=${P3_START}, size=${P3_SIZE}, type=0FC63DAF-8483-4772-8E79-3D69D8477DE4, name="boot"
EOF

# Patched loader at sector 0x4000, and the FIT into p3 - plain byte writes.
dd if="$V/uboot-patched.bin" of="$OUT" bs=512 seek=16384       count=8192 conv=notrunc status=none
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
echo "=== SD image: $OUT ($(du -h "$OUT" | cut -f1)) ==="
echo "flash:  sudo dd if=$OUT of=/dev/sdX bs=4M conv=fsync && sudo sgdisk -e /dev/sdX"
