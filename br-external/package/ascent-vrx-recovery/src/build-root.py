#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-or-later
"""Build the independent, static recovery root before compiling the kernel."""
from pathlib import Path
import shutil
import struct
import subprocess
import sys

target, root, links = map(Path, sys.argv[1:4])
strip, mkpasswd = sys.argv[4:6]
overlay = Path(sys.argv[6])
source = Path(__file__).parent
if root.exists():
    shutil.rmtree(root)
for directory in ('bin', 'sbin', 'usr/bin', 'usr/sbin', 'usr/libexec', 'etc/init.d',
                  'etc/default', 'dev', 'dev/pts', 'proc', 'sys', 'run', 'tmp',
                  'root', 'newroot', 'var/run', 'etc/dropbear'):
    (root / directory).mkdir(parents=True, exist_ok=True)
for name in ('bin/busybox', 'usr/sbin/dropbear', 'usr/sbin/fpvos-update'):
    dest = root / name
    shutil.copy2(target / name, dest)
    subprocess.run([strip, '--strip-unneeded', str(dest)], check=True)
    data = dest.read_bytes()
    if data[:5] != b'\x7fELF\x02':
        raise ValueError(f'not a 64-bit ELF: {name}')
    offset = struct.unpack_from('<Q', data, 32)[0]
    entry_size, count = struct.unpack_from('<HH', data, 54)
    for i in range(count):
        if struct.unpack_from('<I', data, offset + entry_size*i)[0] == 3:
            raise ValueError(f'recovery executable requires an interpreter: {name}')
for name, destination in (('usr/sbin/fpvos-update-receiver', 'fpvos-update'),
                          ('usr/sbin/ar9311-nandctl', 'fpvos-update'),
                          ('usr/libexec/fpvos-update-verify', '../sbin/fpvos-update')):
    (root / name).symlink_to(destination)
for name in links.read_text().splitlines():
    path = root / name.lstrip('/')
    if path == root / 'bin/busybox':
        continue
    path.parent.mkdir(parents=True, exist_ok=True)
    path.symlink_to('/bin/busybox')
(root / 'usr/bin/scp').symlink_to('/usr/sbin/dropbear')
for name in ('usr/libexec/fpvos-update-backend', 'usr/sbin/fpvos-update-service',
             'etc/init.d/S50dropbear'):
    shutil.copy2(target / name, root / name)
usb = (overlay / 'etc/init.d/S40ar9311-usb').read_text()
usb = '\n'.join(line for line in usb.splitlines() if 'modprobe ' not in line) + '\n'
(root / 'etc/init.d/S40ar9311-usb').write_text(usb)
(root / 'etc/init.d/S40ar9311-usb').chmod(0o755)
(root / 'etc/passwd').write_text('root:x:0:0:root:/root:/bin/sh\n')
(root / 'etc/group').write_text('root:x:0:\n')
hash_ = subprocess.check_output([mkpasswd, '-m', 'sha-256', '-S', 'fpvosrec', 'root'], text=True).strip()
(root / 'etc/shadow').write_text(f'root:{hash_}:0:0:99999:7:::\n')
(root / 'etc/shadow').chmod(0o600)
(root / 'etc/shells').write_text('/bin/sh\n')
(root / 'etc/issue').write_text('fpvOS AR9311 NAND recovery (root:root)\n')
(root / 'etc/default/dropbear').write_text('DROPBEAR_ARGS="-p 192.168.3.102:22 -R"\n')
for name in ('init', 'etc/inittab'):
    shutil.copy2(source / Path(name).name, root / name)
(root / 'init').chmod(0o755)
# gen_initramfs accepts the root directory plus this node list. No privileged
# mknod or host root ownership is needed during the build.
(root.parent / 'nodes.list').write_text('nod /dev/console 0600 0 0 c 5 1\nnod /dev/null 0666 0 0 c 1 3\n')
