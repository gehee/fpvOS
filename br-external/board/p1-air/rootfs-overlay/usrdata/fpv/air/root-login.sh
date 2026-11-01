#!/bin/sh
# Apply the air-unit password policy over stock's read-only account database.
# P1 keeps the hash in passwd; other vendor runtimes may use shadow.
# Changes live in tmpfs and can be removed without rebooting or restarting SSH.
set -eu
umask 077
state=/tmp/fpvos-root-login

case "${1:-}" in
apply)
	[ "$#" = 2 ] || { echo "usage: $0 apply ROOT_HASH_FILE" >&2; exit 2; }
	[ "$(id -u)" = 0 ] || exit 1
	[ ! -e "$state" ] || { echo "root-login: already applied or stale state" >&2; exit 1; }
	hash=$(cat "$2")
	case "$hash" in
	  '$6$'*) ;;
	  *) echo "root-login: expected a SHA-512 crypt hash" >&2; exit 1 ;;
	esac
	case "$hash" in *:*|*'
'*) echo "root-login: malformed hash" >&2; exit 1 ;; esac
	account=/etc/passwd
	if [ "$(awk -F: '$1 == "root" {print $2}' /etc/passwd)" = x ]; then
		account=/etc/shadow
	fi
	[ "$(awk -F: '$1 == "root" {n++} END {print n+0}' "$account")" = 1 ] || exit 1
	mkdir "$state"
	cleanup() {
		# A signal can arrive just after mount succeeds. Keep recovery state
		# if unmount fails, so a later restore can still remove the override.
		if [ "$state/account" -ef "$account" ]; then
			umount "$account" || return
		fi
		rm -f "$state/account" "$state/target"
		rmdir "$state"
	}
	trap cleanup EXIT
	trap 'exit 1' HUP INT TERM
	awk -F: -v OFS=: -v h="$hash" '$1 == "root" {$2=h} {print}' "$account" > "$state/account"
	# passwd must remain readable by ordinary processes; shadow stays private.
	if [ "$account" = /etc/passwd ]; then chmod 0644 "$state/account"; fi
	printf '%s\n' "$account" > "$state/target"
	mount --bind "$state/account" "$account"
	trap - EXIT HUP INT TERM
	echo "root-login: temporary password applied"
	;;
restore)
	[ -f "$state/target" ] || exit 0
	account=$(cat "$state/target")
	case "$account" in /etc/passwd|/etc/shadow) ;; *) exit 1 ;; esac
	umount "$account"
	rm -f "$state/account" "$state/target"
	rmdir "$state"
	echo "root-login: stock account restored"
	;;
*) echo "usage: $0 {apply ROOT_HASH_FILE|restore}" >&2; exit 2 ;;
esac
