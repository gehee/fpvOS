#!/bin/sh
# Buildroot post-build hook: merge the extracted vendor runtime into the target.
#
# The proprietary pieces fpvOS cannot ship (AR8030 baseband userland + firmware,
# libmali, librga) are fetched by scripts/extract-ascent-vrx-pro-firmware.py into vendor/rootfs/.
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

# Vendor files fpvOS does not ship at all, even when an extraction carries them
# (dropped by the case in the loop below):
#
#   ar_fpv_upgrade   - stock's firmware upgrade agent, which writes the NAND.
#                      fpvOS upgrades by reflashing the card.
#   factory_mount.sh - stock's /factory mount, which ubiformats the NAND
#                      partition when a mount fails. S50factory reads it
#                      read-only instead.
#
# With ar-libre (arlink.ko in the target), Artosyn's radio host stack is not
# shipped either: arlink.ko, its library and bb_only.sh replace the stock
# driver, the client library and the daemon. Only the chip's own firmware and
# config are still Artosyn's.
OPEN_RADIO=
ls "$TARGET"/lib/modules/*/*/arlink.ko >/dev/null 2>&1 && OPEN_RADIO=1

# /factory/user_cfg.json is the goggle's pairing list: the bb_mac_addr_N
# entries are the air units it may link with. kestrel seeds BB_SET_CANDIDATES
# from it, and its bind menu adds to it.
#
# The image does not need to carry one. At every boot S50factory merges in the
# air units stock has paired, read from the goggle's own NAND, and a unit
# never paired under stock is bound once from the menu. A copy pulled with
# `extract-ascent-vrx-pro-firmware.py --from-device` still lands here via the merge below, but
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

# Build-time-only packages Buildroot installs with Mesa's shader precompiler:
# LLVM, Clang, libclc, the SPIR-V translator and the SPIR-V tools. Mesa is
# built without LLVM (external.mk) and its OpenCL-C shaders are compiled on
# the host, so on the goggle the only one of their files in use is
# libSPIRV-Tools.so, which libgallium links. Everything else each package
# installed - per Buildroot's own record of it - is removed.
#
# The check below fails the build if anything left on the target still links
# a removed library, rather than shipping a broken GL stack.
PRUNE_PKGS='llvm clang libclc spirv-llvm-translator spirv-tools'
PRUNE_KEEP='./usr/lib/libSPIRV-Tools.so'
FILE_LIST="$BUILD_DIR/packages-file-list.txt"
if [ -f "$FILE_LIST" ]; then
    removed=$(mktemp)
    awk -F, -v pkgs="$PRUNE_PKGS" -v keep="$PRUNE_KEEP" '
        BEGIN { n = split(pkgs, p, " "); for (i = 1; i <= n; i++) want[p[i]] = 1
                m = split(keep, k, " "); for (i = 1; i <= m; i++) kept[k[i]] = 1 }
        want[$1] && !kept[$2] { print $2 }' "$FILE_LIST" | sort -u |
    while read -r f; do
        [ -e "$TARGET/$f" ] || [ -L "$TARGET/$f" ] || continue
        rm -f "$TARGET/$f"
        echo "${f##*/}" >> "$removed"
    done
    rm -rf "$TARGET/usr/share/clc" "$TARGET/usr/lib/clang"
fi
# The file list only records what a package installed in its last install
# step, and a reinstall drops a package's earlier entries - so after a partial
# rebuild it can miss files. These patterns catch the same packages by name.
removed=${removed:-$(mktemp)}
for f in "$TARGET"/usr/lib/libLLVM* "$TARGET"/usr/lib/libclang* \
         "$TARGET"/usr/lib/libLTO.so* "$TARGET"/usr/lib/libRemarks.so* \
         "$TARGET"/usr/lib/libSPIRV-Tools-* "$TARGET"/usr/bin/spirv-* \
         "$TARGET"/usr/bin/llvm-* "$TARGET"/usr/bin/clang* \
         "$TARGET"/usr/bin/diagtool "$TARGET"/usr/bin/*-arch; do
    case "$f" in */setarch|*/uname26) continue ;; esac
    [ -e "$f" ] || [ -L "$f" ] || continue
    rm -f "$f"
    echo "${f##*/}" >> "$removed"
done
if [ -s "$removed" ]; then
    READELF=$(ls "$HOST_DIR"/bin/*-readelf 2>/dev/null | head -1)
    [ -x "$READELF" ] || READELF=readelf
    missing=$(find "$TARGET" -type f \( -name '*.so*' -o -perm -u+x \) -print0 |
        xargs -0 "$READELF" -d 2>/dev/null |
        sed -n 's/.*(NEEDED).*\[\(.*\)\]/\1/p' | sort -u |
        grep -Fxf "$removed" || true)
    echo ">>> removed $(wc -l < "$removed") build-time-only files ($PRUNE_PKGS)"
    rm -f "$removed"
    if [ -n "$missing" ]; then
        echo ">>> ERROR: removed libraries are still needed on the target: $missing" >&2
        exit 1
    fi
else
    rm -f "$removed"
fi

# linux-firmware's rtlwifi licence asks for its notice to go with the binaries;
# Buildroot only puts it in legal-info.
if [ -d "$TARGET/lib/firmware/rtlwifi" ]; then
    lic=$(ls "$BUILD_DIR"/linux-firmware-*/LICENCE.rtlwifi_firmware.txt 2>/dev/null | head -1)
    [ -n "$lic" ] || { echo ">>> ERROR: rtlwifi firmware shipped without its licence" >&2; exit 1; }
    cp "$lic" "$TARGET/lib/firmware/rtlwifi/"
fi

if [ ! -d "$VENDOR" ]; then
    echo ">>> vendor runtime absent - building blob-free."
    echo ">>>   supply it with: scripts/extract-ascent-vrx-pro-firmware.py"
    exit 0
fi

# With Mesa as the GL stack there is no kbase driver in the kernel, so the stock
# libmali has nothing to talk to: leave it out.
NO_MALI=0
grep -q '^BR2_PACKAGE_MESA3D=y' "$BR2_CONFIG" 2>/dev/null && NO_MALI=1

# Stock's binary kernel modules (artosyn_drv, the WiFi and IMU drivers) only
# load into a kernel built exactly like stock's. With a kernel built from
# source for another release they are dead weight, and a fallback that cannot
# work: leave them out. (No kernel built, as with the stock kernel: keep them.)
KREL=$(cd "$TARGET/lib/modules" 2>/dev/null && ls -d */ 2>/dev/null | head -1)
KREL=${KREL%/}

# A file left out is also removed from the target: Buildroot never cleans it,
# so one merged by an earlier build would otherwise stay.
drop() { echo ">>>   dropping $rel ($1)"; rm -f "$TARGET/$rel"; }

merged=0
skipped=0
cd "$VENDOR"
find . -type f | while read -r f; do
    rel=${f#./}
    case "$rel" in
        *$SKIP*) echo ">>>   skipping $rel (built from source)"; continue ;;
        ar8030soc/ar_fpv_upgrade|ar8030soc/factory_mount.sh)
                 drop "not shipped"; continue ;;
        usr/lib/libmali*)
                 [ "$NO_MALI" = 1 ] && { drop "Mesa is the GL stack"; continue; } ;;
        ar8030soc/daemon|ar8030soc/artosyn_drv.ko|ar8030soc/libar8030_client.so)
                 [ -n "$OPEN_RADIO" ] && { drop "ar-libre replaces it"; continue; } ;;
        usr/lib/libar8030_client.so)
                 # ar-libre installs its own here: leave it, merge nothing.
                 [ -n "$OPEN_RADIO" ] && { echo ">>>   skipping $rel (ar-libre's)"; continue; } ;;
    esac
    case "$rel" in
        *.ko) km=$(grep -ao 'vermagic=[^ ]*' "$f" | head -1)
              if [ -n "$KREL" ] && [ "${km#vermagic=}" != "$KREL" ]; then
                  drop "built for ${km#vermagic=}, the kernel is $KREL"; continue
              fi ;;
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

n=$(find "$VENDOR/" -type f | wc -l)
echo ">>> merged vendor runtime into the target rootfs ($n files considered, $SKIP excluded)"

# Say whether this image carries one goggle's pairing list, since that is
# what must never go into a release.
if [ -f "$TARGET/factory/user_cfg.json" ]; then
    echo ">>> /factory/user_cfg.json baked in - this image is tied to one goggle"
else
    echo ">>> no baked-in pairing list - stock's is merged from NAND at boot"
fi
