#!/bin/sh
# Insert the fpvOS hook into the GT board script. stdin is not used.
#   sh gt-hook-apply.sh /usrdata
# The hook text is /tmp/fpv_run-hook.sh, copied there by ascent-deploy.sh.
set -eu
root=$1
run=$root/fpv/fpv_run_cx4861.sh
hook=/tmp/fpv_run-hook.sh
[ -f "$run" ] || { echo "no $run" >&2; exit 1; }
[ -f "$hook" ] || { echo "no $hook" >&2; exit 1; }
if grep -q 'fpvOS hook' "$run"; then
	echo "fpv_run_cx4861.sh already hooked"
	exit 0
fi
# The last boot_ar8030 is after ar_fpvhs_upgrade. The earlier ones are the
# RF probe and still have to run, or the updater never starts.
n=$(grep -n '^cd /usrdata/fpv/boot_ar8030' "$run" | tail -n 1 | cut -d: -f1)
[ -n "$n" ] || { echo "fpv_run_cx4861.sh: no boot_ar8030 line to hook before" >&2; exit 1; }
[ -e "$run.prev" ] || cp -p "$run" "$run.prev"
{ head -n $((n - 1)) "$run"; cat "$hook"; tail -n +"$n" "$run"; } > "$run.new"
mv "$run.new" "$run"
chmod 755 "$run"
echo "hooked $run"
