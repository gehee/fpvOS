#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-or-later
"""Generate deterministic, compiled-in bootstrap resources (no external archive)."""
import json
from pathlib import Path
import struct
import sys
from board_profile import read_profile


def static_aarch64(data):
    if len(data) < 64 or data[:6] != b'\x7fELF\x02\x01' or struct.unpack_from('<H', data, 18)[0] != 183:
        raise ValueError('bootstrap requires little-endian AArch64 ELF executables')
    offset = struct.unpack_from('<Q', data, 32)[0]
    size, count = struct.unpack_from('<HH', data, 54)
    if size < 56 or not count or offset + size * count > len(data):
        raise ValueError('invalid ELF program headers')
    for i in range(count):
        kind = struct.unpack_from('<I', data, offset + size * i)[0]
        if kind in (2, 3):  # PT_DYNAMIC / PT_INTERP
            raise ValueError('bootstrap executables must be statically linked')


def build(busybox, backend, output):
    profile = read_profile(backend / "profile.json")
    files = {
        'prepare.sh': ((backend / 'bootstrap-ram.sh').read_bytes(), 0o700),
        'root/bin/busybox': (busybox.read_bytes(), 0o700),
        'root/usr/libexec/fpvos-update-backend': ((backend / 'update-helper').read_bytes(), 0o755),
        'root/etc/fpvos-stock-bootstrap': ((profile['hardware'] + '\n').encode('ascii'), 0o600),
    }
    static_aarch64(files['root/bin/busybox'][0])
    # Use the packaged BusyBox for every helper command, not stock's libc/tools.
    applets = ('sh', 'awk', 'cat', 'chmod', 'cut', 'id', 'mkdir', 'mktemp', 'readlink',
               'rm', 'sha256sum', 'md5sum', 'sync', 'tr', 'reboot', 'sleep',
               'cp', 'chroot', 'mount', 'umount', 'mountpoint', 'mknod', 'ln', 'pidof', 'killall', 'seq')
    links = {f'root/bin/{name}': 'busybox' for name in applets}
    links.update({'root/usr/sbin/fpvos-update-receiver': 'fpvos-update',
                  'root/usr/sbin/ar9311-nandctl': 'fpvos-update',
                  'root/usr/libexec/fpvos-update-verify': '../sbin/fpvos-update'})
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_suffix(output.suffix + '.tmp')
    try:
        with temporary.open('w') as source:
            source.write('/* Generated bootstrap resources. */\n#include "bootstrap.h"\n')
            entries = []
            for index, (name, (data, mode)) in enumerate(sorted(files.items())):
                if not 0 < len(data) <= 4 * 1024 * 1024:
                    raise ValueError('bootstrap resource outside supported size')
                symbol = f'resource_{index}'
                source.write(f'static const unsigned char {symbol}[] = {{\n')
                for offset in range(0, len(data), 16):
                    source.write(','.join(f'0x{byte:02x}' for byte in data[offset:offset+16]) + ',\n')
                source.write('};\n')
                entries.append(f'{{{json.dumps(name)}, {symbol}, sizeof({symbol}), {mode}}}')
            source.write('const struct fpvos_bootstrap_file fpvos_bootstrap_files[] = {\n' + ',\n'.join(entries) + '\n};\n')
            source.write('const size_t fpvos_bootstrap_file_count = sizeof(fpvos_bootstrap_files)/sizeof(*fpvos_bootstrap_files);\n')
            source.write('const struct fpvos_bootstrap_link fpvos_bootstrap_links[] = {\n')
            for name, destination in sorted(links.items()):
                source.write(f'{{{json.dumps(name)}, {json.dumps(destination)}}},\n')
            source.write('};\nconst size_t fpvos_bootstrap_link_count = sizeof(fpvos_bootstrap_links)/sizeof(*fpvos_bootstrap_links);\n')
        temporary.replace(output)
    finally:
        temporary.unlink(missing_ok=True)


if __name__ == '__main__':
    build(*map(Path, sys.argv[1:4]))
