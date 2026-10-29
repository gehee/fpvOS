#!/bin/bash
# fpvOS end-to-end build: Buildroot rootfs (with kestrel) -> SD image.
#
#   ./build.sh              # full build
#   ./build.sh config       # just run the defconfig into ./buildroot
#   ./build.sh kestrel      # rebuild only kestrel into the buildroot sysroot
#   ./build.sh image        # just assemble the SD image (rootfs already built)
#   ./build.sh air [config|kernel]   # the Ascent Lite and Lite+ air units, into ./output-air
#   ./build.sh ar9311 [config|kernel|all] # Ascent Gnd485 RAM boot, into ./output-ar9311
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

# The air unit builds into its own output directory, so it never touches the goggle's.
AIR_OUT="$ROOT/output-air"
AR9311_OUT="$ROOT/output-ar9311"

case "${1:-all}" in
  ar9311)
    # Kernel, board DTB and initramfs for RAM boot through the existing U-Boot.
    case "${2:-all}" in
      config) make -C "$BR" BR2_EXTERNAL="$EXT" O="$AR9311_OUT" ar9311_defconfig ;;
      kernel) make -C "$BR" BR2_EXTERNAL="$EXT" O="$AR9311_OUT" ar9311_defconfig
              make -C "$AR9311_OUT" linux-reconfigure ;;
      all)    make -C "$BR" BR2_EXTERNAL="$EXT" O="$AR9311_OUT" ar9311_defconfig
              make -C "$AR9311_OUT" ;;
      *) echo "usage: $0 ar9311 [config|kernel|all]" >&2; exit 1 ;;
    esac ;;
  air)
    case "${2:-all}" in
      config) make -C "$BR" BR2_EXTERNAL="$EXT" O="$AIR_OUT" ascentlite_defconfig ;;
      # reconfigure, so a change to the config fragment is picked up
      kernel) make -C "$BR" BR2_EXTERNAL="$EXT" O="$AIR_OUT" ascentlite_defconfig
              make -C "$AIR_OUT" linux-reconfigure ;;
      all)    make -C "$BR" BR2_EXTERNAL="$EXT" O="$AIR_OUT" ascentlite_defconfig
              make -C "$AIR_OUT" ;;
      *) echo "usage: $0 air [config|kernel|all]" >&2; exit 1 ;;
    esac ;;
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
  *) echo "usage: $0 {all|config|kestrel|image|air [config|kernel|all]|ar9311 [config|kernel|all]}" >&2; exit 1 ;;
esac
