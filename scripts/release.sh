#!/bin/sh
# Assemble a flashable fpvOS release image.
#
# Extracts the vendor runtime and the stock boot chain from Caddx's own
# firmware release (scripts/extract-vendor.py), builds, and emits a card image
# plus checksums:
#
#   out/fpvos-vrxpro-<version>.img.xz
#   out/SHA256SUMS
#
# The vendor files are proprietary and are never committed to this repository;
# extract-vendor.py downloads the stock firmware (cached under ~/.cache/fpvos)
# the same way anyone building fpvOS does. A release pins it: the download must
# match the known-good release zip below, so a Caddx update behind the same
# link cannot slip different blobs into a release unnoticed.
#
#   FPVOS_FIRMWARE_SHA256  the release zip's SHA-256 (default: the known-good
#                          one, see extract-vendor.py)
#   FIRMWARE_OTA           extract from this VRX Pro image instead of the
#                          download - checked against FIRMWARE_OTA_SHA256
#                          (default: the known-good Ascent_VRX_Pro_18_21_10.img)
#
# It also cuts the release itself, and does so LAST - only once the image has
# been built and assembled - so a tag never names something that did not
# build. In order:
#
#   0. resolve the kestrel commit to release: the one KESTREL_PIN names -
#      the kestrel this fpvOS tree was built and tested with - or
#      KESTREL_COMMIT=<sha> to choose another. There is no release branch;
#      the tag is the release
#   1-3. extract the vendor files, build with exactly that commit, assemble,
#      compress
#   4. tag kestrel-gnd at that commit with VERSION and push the tag - it has
#      to be on the remote for anyone building the fpvOS tag to fetch it -
#      then write the tag into KESTREL_PIN in br-external/package/kestrel/
#      kestrel.mk, commit, and tag fpvOS with the same VERSION
#
# fpvOS's own push is deliberately left to you: that is the moment the release
# becomes public, and it should happen after the artifacts have been looked at.
# The script prints the exact command.
#
# A tag that already exists, on either side, is a hard stop. Release tags are
# never moved: Buildroot caches downloads by name, so a moved tag would be
# served stale to everyone who already built it.
#
#   KESTREL_COMMIT   release this kestrel commit instead of the branch head
#   KESTREL_PUSH_URL where to push the kestrel tag (default: KESTREL_SITE,
#                    over ssh for a github https URL)
#   DRY_RUN=1        do everything except push, commit and tag; prints what
#                    step 4 would do. Use it to rehearse a release.
#
# Usage:
#   scripts/release.sh v0.1.0
#   DRY_RUN=1 scripts/release.sh v0.1.0
#   FIRMWARE_OTA=~/.cache/fpvos/Ascent_VRX_Pro_18_21_10.img scripts/release.sh v0.1.0
#
# NOTE ON WHAT YOU ARE PUBLISHING: the resulting image contains the vendor
# runtime, which is extractable by anyone who downloads it. Publishing it is a
# public redistribution of that code, even though this repository never
# carries it.
set -e

VERSION=${1:?usage: release.sh VERSION   (e.g. 2026.09.alpha1)}
ROOT=$(cd "$(dirname "$0")/.." && pwd)
# Known-good stock firmware, as recorded in extract-vendor.py.
export FPVOS_FIRMWARE_SHA256=${FPVOS_FIRMWARE_SHA256:-833dc686a71e8e834096bdd97d8fc1392eee550e04bd219d1d6e04dd435a7997}
FIRMWARE_OTA_SHA256=${FIRMWARE_OTA_SHA256:-8e06ee54db882ac8d8c84a96f94bbaf87e245ddb0cc8e59dab460e10cd898389}
OUT="$ROOT/out"

mkdir -p "$OUT"

KESTREL_MK="$ROOT/br-external/package/kestrel/kestrel.mk"
KESTREL_SITE=${KESTREL_SITE:-$(sed -n 's/^KESTREL_SITE ?= //p' "$KESTREL_MK")}
DRY=${DRY_RUN:-0}

# --- 0. which kestrel, and is this version free ----------------------------
# Year.month of the release, then what it is: 2026.09.alpha1, 2026.10,
# 2026.10.1 for a fix to it.
case "$VERSION" in
    20[0-9][0-9].[01][0-9]|20[0-9][0-9].[01][0-9].*) ;;
    *) echo "VERSION should look like 2026.09 or 2026.09.alpha1 (got '$VERSION')" >&2; exit 1 ;;
esac
if [ -n "$KESTREL_COMMIT" ]; then
    KCOMMIT=$KESTREL_COMMIT
    echo ">>> kestrel: releasing requested commit $KCOMMIT"
else
    PIN=$(sed -n 's/^KESTREL_PIN = //p' "$KESTREL_MK")
    if echo "$PIN" | grep -qE '^[0-9a-f]{40}$'; then
        KCOMMIT=$PIN
    else
        # Already a tag (the last release): release the commit it names.
        KCOMMIT=$(git ls-remote -q "$KESTREL_SITE" "refs/tags/$PIN^{}" | cut -f1)
        [ -n "$KCOMMIT" ] || { echo "could not resolve KESTREL_PIN '$PIN' at $KESTREL_SITE" >&2; exit 1; }
    fi
    echo ">>> kestrel: releasing the pinned commit $KCOMMIT (KESTREL_PIN = $PIN)"
fi
if git ls-remote -q --tags "$KESTREL_SITE" "refs/tags/$VERSION" | grep -q .; then
    echo "kestrel-gnd already has tag $VERSION - release tags are never moved" >&2; exit 1
fi
if git -C "$ROOT" rev-parse -q --verify "refs/tags/$VERSION" >/dev/null; then
    echo "fpvOS already has tag $VERSION - release tags are never moved" >&2; exit 1
fi
if [ -n "$(git -C "$ROOT" status --porcelain)" ]; then
    echo "fpvOS working tree is not clean - commit or stash first" >&2; exit 1
fi
# The build below uses exactly this commit, whatever the pin currently says.
export KESTREL_VERSION="$KCOMMIT"
# The version the image reports - /etc/fpvos-version, os-release and the
# kestrel menu (kestrel.mk passes it on) - all come from VERSION. Write it now,
# before the build; step 5 commits it with the release.
echo "$VERSION" > "$ROOT/VERSION"
# A workspace buildroot/local.mk builds kestrel from a local checkout instead
# of the commit being released. Keep it out of the way until we are done.
work=$(mktemp -d)
LOCAL_MK="$ROOT/buildroot/local.mk"
if [ -e "$LOCAL_MK" ]; then
    mv "$LOCAL_MK" "$work/local.mk"
    echo ">>> moved buildroot/local.mk aside for the release build"
fi
trap '[ -e "$work/local.mk" ] && mv "$work/local.mk" "$LOCAL_MK"; rm -rf "$work"' EXIT

# --- 1. vendor runtime + stock boot chain -----------------------------------
# From scratch every time: nothing left from an earlier extraction - a
# --from-device one in particular, which can carry one goggle's pairing - may
# end up in a release. extract-vendor.py fills vendor/rootfs (the runtime) and
# vendor/stock (the unmodified uboot.img and boot.img the fpvos-bootchain
# package turns into the boot chain).
rm -rf "$ROOT/vendor/rootfs" "$ROOT/vendor/stock" "$ROOT/vendor/boot"
if [ -n "$FIRMWARE_OTA" ]; then
    got=$(sha256sum "$FIRMWARE_OTA" | cut -d' ' -f1)
    [ "$got" = "$FIRMWARE_OTA_SHA256" ] ||
        { echo "$FIRMWARE_OTA: SHA-256 $got, expected $FIRMWARE_OTA_SHA256" >&2; exit 1; }
    echo ">>> vendor: extracting from $FIRMWARE_OTA"
    python3 "$ROOT/scripts/extract-vendor.py" --from-ota "$FIRMWARE_OTA"
else
    echo ">>> vendor: extracting from the stock firmware release (pinned $FPVOS_FIRMWARE_SHA256)"
    python3 "$ROOT/scripts/extract-vendor.py" --download
fi
for d in rootfs stock; do
    [ -d "$ROOT/vendor/$d" ] || { echo "extract-vendor.py left no vendor/$d" >&2; exit 1; }
done
# Per-unit identity never goes into a release - see step 2 for why. Drop it
# here, before the build can see it, whatever the extraction carried.
if [ -e "$ROOT/vendor/rootfs/factory" ]; then
    rm -rf "$ROOT/vendor/rootfs/factory"
    echo ">>> dropped vendor/rootfs/factory (per-unit identity, never published)"
fi
echo ">>> vendor: $(find "$ROOT/vendor/rootfs" -type f | wc -l) runtime files, $(ls "$ROOT/vendor/stock" | tr '\n' ' ')"

# --- 2. build the rootfs (post-build.sh merges vendor/rootfs) --------------
# /factory/user_cfg.json holds the MAC addresses of the air units ONE goggle is
# paired with, and fact_env.json that unit's saved settings. They are fine in a
# build you make for yourself and must never leave the building in a release:
# publishing them hands out one owner's pairing data to every downloader, and
# the recipient's goggle would try to associate with someone else's aircraft.
#
# Step 1 kept them out of vendor/, but Buildroot's target directory survives
# between builds, so a copy from an earlier personal build can still be sitting
# in it. Remove that before building - rootfs.ext2 is generated from the target
# during the build, so removing anything afterwards changes nothing in the
# image. Step 3 then checks the finished image rather than trusting any of this.
# Each downloader's own list is merged from their goggle's NAND at boot
# (S50factory); the empty /factory directory stays so that path exists.
T="$ROOT/buildroot/output/target"
for f in user_cfg.json fact_env.json; do
    if [ -e "$T/factory/$f" ]; then
        rm -f "$T/factory/$f"
        echo ">>> removed stale /factory/$f from the build target"
    fi
done

# Skip with SKIP_BUILD=1 to re-assemble an image from an existing build.
if [ "${SKIP_BUILD:-0}" != "1" ]; then
    echo ">>> building"
    "$ROOT/build.sh" config
    "$ROOT/build.sh" >/dev/null 2>&1 || "$ROOT/build.sh"
fi

# --- 3. assemble the card image -------------------------------------------
echo ">>> assembling image"
# COMPRESS=0: the .xz is made in step 4, after step 3b has checked the image.
COMPRESS=0 OUT="$OUT/fpvos-vrxpro-$VERSION.img" "$ROOT/boot/mk-sd-image.sh"
IMG="$OUT/fpvos-vrxpro-$VERSION.img"

# --- 3b. prove the image carries no per-unit identity ---------------------
# Read the rootfs partition back out of the assembled image and list /factory
# with debugfs (no mount, no root). Buildroot builds debugfs for the host as
# part of the ext4 rootfs; a system one works too.
DEBUGFS="$ROOT/buildroot/output/host/sbin/debugfs"
[ -x "$DEBUGFS" ] || DEBUGFS=$(command -v debugfs || true)
[ -n "$DEBUGFS" ] || { echo "debugfs not found - cannot verify the image (apt install e2fsprogs)" >&2; exit 1; }
P2_START=$(sed -n 's/^P2_START=\([0-9]*\);.*/\1/p' "$ROOT/boot/mk-sd-image.sh")
[ -n "$P2_START" ] || { echo "could not read P2_START from boot/mk-sd-image.sh" >&2; exit 1; }
FS_BYTES=$(stat -c %s "$ROOT/buildroot/output/images/rootfs.ext2")
dd if="$IMG" of="$work/rootfs.ext4" bs=512 skip="$P2_START" count=$(( FS_BYTES / 512 )) status=none
# A listing of / that lacks etc means debugfs could not read the filesystem,
# and an empty /factory listing from that would prove nothing.
"$DEBUGFS" -R "ls -p /" "$work/rootfs.ext4" 2>/dev/null | grep -q '/etc/' ||
    { echo "could not read the rootfs out of $IMG - not verified" >&2; exit 1; }
leak=$("$DEBUGFS" -R "ls -p /factory" "$work/rootfs.ext4" 2>/dev/null |
       grep -oE '/(user_cfg|fact_env)\.json/' | tr -d / | tr '\n' ' ' || true)
rm -f "$work/rootfs.ext4"
if [ -n "$leak" ]; then
    rm -f "$IMG"
    echo "RELEASE ABORTED: the image carries one goggle's pairing data in /factory: $leak" >&2
    echo "Image deleted. Rebuild without SKIP_BUILD so the target is regenerated." >&2
    exit 1
fi
echo ">>> verified: no /factory pairing data in the image"

# --- 4. compress + checksum -----------------------------------------------
echo ">>> compressing"
xz -T0 -f "$IMG"
( cd "$OUT" && sha256sum "fpvos-vrxpro-$VERSION.img.xz" > SHA256SUMS )

echo
echo "=== release artifacts ==="
ls -la "$OUT"

# --- 5. cut the release: tag kestrel, pin it, tag fpvOS --------------------
# Only now. Everything above has to have succeeded for a tag to be deserved.
echo
if [ "$DRY" = 1 ]; then
    echo ">>> DRY RUN - would: tag kestrel-gnd $VERSION at $KCOMMIT and push it;"
    echo ">>>            set KESTREL_PIN = $VERSION in kestrel.mk; commit; tag fpvOS $VERSION"
    git -C "$ROOT" checkout -q -- VERSION
else
    echo ">>> tagging kestrel-gnd $VERSION at $KCOMMIT"
    # Pushing needs credentials an https URL does not carry here: push over ssh.
    KESTREL_PUSH_URL=${KESTREL_PUSH_URL:-$(echo "$KESTREL_SITE" | sed 's#^https://github.com/#git@github.com:#')}
    git clone -q --no-checkout "$KESTREL_PUSH_URL" "$work/kestrel"
    git -C "$work/kestrel" tag -a "$VERSION" "$KCOMMIT" -m "fpvOS release $VERSION"
    git -C "$work/kestrel" push -q origin "refs/tags/$VERSION"
    echo ">>> pinning kestrel $VERSION in $KESTREL_MK"
    sed -i "s/^KESTREL_PIN = .*/KESTREL_PIN = $VERSION/" "$KESTREL_MK"
    grep -q "^KESTREL_PIN = $VERSION\$" "$KESTREL_MK" || { echo "failed to write the pin" >&2; exit 1; }
    git -C "$ROOT" add "$KESTREL_MK" "$ROOT/VERSION"
    git -C "$ROOT" commit -q -m "Release $VERSION

kestrel-gnd $VERSION ($KCOMMIT). Image: fpvos-vrxpro-$VERSION.img.xz"
    git -C "$ROOT" tag -a "$VERSION" -m "fpvOS $VERSION - kestrel-gnd $VERSION ($KCOMMIT)"
    echo ">>> fpvOS committed and tagged $VERSION (not pushed)"
fi

echo
echo "flash with balenaEtcher (Flash from file -> fpvos-vrxpro-$VERSION.img.xz, no need to unpack),"
echo "or:"
echo "  xz -dc fpvos-vrxpro-$VERSION.img.xz | sudo dd of=/dev/sdX bs=4M conv=fsync && sync"
if [ "$DRY" != 1 ]; then
    echo
    echo "publish with (after checking the artifacts):"
    echo "  git -C $ROOT push origin main refs/tags/$VERSION"
fi
