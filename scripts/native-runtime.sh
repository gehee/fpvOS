#!/bin/bash
# The AR9311 receivers' kestrel-gnd runtime (KESTREL_NATIVE_IMAGE), built from
# fpvOS's own pins:
#   scripts/native-runtime.sh ascent     # Ascent VRX, Skyzone SteadyDigital
#   scripts/native-runtime.sh p1goggle   # BETAFPV P1 goggles
# kestrel-gnd at KESTREL_PIN and ar_libre at AR_LIBRE_VERSION (from
# KESTREL_SITE and AR_LIBRE_SITE, GitHub unless set), built natively for
# AArch64 in scripts/native-runtime/Dockerfile (emulated on another host) with
# SOURCE_DATE_EPOCH at kestrel-gnd's commit time, so the same pins give the
# same file. kestrel-native checks it against
# br-external/package/kestrel-native/runtime.hash; after moving a pin, run
# this for both boards and put the sums it prints there.
#
# Out: output/kestrel-runtime/runtime-<board>.squashfs (where kestrel-native
# looks for it), and beside it runtime-<board>.pins, what it was built from.
# Needs Docker (and binfmt/QEMU for arm64 on another architecture).
set -euo pipefail

BOARD=${1:?usage: $0 ascent|p1goggle}
case "$BOARD" in ascent|p1goggle) ;; *) echo "$0: board is ascent or p1goggle, not $BOARD" >&2; exit 2;; esac
ROOT=$(cd "$(dirname "$0")/.." && pwd)
PKG=$ROOT/br-external/package

# A make variable as a package's .mk file sets it (VAR = or VAR ?=).
mkvar() { sed -nE "s/^$1 *\??= *([^ ]+) *$/\1/p" "$PKG"/*/*.mk | head -1; }
KG_REV=$(mkvar KESTREL_PIN)
AR_REV=${AR_LIBRE_VERSION:-$(mkvar AR_LIBRE_VERSION)}
KG_SITE=${KESTREL_SITE:-$(mkvar KESTREL_SITE)}
AR_SITE=${AR_LIBRE_SITE:-$(mkvar AR_LIBRE_SITE)}
[ -n "$KG_REV" ] && [ -n "$AR_REV" ] && [ -n "$KG_SITE" ] && [ -n "$AR_SITE" ] ||
	{ echo "$0: kestrel-gnd or ar_libre pin not found under $PKG" >&2; exit 1; }

DOCKERFILE=$ROOT/scripts/native-runtime/Dockerfile
ENV_ID=$(sha256sum "$DOCKERFILE" | cut -c1-12)
IMAGE=fpvos-native-runtime:$ENV_ID
OUTDIR=$ROOT/output/kestrel-runtime
WORK=$OUTDIR/work-$BOARD
OUT=$OUTDIR/runtime-$BOARD.squashfs
mkdir -p "$WORK"

# The sources, at their pins.
fetch() {  # DIR SITE REV
	[ -d "$1/.git" ] || git clone -q "$2" "$1"
	git -C "$1" cat-file -e "$3^{commit}" 2>/dev/null || git -C "$1" fetch -q "$2"
	git -C "$1" checkout -q --detach "$3"
	git -C "$1" clean -q -ffdx
}
fetch "$WORK/kestrel-gnd" "$KG_SITE" "$KG_REV"
fetch "$WORK/ar_libre" "$AR_SITE" "$AR_REV"
KG_REV=$(git -C "$WORK/kestrel-gnd" rev-parse HEAD)
AR_REV=$(git -C "$WORK/ar_libre" rev-parse HEAD)
EPOCH=$(git -C "$WORK/kestrel-gnd" log -1 --format=%ct HEAD)

# The idle screen's font and background are the VRX Pro's.
ASSETS=$ROOT/br-external/board/ascent-vrx-pro/rootfs-overlay
cp "$ASSETS/usr/share/fonts/truetype/chakra-petch/ChakraPetch-SemiBold.ttf" \
   "$ASSETS/usr/share/fonts/truetype/chakra-petch/OFL.txt" \
   "$ASSETS/etc/kestrel/background.png" "$WORK/"

docker build -q --platform linux/arm64 -t "$IMAGE" \
	--build-arg UID="$(id -u)" --build-arg GID="$(id -g)" "$(dirname "$DOCKERFILE")" > /dev/null
# The build directory starts empty every time: nothing from an earlier pin.
docker run --rm --platform linux/arm64 -v "$WORK:/w" -e SOURCE_DATE_EPOCH="$EPOCH" \
	-e BOARD="$BOARD" -e KG_REV="$KG_REV" ${NATIVE_RUNTIME_DOCKER_ARGS:-} "$IMAGE" bash -euo pipefail -c '
	rm -rf /w/build /w/runtime.squashfs
	cc -O2 -Wall -pthread -c /w/ar_libre/lib/arlink.c -o /w/arlink.o
	rm -f /w/libar8030_client.a && ar rcsD /w/libar8030_client.a /w/arlink.o
	cmake -S /w/kestrel-gnd -B /w/build -G Ninja -DCMAKE_BUILD_TYPE=Release \
		-DKESTREL_HAL=ar9311 -DKESTREL_BOARD="$BOARD" \
		-DCMAKE_EXE_LINKER_FLAGS=-static \
		-DAR8030_LIB=/w/libar8030_client.a -DDRM_UAPI_INCLUDE_DIR=/usr/include/drm \
		-DKESTREL_UI_FONT=/w/ChakraPetch-SemiBold.ttf -DKESTREL_UI_BACKGROUND=/w/background.png \
		-DKESTREL_GND_GIT_HASH_FALLBACK="${KG_REV:0:8}" > /w/cmake.log
	ninja -C /w/build > /w/ninja.log
	python3 /w/kestrel-gnd/tools/package_ascent.py --strip strip /w/build /w/runtime.squashfs > /w/package.log
'
mv "$WORK/runtime.squashfs" "$OUT"
SUM=$(sha256sum "$OUT" | cut -d' ' -f1)
printf 'kestrel-gnd %s\nar_libre %s\nenvironment %s\nsha256 %s\n' "$KG_REV" "$AR_REV" "$ENV_ID" "$SUM" > "$OUTDIR/runtime-$BOARD.pins"
printf '%s  %s  (kestrel-gnd %s, ar_libre %s, board %s)\n' "$SUM" "$OUT" "${KG_REV:0:8}" "${AR_REV:0:7}" "$BOARD"
