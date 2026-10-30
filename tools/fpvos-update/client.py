#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-or-later
"""fpvOS USB CDC update transport. Supports verification, firmware installation and clean-mode reconnect."""
import argparse
import fcntl
import hashlib
import json
import os
from pathlib import Path
import select
import struct
import subprocess
import termios
import time
import tty
import zlib

from boards import get_profile

HEADER = struct.Struct('<IHHHHIHHIIII')
DESTINATION = '/tmp/pc/fpvos.fwu'
VERIFY_DESTINATION = '/tmp/pc/fpvos.verify'


def packet(command, data=b'', sequence=1):
    header = bytearray(HEADER.pack(0x4152544f, 0xcdc, 1, 0, 0xabcd,
                                  command, 2, 0, len(data), sequence, 0, 0))
    struct.pack_into('<I', header, 32, zlib.crc32(header + data))
    return header + data


class Client:
    def __init__(self, fd, board, timeout=30):
        self.fd, self.timeout, self.sequence = fd, timeout, 1
        self.board = board

    def exact(self, length, deadline):
        result = bytearray()
        while len(result) < length:
            remaining = deadline - time.monotonic()
            if remaining <= 0 or not select.select([self.fd], [], [], remaining)[0]:
                raise TimeoutError('USB response timeout')
            data = os.read(self.fd, length - len(result))
            if not data:
                raise EOFError('USB disconnected')
            result.extend(data)
        return result

    def exchange(self, command, data=b''):
        sequence = self.sequence
        self.sequence += 1
        request = packet(command, data, sequence)
        deadline = time.monotonic() + self.timeout
        view = memoryview(request)
        while view:
            remaining = deadline - time.monotonic()
            if remaining <= 0 or not select.select([], [self.fd], [], remaining)[1]:
                raise TimeoutError('USB write timeout')
            sent = os.write(self.fd, view)
            if not sent:
                raise EOFError('USB disconnected')
            view = view[sent:]
        header = self.exact(36, deadline)
        fields = HEADER.unpack(header)
        if (fields[:3] != (0x4152544f, 0xcdc, 2) or fields[5] != command or
                fields[6] != 2 or fields[9] != sequence or fields[8] > 4096):
            raise ValueError('invalid/mismatched response header')
        body = self.exact(fields[8], deadline)
        blank = bytearray(header)
        struct.pack_into('<I', blank, 32, 0)
        if zlib.crc32(blank + body) != fields[-1]:
            raise ValueError('response CRC mismatch')
        return body

    def ack(self, command, data=b''):
        body = self.exchange(command, data)
        data_ack = command in (0x74, 0x75)
        if len(body) != (80 if data_ack else 68):
            raise ValueError('invalid ACK size')
        offset = 12 if data_ack else 0
        status = struct.unpack_from('<i', body, offset)[0]
        detail = body[offset+4:].split(b'\0')[0].decode(errors='replace')
        if status:
            raise ValueError(f'receiver rejected 0x{command:02x}: {detail}')
        return body

    def info(self):
        body = self.exchange(0x3c)
        if len(body) != 300:
            raise ValueError('invalid device info')
        text = lambda offset, n: body[offset:offset+n].split(b'\0')[0].decode()
        result = dict(device=text(36, 64), hardware=text(200, 32),
                      detail=text(236, 64), firmware=text(104, 64), chunk_limit=struct.unpack_from('<I', body)[0])
        if (result['device'] not in ('fpvOS updater', self.board.get('legacy_service')) or
                result['hardware'] != self.board['hardware']):
            raise ValueError('update service does not match the selected board')
        return result

    def clean(self):
        reply = self.ack(3, b'clean'.ljust(32, b'\0'))
        return reply[4:].startswith(b'rebooting into ')

    def verify(self, source, install=False, enter_clean=True):
        payload = source.read_bytes()
        if not 0 < len(payload) <= 64 * 1024 * 1024:
            raise ValueError('package size outside transport limit')
        info = self.info()
        if enter_clean and self.clean():
            raise RuntimeError('clean reboot requested; reconnect before transfer')
        self.ack(0x72)
        destination = DESTINATION if install else VERIFY_DESTINATION
        if info['device'] == self.board.get('legacy_service'):
            destination = self.board['legacy_destination'] + ('.fwu' if install else '.verify')
        metadata = struct.pack('<64sii128s128s', hashlib.md5(payload).hexdigest().encode(),
                               len(payload), 1, destination.encode(), b'host')
        self.ack(0x73, metadata)
        chunk = min(info['chunk_limit'], 1024 * 1024)
        if chunk < 1:
            raise ValueError('invalid receiver chunk limit')
        current = 0
        for offset in range(0, len(payload), chunk):
            part = payload[offset:offset+chunk]
            reply = self.ack(0x74, part)
            current += len(part)
            if struct.unpack_from('<II', reply, 4) != (current, len(payload)):
                raise ValueError('receiver byte-count mismatch')
        self.ack(0x75)
        deadline = time.monotonic() + 900
        while True:
            body = self.exchange(0x76)
            if len(body) != 72:
                raise ValueError('invalid status response')
            progress, state = struct.unpack_from('<Ii', body)
            detail = body[8:].split(b'\0')[0].decode()
            if state < 0:
                raise RuntimeError(f'update failed ({state}): {detail}')
            if state == (4 if install else 2):
                break
            if not install or time.monotonic() > deadline:
                raise TimeoutError(f'update did not complete: {detail}')
            time.sleep(0.5)
        return dict(bytes=current, sha256=hashlib.sha256(payload).hexdigest(),
                    progress=progress, state=state, detail=detail, installed=install)



def checked_port(path, board):
    path = path.resolve(strict=True)
    sysfs = Path('/sys/class/tty') / path.name / 'device'
    for parent in sysfs.resolve(strict=True).parents:
        if (parent / 'idVendor').is_file():
            identity = tuple((parent / field).read_text().strip() for field in
                             ('idVendor', 'idProduct', 'serial'))
            if identity != tuple(board['usb_identity']):
                raise ValueError(f'not the fpvOS native USB gadget: {identity}')
            break
    else:
        raise ValueError('no USB identity; physical debug UART is not supported')
    users = subprocess.run(['fuser', str(path)], capture_output=True, timeout=5)
    if users.returncode != 1 or users.stdout or users.stderr:
        raise ValueError('serial port is in use or ownership check failed')
    return path


def connect(path, board):
    path = checked_port(path, board)
    fd = os.open(path, os.O_RDWR | os.O_NOCTTY | os.O_NONBLOCK)
    try:
        fcntl.ioctl(fd, termios.TIOCEXCL)
        tty.setraw(fd)
        termios.tcflush(fd, termios.TCIOFLUSH)
    except Exception:
        os.close(fd)
        raise
    return fd, Client(fd, board)


def disconnect(fd):
    if fd is not None:
        try:
            fcntl.ioctl(fd, termios.TIOCNXCL)
        except OSError:
            pass
        os.close(fd)


def reconnect(path, board, clean=False, image_hash=None):
    deadline = time.monotonic() + 180
    last_error = 'not connected'
    while time.monotonic() < deadline:
        time.sleep(1)
        fd = None
        try:
            fd, client = connect(path, board)
            info = client.info()
            if clean and info['detail'] != 'clean RAM mode':
                raise ValueError('waiting for clean boot')
            if image_hash and info['firmware'] != image_hash:
                raise ValueError('waiting for the installed firmware image')
            return fd, client, info
        except (OSError, ValueError, TimeoutError, EOFError) as error:
            last_error = str(error)
            disconnect(fd)
    raise TimeoutError(f'receiver did not return in the expected mode: {last_error}')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--board', required=True, help='board backend, e.g. ascent-vrx')
    parser.add_argument('--port', required=True, type=Path)
    sub = parser.add_subparsers(dest='command', required=True)
    sub.add_parser('info')
    sub.add_parser('clean')
    sub.add_parser('reboot')
    sub.add_parser('verify').add_argument('package', type=Path)
    install_parser = sub.add_parser('install')
    install_parser.add_argument('package', type=Path)
    install_parser.add_argument('--no-reboot', action='store_true',
                                help='leave the completed installation in clean mode')
    args = parser.parse_args()
    board = get_profile(args.board)
    fd, client = connect(args.port, board)
    try:
        result = client.info()
        if args.command in ('clean', 'verify', 'install'):
            if client.clean():
                disconnect(fd)
                fd = None
                fd, client, result = reconnect(args.port, board, clean=True)
            else:
                result = client.info()
        if args.command in ('verify', 'install'):
            installing = args.command == 'install'
            result = client.verify(args.package, install=installing, enter_clean=False)
            if installing and not args.no_reboot:
                with args.package.open('rb') as package:
                    header = package.read(512)
                kind = struct.unpack_from('<I', header, 88)[0]
                client.ack(3, b'reboot'.ljust(32, b'\0'))
                result['reboot_requested'] = True
                disconnect(fd)
                fd = None
                if kind == 0:
                    fd, client, info = reconnect(args.port, board, image_hash=result['sha256'])
                    result['boot_verified'] = True
                else:
                    result['boot_verified'] = False
                    result['note'] = 'Vendor USB identity differs; verify the stock boot separately.'
        elif args.command == 'reboot':
            client.ack(3, b'reboot'.ljust(32, b'\0'))
            result = {'reboot_requested': True}
        print(json.dumps(result, indent=2))
    finally:
        disconnect(fd)


if __name__ == '__main__':
    main()
