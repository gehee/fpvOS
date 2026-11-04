#!/bin/sh
# Development app bundle only. The extracted stock rootfs is not repacked,
# and this script does not construct a vendor-signed update or write NAND.
set -eu
air="$TARGET_DIR/usrdata/fpv/air"
mkdir -p "$air/ssh"
chmod 0700 "$air/ssh"
password=${FPVOS_AIR_ROOT_PASSWORD-root}
rm -f "$air/ssh/root.hash" "$air/ssh/authorized_keys"
if [ -n "$password" ]; then
	# Use stdin so a build password is not exposed in process arguments.
	printf '%s\n' "$password" | openssl passwd -6 -stdin > "$air/ssh/root.hash"
	chmod 0600 "$air/ssh/root.hash"
fi
if [ -n "${FPVOS_AIR_SSH_KEYS:-}" ]; then
	echo "P1 bundle: SSH key provisioning is not integrated with stock Dropbear" >&2
	exit 1
fi
tar -C "$TARGET_DIR/usrdata/fpv" -czf "$BINARIES_DIR/p1-air-app.tar.gz" air
