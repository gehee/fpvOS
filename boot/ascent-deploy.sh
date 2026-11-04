#!/bin/bash
# Put the air app of a built image on a running Ascent Lite or Lite+ over ssh, without
# flashing it: the files under fpv/air/ and the hooked fpv_run_cx482.sh, taken
# from the same app volume the PC tool would flash, so the result is the same.
#
#   boot/ascent-deploy.sh [--dry] [--reboot] [HOST]       (HOST default root@192.168.5.104)
#   IMG=path/to/Ascent_H_Sky_*.img                        (default: output-air/images/)
#
# Needs ssh to the unit (build with FPVOS_AIR_SSH_KEYS, enable_rndis.py, and the
# host address and route; see docs/BUILD.md). Nothing is run on the unit but tar,
# mv, md5sum and sync. Reboot it afterwards (--reboot does): the radio driver is
# not swapped on a running chip.
#
# Every file is written beside its place and then renamed over it, so files in
# use (the running kestrel-air, dropbear) are replaced safely and the running
# programs go on with their old copy until the reboot. The old hook script is
# kept once as fpv_run_cx482.sh.prev. What is no longer in the image is left.
# After the copy, every file is compared by md5 on the unit.
#
# The unit's /usrdata is the same flash the PC tool writes: this is a different
# way to write the app volume, not a trial run. A reflash with the PC tool
# always puts the whole volume back.
set -eu

ROOT=$(cd "$(dirname "$0")/.." && pwd)
DRY=0; REBOOT=0; HOST=root@192.168.5.104
for a in "$@"; do
    case $a in
        --dry) DRY=1 ;;
        --reboot) REBOOT=1 ;;
        -*) echo "unknown option $a" >&2; exit 2 ;;
        *) HOST=$a ;;
    esac
done
IMG=${IMG:-$ROOT/output-air/images/Ascent_H_Sky_18_21_10.img}
[ -f "$IMG" ] || { echo "no image: $IMG (./build.sh air)" >&2; exit 1; }
# DEPLOY_SH replaces "ssh HOST" in the tests: the unit's side runs locally under UNIT_ROOT.
UNIT_ROOT=${UNIT_ROOT:-/usrdata}
unit() { if [ -n "${DEPLOY_SH:-}" ]; then $DEPLOY_SH "$@"; else ssh -o BatchMode=yes -o ConnectTimeout=30 -o LogLevel=ERROR "$HOST" "$@"; fi; }

T=$(mktemp -d)
trap 'rm -rf "$T"' EXIT
"$ROOT/boot/mkascentimg.py" extract "$IMG" "$T/img" > /dev/null
VOL=$T/img/fpv                      # the app volume's root: contains fpv/
FILES="fpv/air fpv/fpv_run_cx482.sh"
[ -x "$VOL/fpv/air/start.sh" ] || { echo "the image has no fpv/air/start.sh" >&2; exit 1; }

echo "image: $(cat "$VOL/fpv/air/VERSION")  ($(basename "$IMG"))"
echo "unit:  $(unit "cat $UNIT_ROOT/fpv/air/VERSION 2>/dev/null || echo 'no fpv/air yet'")"

(cd "$VOL" && find $FILES -type f -exec md5sum {} + | sort -k2) > "$T/sums"
echo "files: $(wc -l < "$T/sums") (+ links)"
if [ $DRY = 1 ]; then echo "--dry: nothing copied"; exit 0; fi

# 1. send everything to a staging directory next to the volume's files
unit "rm -rf $UNIT_ROOT/.deploy && mkdir -p $UNIT_ROOT/.deploy"
tar -C "$VOL" --owner=0 --group=0 --numeric-owner -c $FILES | unit "cd $UNIT_ROOT/.deploy && tar x"

# 2. rename each file over its place (symlinks and directories included); keep the
#    old hook script once
unit "set -e; cd $UNIT_ROOT/.deploy
[ -e $UNIT_ROOT/fpv/fpv_run_cx482.sh.prev ] || cp -p $UNIT_ROOT/fpv/fpv_run_cx482.sh $UNIT_ROOT/fpv/fpv_run_cx482.sh.prev
find fpv -type d | while read d; do [ -d $UNIT_ROOT/\$d ] || { mkdir -p $UNIT_ROOT/\$d; chmod --reference=\$d $UNIT_ROOT/\$d 2>/dev/null || true; }; done
find fpv ! -type d | while read f; do mv -f \$f $UNIT_ROOT/\$f; done
cd $UNIT_ROOT && rm -rf .deploy && sync"

# 3. compare every file by md5 on the unit
(cd "$VOL" && cat "$T/sums") | unit "cd $UNIT_ROOT && md5sum -c -" > "$T/check" 2>&1 || true
bad=$(grep -E ': FAILED|No such file|md5sum:' "$T/check" || true)
if [ -n "$bad" ]; then echo "MISMATCH after the copy:"; echo "$bad"; exit 1; fi
echo "all $(wc -l < "$T/sums") files match the image"

if [ $REBOOT = 1 ]; then
    echo "rebooting the unit"
    unit "sync; reboot" || true
else
    echo "now reboot the unit (ssh $HOST reboot) to run it; the radio driver is not swapped on a running chip"
fi
