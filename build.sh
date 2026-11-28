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
#   ./build.sh p1-goggle [config|kernel|all] # P1 goggles RAM bring-up
#   ./build.sh p1-gnd [config|kernel|all|recovery]  # BETAFPV P1 goggles, goggles Pro + VRX, one image (.fwu each, experimental); recovery = slim HID-upload kernel
#   ./build.sh skyzone-steadydigital [config|kernel|all] # Skyzone SteadyDigital (RAM)
#   ./build.sh skyzone-steadydigital-flash [config|kernel|all|recovery] # Skyzone SteadyDigital flashable NAND image (.fwu); recovery = slim HID-upload kernel
#   ./build.sh p1-air [config|all] # P1 stock-runtime development bundle
#
#   ./build.sh p1-air-source [config|all|recovery] # experimental source kernel, RAM rootfs; recovery = slim HID-upload kernel
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

# The SteadyDigital defconfigs name no radio config of their own, so Open8030's
# gnd-config.py makes it from the stock VRX Pro one - only that file, not the
# VRX Pro boot images need_vendor wants. Say so now, not deep into the build.
# OPEN8030_PRIVATE_DIR/OPEN8030_CONFIG_DIR (a config of your own) skip it.
need_stock_gnd_config() {
    [ -z "${OPEN8030_PRIVATE_DIR:-}${OPEN8030_CONFIG_DIR:-}" ] || return 0
    local config=${OPEN8030_STOCK_GND_CONFIG:-$ROOT/vendor/rootfs/lib/firmware/bb_config_gnd_pro.json}
    [ -f "$config" ] || {
        echo "missing $config" >&2
        echo "(the stock VRX Pro radio config this board's Open8030 config is made from) - run:" >&2
        echo "  scripts/extract-ascent-vrx-pro-firmware.py        (downloads the stock firmware)" >&2
        exit 1; }
}

# The AR9311 receivers' kestrel-gnd runtime (kestrel-native): the pinned one
# (br-external/package/kestrel-native/runtime.hash) in output/kestrel-runtime/,
# built with scripts/native-runtime.sh when it is not there yet - which needs
# Docker. A KESTREL_NATIVE_IMAGE of your own is used as it is.
need_native_runtime() {
    [ -z "${KESTREL_NATIVE_IMAGE:-}" ] || return 0
    local board=$1 image=$ROOT/output/kestrel-runtime/runtime-$1.squashfs pin
    pin=$(awk -v b="$board" '$1 == b { print $2 }' "$EXT/package/kestrel-native/runtime.hash")
    [ -f "$image" ] && [ "$(sha256sum "$image" | cut -d' ' -f1)" = "$pin" ] && return 0
    command -v docker > /dev/null || {
        echo "$image is not the pinned $board runtime ($pin), and building it needs Docker:" >&2
        echo "  scripts/native-runtime.sh $board        (on a host with Docker, in this tree)" >&2
        exit 1; }
    "$ROOT/scripts/native-runtime.sh" "$board"
}

# Each board has an independent Buildroot configuration, toolchain and images.
ASCENT_VRX_PRO_OUT="$ROOT/output/ascent-vrx-pro"
AIR_OUT="$ROOT/output/ascent-lite"
ASCENT_VRX_OUT="$ROOT/output/ascent-vrx"
P1_GOGGLE_OUT="$ROOT/output/p1-goggle"
P1_GND_OUT="$ROOT/output/p1-gnd"
STEADYDIGITAL_OUT="$ROOT/output/skyzone-steadydigital"
STEADYDIGITAL_FLASH_OUT="$ROOT/output/skyzone-steadydigital-flash"
P1_AIR_OUT="$ROOT/output/p1-air"
P1_AIR_SOURCE_OUT="$ROOT/output/p1-air-source"

# The VRX Pro is the default board; ascent-vrx-pro names it like the others.
[ "${1:-}" = ascent-vrx-pro ] && shift

case "${1:-all}" in
  p1-goggle)
    case "${2:-all}" in
      config) make -C "$BR" BR2_EXTERNAL="$EXT" O="$P1_GOGGLE_OUT" p1goggle_defconfig ;;
      kernel) make -C "$BR" BR2_EXTERNAL="$EXT" O="$P1_GOGGLE_OUT" p1goggle_defconfig
              make -C "$P1_GOGGLE_OUT" linux-reconfigure ;;
      all)    need_native_runtime p1goggle
              make -C "$BR" BR2_EXTERNAL="$EXT" O="$P1_GOGGLE_OUT" p1goggle_defconfig
              make -C "$P1_GOGGLE_OUT" ;;
      *) echo "usage: $0 p1-goggle [config|kernel|all]" >&2; exit 1 ;;
    esac ;;
  p1-gnd)
    case "${2:-all}" in
      config) make -C "$BR" BR2_EXTERNAL="$EXT" O="$P1_GND_OUT" p1gnd_defconfig ;;
      kernel) make -C "$BR" BR2_EXTERNAL="$EXT" O="$P1_GND_OUT" p1gnd_defconfig
              make -C "$P1_GND_OUT" linux-reconfigure ;;
      all)    need_native_runtime p1goggle
              make -C "$BR" BR2_EXTERNAL="$EXT" O="$P1_GND_OUT" p1gnd_defconfig
              make -C "$P1_GND_OUT" ;;
      # The slim upload recovery kernel the HID loader boots
      # (images/kernel-recovery.img), from a copy of the build's kernel.
      recovery) "$EXT/board/p1-gnd/recovery-kernel.sh" "$P1_GND_OUT" ;;
      *) echo "usage: $0 p1-gnd [config|kernel|all|recovery]" >&2; exit 1 ;;
    esac ;;
  p1-air-source)
    case "${2:-all}" in
      config) make -C "$BR" BR2_EXTERNAL="$EXT" O="$P1_AIR_SOURCE_OUT" p1air_source_defconfig ;;
      all)    make -C "$BR" BR2_EXTERNAL="$EXT" O="$P1_AIR_SOURCE_OUT" p1air_source_defconfig
              make -C "$P1_AIR_SOURCE_OUT" ;;
      # The slim upload recovery kernel the HID loader boots
      # (images/kernel-recovery.img), from a copy of the source build's kernel.
      recovery) "$EXT/board/p1-air/recovery-kernel.sh" "$P1_AIR_SOURCE_OUT" ;;
      *) echo "usage: $0 p1-air-source [config|all|recovery]" >&2; exit 1 ;;
    esac ;;
  p1-air)
    case "${2:-all}" in
      config) make -C "$BR" BR2_EXTERNAL="$EXT" O="$P1_AIR_OUT" p1air_defconfig ;;
      all)    make -C "$BR" BR2_EXTERNAL="$EXT" O="$P1_AIR_OUT" p1air_defconfig
              make -C "$P1_AIR_OUT" ;;
      *) echo "usage: $0 p1-air [config|all]" >&2; exit 1 ;;
    esac ;;
  skyzone-steadydigital)
    # Kernel, board DTB and initramfs for RAM boot through the existing U-Boot.
    case "${2:-all}" in
      config) make -C "$BR" BR2_EXTERNAL="$EXT" O="$STEADYDIGITAL_OUT" skyzonesteadydigital_defconfig ;;
      kernel) make -C "$BR" BR2_EXTERNAL="$EXT" O="$STEADYDIGITAL_OUT" skyzonesteadydigital_defconfig
              make -C "$STEADYDIGITAL_OUT" linux-reconfigure ;;
      all)    need_native_runtime ascent
              need_stock_gnd_config
              make -C "$BR" BR2_EXTERNAL="$EXT" O="$STEADYDIGITAL_OUT" skyzonesteadydigital_defconfig
              make -C "$STEADYDIGITAL_OUT" ;;
      *) echo "usage: $0 skyzone-steadydigital [config|kernel|all]" >&2; exit 1 ;;
    esac ;;
  skyzone-steadydigital-flash)
    # Flashable NAND image: the installed kernel.img (for either bank) + packaged .fwu.
    # `recovery` then builds the slim upload recovery kernel the flasher boots
    # through the HID loader (images/kernel-recovery.img) from a copy of it.
    case "${2:-all}" in
      config) make -C "$BR" BR2_EXTERNAL="$EXT" O="$STEADYDIGITAL_FLASH_OUT" skyzonesteadydigital_flash_defconfig ;;
      # A reconfigured kernel needs its out-of-tree modules rebuilt too, or they
      # are rejected at load (struct module layout differs): no GPIO, no display.
      kernel) make -C "$BR" BR2_EXTERNAL="$EXT" O="$STEADYDIGITAL_FLASH_OUT" skyzonesteadydigital_flash_defconfig
              make -C "$STEADYDIGITAL_FLASH_OUT" linux-reconfigure
              for p in $(make -s -C "$STEADYDIGITAL_FLASH_OUT" linux-show-rdepends); do
                  make -C "$STEADYDIGITAL_FLASH_OUT" "$p-rebuild"; done ;;
      all)    need_native_runtime ascent
              need_stock_gnd_config
              make -C "$BR" BR2_EXTERNAL="$EXT" O="$STEADYDIGITAL_FLASH_OUT" skyzonesteadydigital_flash_defconfig
              make -C "$STEADYDIGITAL_FLASH_OUT" ;;
      recovery) "$EXT/board/skyzone-steadydigital/recovery-kernel.sh" "$STEADYDIGITAL_FLASH_OUT" ;;
      *) echo "usage: $0 skyzone-steadydigital-flash [config|kernel|all|recovery]" >&2; exit 1 ;;
    esac ;;
  ascent-vrx)
    # Kernel, board DTB and initramfs for RAM boot through the existing U-Boot.
    case "${2:-all}" in
      config) make -C "$BR" BR2_EXTERNAL="$EXT" O="$ASCENT_VRX_OUT" ascentvrx_defconfig ;;
      kernel) make -C "$BR" BR2_EXTERNAL="$EXT" O="$ASCENT_VRX_OUT" ascentvrx_defconfig
              make -C "$ASCENT_VRX_OUT" linux-reconfigure ;;
      all)    need_native_runtime ascent
              make -C "$BR" BR2_EXTERNAL="$EXT" O="$ASCENT_VRX_OUT" ascentvrx_defconfig
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
  # The boot chain is rebuilt right before every card: Buildroot rebuilds a
  # changed kernel without it, and the card would boot the old kernel with the
  # new modules (mk-sd-image.sh refuses such a pair).
  image)
    need_vendor
    make -C "$ASCENT_VRX_PRO_OUT" fpvos-bootchain-rebuild
    "$ROOT/boot/mk-sd-image.sh" ;;
  all)
    need_vendor
    make -C "$BR" BR2_EXTERNAL="$EXT" O="$ASCENT_VRX_PRO_OUT" ascentvrxpro_defconfig
    make -C "$BR" BR2_EXTERNAL="$EXT" O="$ASCENT_VRX_PRO_OUT"
    make -C "$ASCENT_VRX_PRO_OUT" fpvos-bootchain-rebuild
    "$ROOT/boot/mk-sd-image.sh" ;;
  *) echo "usage: $0 {[ascent-vrx-pro] {all|config|kestrel|image}|air [config|kernel|all]|ascent-vrx [config|kernel|all]|p1-goggle [config|kernel|all]|p1-gnd [config|kernel|all|recovery]|p1-air [config|all]|p1-air-source [config|all|recovery]}" >&2; exit 1 ;;
esac
