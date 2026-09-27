#!/bin/sh
# Buildroot post-build hook: merge the extracted vendor runtime into the target.
#
# The proprietary pieces fpvOS cannot ship (AR8030 baseband userland + firmware,
# libmali, librga) are fetched by scripts/extract-vendor.py into vendor/rootfs/.
# They are laid over the target here rather than through BR2_ROOTFS_OVERLAY so
# that a build with NO vendor blobs still succeeds: CI builds the open tree
# without them and the image simply comes up with kestrel unable to reach the
# radio or the GPU until they are supplied.
#
# $1 is TARGET_DIR (Buildroot passes it).
set -e

TARGET=$1
VENDOR="$(cd "$(dirname "$0")/../../.." && pwd)/vendor/rootfs"

# Files Buildroot now builds from source. The vendor copies are kept in the
# blob set as a fallback, but must NOT be laid over the built ones - otherwise
# the from-source build is silently discarded and we ship the vendor binary
# while believing we ship ours.
#
#   librockchip_mpp  - built from the rockchip-mpp package (Apache-2.0/MIT).
#                      Remove this exclusion to fall back to the vendor blob
#                      if a from-source MPP ever regresses hardware decode.
SKIP='librockchip_mpp'

# Vendor files fpvOS does not ship at all, even when an older extraction or the
# vendor-blobs repo still carries them (dropped by the case in the loop below):
#
#   ar_fpv_upgrade   - stock's firmware upgrade agent, which writes the NAND.
#                      fpvOS upgrades by reflashing the card.
#   factory_mount.sh - stock's /factory mount, which ubiformats the NAND
#                      partition when a mount fails. S50factory reads it
#                      read-only instead.

# /factory/user_cfg.json is the goggle's pairing list: the bb_mac_addr_N
# entries are the air units it may link with. kestrel seeds BB_SET_CANDIDATES
# from it, and its bind menu adds to it.
#
# The image does not need to carry one. At every boot S50factory merges in the
# air units stock has paired, read from the goggle's own NAND, and a unit
# never paired under stock is bound once from the menu. A copy pulled with
# `extract-vendor.py --from-device` still lands here via the merge below, but
# only for a build meant for that one goggle - never ship it in a release.
mkdir -p "$TARGET/factory"

# The fpvOS version, from VERSION at the top of the tree: /etc/fpvos-version
# for scripts, and os-release so the system names itself fpvOS, not Buildroot.
FPVOS_VERSION=$(cat "${VENDOR%/vendor/rootfs}/VERSION")
echo "$FPVOS_VERSION" > "$TARGET/etc/fpvos-version"
if [ -f "$TARGET/usr/lib/os-release" ]; then
    sed -i -e "s/^NAME=.*/NAME=fpvOS/" -e "s/^ID=.*/ID=fpvos/" \
           -e "s/^VERSION=.*/VERSION=$FPVOS_VERSION/" \
           -e "s/^VERSION_ID=.*/VERSION_ID=$FPVOS_VERSION/" \
           -e "s/^PRETTY_NAME=.*/PRETTY_NAME=\"fpvOS $FPVOS_VERSION\"/" \
           "$TARGET/usr/lib/os-release"
fi

if [ ! -d "$VENDOR" ]; then
    echo ">>> vendor runtime absent - building blob-free."
    echo ">>>   supply it with: scripts/extract-vendor.py"
    exit 0
fi

merged=0
skipped=0
cd "$VENDOR"
find . -type f | while read -r f; do
    rel=${f#./}
    case "$rel" in
        *$SKIP*) echo ">>>   skipping $rel (built from source)"; continue ;;
        ar8030soc/ar_fpv_upgrade|ar8030soc/factory_mount.sh)
                 echo ">>>   dropping $rel (not shipped)"; continue ;;
    esac
    dst="$TARGET/$rel"
    mkdir -p "$(dirname "$dst")"
    # Remove the destination first. cp onto a symlink writes THROUGH it and
    # overwrites whatever it points at (this is how the vendor MPP silently
    # replaced the from-source build); removing first makes the overlay
    # deterministic - the vendor file lands exactly where it is named.
    rm -f "$dst"
    cp -a "$f" "$dst"
done

n=$(find "$VENDOR" -type f | wc -l)
echo ">>> merged vendor runtime into the target rootfs ($n files considered, $SKIP excluded)"

# Say whether this image carries one goggle's pairing list, since that is
# what must never go into a release.
if [ -f "$TARGET/factory/user_cfg.json" ]; then
    echo ">>> /factory/user_cfg.json baked in - this image is tied to one goggle"
else
    echo ">>> no baked-in pairing list - stock's is merged from NAND at boot"
fi
