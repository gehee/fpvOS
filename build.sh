#!/bin/bash
# fpvOS end-to-end build: Buildroot rootfs (with kestrel) -> SD image.
#
#   ./build.sh              # full build (the VRX Pro goggle; any of these VRX Pro
#                           # commands may also be spelled ./build.sh ascent-vrx-pro ...)
#   ./build.sh config       # configure the VRX Pro build in ./output/ascent-vrx-pro
#   ./build.sh kestrel      # rebuild only kestrel into the buildroot sysroot
#   ./build.sh image        # just assemble the SD image (rootfs already built)
#   ./build.sh air [config|kernel]   # the Ascent Lite and Lite+ air units, into ./output/ascent-lite
#   ./build.sh ascent-vrx [config|kernel|all] # Ascent VRX, into ./output/ascent-vrx
#
# Prerequisites:
#   - the Buildroot submodule is checked out (git clone --recurse-submodules,
#     or: git submodule update --init)
#   - vendor blobs extracted: scripts/extract-ascent-vrx-pro-firmware.py
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
        echo "  scripts/extract-ascent-vrx-pro-firmware.py        (downloads the stock firmware)" >&2
        exit 1; }
}

# Each board has an independent Buildroot configuration, toolchain and images.
ASCENT_VRX_PRO_OUT="$ROOT/output/ascent-vrx-pro"
AIR_OUT="$ROOT/output/ascent-lite"
ASCENT_VRX_OUT="$ROOT/output/ascent-vrx"

# The VRX Pro is the default board; ascent-vrx-pro names it like the others.
[ "${1:-}" = ascent-vrx-pro ] && shift

case "${1:-all}" in
  ascent-vrx)
    # Kernel, board DTB and initramfs for RAM boot through the existing U-Boot.
    case "${2:-all}" in
      config) make -C "$BR" BR2_EXTERNAL="$EXT" O="$ASCENT_VRX_OUT" ascentvrx_defconfig ;;
      kernel) make -C "$BR" BR2_EXTERNAL="$EXT" O="$ASCENT_VRX_OUT" ascentvrx_defconfig
              make -C "$ASCENT_VRX_OUT" linux-reconfigure ;;
      all)    make -C "$BR" BR2_EXTERNAL="$EXT" O="$ASCENT_VRX_OUT" ascentvrx_defconfig
              make -C "$ASCENT_VRX_OUT" ;;
      *) echo "usage: $0 ascent-vrx [config|kernel|all]" >&2; exit 1 ;;
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
    make -C "$BR" BR2_EXTERNAL="$EXT" O="$ASCENT_VRX_PRO_OUT" ascentvrxpro_defconfig ;;
  kestrel)
    make -C "$BR" BR2_EXTERNAL="$EXT" O="$ASCENT_VRX_PRO_OUT" kestrel-rebuild ;;
  image)
    need_vendor; "$ROOT/boot/mk-sd-image.sh" ;;
  all)
    need_vendor
    make -C "$BR" BR2_EXTERNAL="$EXT" O="$ASCENT_VRX_PRO_OUT" ascentvrxpro_defconfig
    make -C "$BR" BR2_EXTERNAL="$EXT" O="$ASCENT_VRX_PRO_OUT"
    "$ROOT/boot/mk-sd-image.sh" ;;
  *) echo "usage: $0 {[ascent-vrx-pro] {all|config|kestrel|image}|air [config|kernel|all]|ascent-vrx [config|kernel|all]}" >&2; exit 1 ;;
esac
