#!/bin/sh
# Initial entry, sourced by stock's consumed one-shot clean flag.
set -eu
[ "${upgrade_mode:-}" = web ]
[ "${flagfile:-}" = /usrdata/sirius-clean-system-flag ]
[ ! -e "$flagfile" ]
case "$(tr '\000' ' ' </proc/$$/cmdline)" in */etc/init.d/start_clean_system.sh*) ;; *) exit 1;; esac
chmod 700 /usrdata/fpvos-update
export FPVOS_BOOTSTRAP_HOOK=stock-clean
exec /usrdata/fpvos-update bootstrap
