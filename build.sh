#!/bin/bash
# fpvOS end-to-end build: Buildroot rootfs (with kestrel) -> SD image.
#
#   ./build.sh              # full build
#   ./build.sh config       # just run the defconfig into ./buildroot
#   ./build.sh kestrel      # rebuild only kestrel into the buildroot sysroot
#   ./build.sh image        # just assemble the SD image (rootfs already built)
#
# Prerequisites:
#   - the Buildroot submodule is checked out (git clone --recurse-submodules,
#     or: git submodule update --init)
#   - vendor blobs extracted: scripts/extract-vendor.py
set -e

ROOT=$(cd "$(dirname "$0")" && pwd)
BR="$ROOT/buildroot"
EXT="$ROOT/br-external"

# The Buildroot submodule is pinned to the version in br-external/BUILDROOT_VERSION.
if [ ! -f "$BR/Makefile" ]; then
    echo "Buildroot submodule not checked out - fetching it now..." >&2
    git -C "$ROOT" submodule update --init --depth 1 buildroot
fi

need_vendor() {
    [ -f "$ROOT/vendor/rootfs/ar8030soc/daemon" ] &&
    [ -f "$ROOT/vendor/stock/uboot.img" ] && [ -f "$ROOT/vendor/stock/boot.img" ] || {
        echo "vendor blobs missing - run:" >&2
        echo "  scripts/extract-vendor.py        (downloads the stock firmware)" >&2
        exit 1; }
}

case "${1:-all}" in
  config)
    make -C "$BR" BR2_EXTERNAL="$EXT" vrxpro_defconfig ;;
  kestrel)
    make -C "$BR" BR2_EXTERNAL="$EXT" kestrel-rebuild ;;
  image)
    need_vendor; "$ROOT/boot/mk-sd-image.sh" ;;
  all)
    need_vendor
    make -C "$BR" BR2_EXTERNAL="$EXT" vrxpro_defconfig
    make -C "$BR" BR2_EXTERNAL="$EXT"
    "$ROOT/boot/mk-sd-image.sh" ;;
  *) echo "usage: $0 {all|config|kestrel|image}" >&2; exit 1 ;;
esac
