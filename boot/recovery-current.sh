#!/bin/sh
# The kernel's recovery root against the image it was built with: the same
# fpvOS version, updater and update helper, and a kernel linked after them.
# The recovery root installs and boots every bundle, so an image whose kernel
# carries an older one is refused here instead of shipped.
#   recovery-current.sh   (a Buildroot post-image step: BUILD_DIR, TARGET_DIR, HOST_DIR)
set -eu
root=$BUILD_DIR/fpvos-recovery-1/root
packed=$(ls "$BUILD_DIR"/linux-*/usr/initramfs_data.cpio 2>/dev/null | head -1)
stale() {
    echo "recovery-current: the kernel's recovery root $1;" >&2
    echo "  build it and the kernel again: make fpvos-recovery-rebuild all" >&2
    exit 1
}
cmp -s "$root/etc/fpvos-version" "$TARGET_DIR/etc/fpvos-version" ||
    stale "says $(cat "$root/etc/fpvos-version"), the image $(cat "$TARGET_DIR/etc/fpvos-version")"
cmp -s "$root/usr/libexec/fpvos-update-backend" "$TARGET_DIR/usr/libexec/fpvos-update-backend" ||
    stale "has another update helper than the image"
# The two updaters are stripped differently: their code and data are compared.
objcopy=$(ls "$HOST_DIR"/bin/*-objcopy | head -1)
a=$BUILD_DIR/.recovery-current.root b=$BUILD_DIR/.recovery-current.target
"$objcopy" -O binary -j .text -j .rodata -j .data "$root/usr/sbin/fpvos-update" "$a"
"$objcopy" -O binary -j .text -j .rodata -j .data "$TARGET_DIR/usr/sbin/fpvos-update" "$b"
same=0
cmp -s "$a" "$b" || same=1
rm -f "$a" "$b"
[ "$same" = 0 ] || stale "has another updater than the image"
# Kbuild packs the root into usr/initramfs_data.cpio when it links the kernel.
[ -n "$packed" ] || stale "is in no kernel build under $BUILD_DIR"
[ ! "$root/usr/sbin/fpvos-update" -nt "$packed" ] && [ ! "$root/etc/fpvos-version" -nt "$packed" ] ||
    stale "was built after the kernel that should carry it"
