#!/bin/bash
# Put the GT air app of a built image on a running Ascent GT over ssh, without
# flashing it: fpv/air/ only. The unit's fpv_run_cx4861.sh is hooked in place,
# after its updater. The stock ar_ldyhs_sky stays: libsns_ps5280.so maps it.
#
#   boot/ascent-gt-deploy.sh [--dry] [--reboot] [HOST]
#   IMG=path/to/Ascent_G_Sky_*.img     (default: the newest output-gt/images/)
#
# Do not point this at a Lite, and do not flash an H_Sky image onto the GT.
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
if [ -n "${IMG:-}" ]; then
    :
else
    IMG=$(ls -1 "$ROOT"/output-gt/images/Ascent_G_Sky_*.img 2>/dev/null | tail -n 1 || true)
fi
[ -n "${IMG:-}" ] && [ -f "$IMG" ] || { echo "no GT image (./build.sh gt)" >&2; exit 1; }
UNIT_ROOT=${UNIT_ROOT:-/usrdata}
unit() { if [ -n "${DEPLOY_SH:-}" ]; then $DEPLOY_SH "$@"; else ssh -o BatchMode=yes -o ConnectTimeout=30 -o LogLevel=ERROR "$HOST" "$@"; fi; }

T=$(mktemp -d)
trap 'rm -rf "$T"' EXIT
"$ROOT/boot/mkascentimg.py" extract "$IMG" "$T/img" > /dev/null
VOL=$T/img/fpv
FILES="fpv/air"
[ -x "$VOL/fpv/air/start.sh" ] || { echo "the image has no fpv/air/start.sh" >&2; exit 1; }
unit "test -f $UNIT_ROOT/fpv/fpv_run_cx4861.sh" || { echo "unit has no fpv_run_cx4861.sh" >&2; exit 1; }

echo "image: $(cat "$VOL/fpv/air/VERSION")  ($(basename "$IMG"))"
echo "unit:  $(unit "cat $UNIT_ROOT/fpv/air/VERSION 2>/dev/null || echo 'no fpv/air yet'")"

(cd "$VOL" && find $FILES -type f -exec md5sum {} + | sort -k2) > "$T/sums"
echo "files: $(wc -l < "$T/sums") (+ links)"
if [ $DRY = 1 ]; then echo "--dry: nothing copied"; exit 0; fi

unit "rm -rf $UNIT_ROOT/.deploy && mkdir -p $UNIT_ROOT/.deploy"
tar -C "$VOL" --owner=0 --group=0 --numeric-owner -c $FILES | unit "cd $UNIT_ROOT/.deploy && tar x"
unit "set -e; cd $UNIT_ROOT/.deploy
find fpv -type d | while read d; do [ -d $UNIT_ROOT/\$d ] || { mkdir -p $UNIT_ROOT/\$d; chmod --reference=\$d $UNIT_ROOT/\$d 2>/dev/null || true; }; done
find fpv ! -type d | while read f; do mv -f \$f $UNIT_ROOT/\$f; done
cd $UNIT_ROOT && rm -rf .deploy && sync"

(cd "$VOL" && cat "$T/sums") | unit "cd $UNIT_ROOT && md5sum -c -" > "$T/check" 2>&1 || true
bad=$(grep -E ': FAILED|No such file|md5sum:' "$T/check" || true)
if [ -n "$bad" ]; then echo "MISMATCH after the copy:"; echo "$bad"; exit 1; fi
echo "all $(wc -l < "$T/sums") files match the image"

unit "cat > /tmp/fpv_run-hook.sh" < "$ROOT/br-external/board/ascent-gt/fpv_run-hook.sh"
unit "sh -s $UNIT_ROOT" < "$ROOT/boot/gt-hook-apply.sh"

if [ $REBOOT = 1 ]; then
    echo "rebooting the unit"
    unit "sync; reboot" || true
else
    echo "now reboot the unit (ssh $HOST reboot) to run it"
fi
