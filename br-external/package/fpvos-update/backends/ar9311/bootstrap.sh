#!/bin/sh
# Sourced by stock's consumed one-shot web: clean hook. No firmware writes here.
set -eu
[ "${upgrade_mode:-}" = web ]
[ "${flagfile:-}" = /factory/sirius-clean-system-flag ]
[ ! -e "$flagfile" ]
case "$(tr '\000' ' ' </proc/$$/cmdline)" in
    */etc/init.d/start_clean_system.sh*) ;;
    *) exit 1 ;;
esac
chmod 700 /usrdata/fpvos-update
export FPVOS_BOOTSTRAP_HOOK=stock-clean
exec /usrdata/fpvos-update bootstrap
exit 1
