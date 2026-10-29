#!/usr/bin/env python3
"""AR9311 vendor HID RAM transfer. Only operations 4/5; no flash commands.
Requires an already-running `artosyn_hid_upgrade 0` session.
Requires Python 3 and PyUSB. Restricts accesses to the kernel, DTB and
initramfs staging windows used by the Ascent Gnd485 RAM boot profile.
"""
import argparse
import hashlib
import json
from pathlib import Path
import struct
import time
import warnings
import zlib
import usb.core
import usb.util

MAGIC = bytes.fromhex('ff55ffaa4152544f')
CHUNK = 960
WINDOWS = ((0x24400000, 0x24c00000), (0x22080000, 0x220e0000), (0x26000000, 0x26800000))

def checked_range(address, length):
    if not (0 < length <= 0x800000 and any(lo <= address and address + length <= hi for lo, hi in WINDOWS)):
        raise ValueError('Transfer outside approved RAM staging windows')

def frame(kind, body):
    if kind not in (4, 5) or len(body) > CHUNK:
        raise ValueError('Unsupported operation or oversized frame')
    inner = struct.pack('<HHII', kind, 12, len(body), 0) + body
    outer = bytearray(36)
    outer[:8] = MAGIC
    struct.pack_into('<III', outer, 16, 36 + len(inner), 1, 0)
    outer[28] = 1
    return bytes(outer) + inner

def data_chunks(data):
    offset = 0
    while offset < len(data):
        n = min(CHUNK, len(data) - offset)
        # Vendor handler interprets any 16-byte body as a possible setup command.
        if n == 16:
            n = 8
        yield data[offset:offset + n]
        offset += n

def digest(data):
    return {'length': len(data), 'sha256': hashlib.sha256(data).hexdigest(), 'crc32': f'{zlib.crc32(data):08x}'}

class Transfer:
    def __enter__(self):
        matches = [d for d in usb.core.find(find_all=True, idVendor=0x1d6b, idProduct=0x0100)]
        if len(matches) != 1:
            raise RuntimeError(f'Expected exactly one receiver USB gadget, found {len(matches)}')
        self.dev = matches[0]
        if (usb.util.get_string(self.dev, self.dev.iManufacturer), usb.util.get_string(self.dev, self.dev.iProduct)) != ('U-Boot', 'USB download gadget'):
            raise RuntimeError('Unexpected USB device identity')
        interface = self.dev.get_active_configuration()[(0, 0)]
        if interface.bInterfaceClass != 3 or {(e.bEndpointAddress, e.wMaxPacketSize) for e in interface} != {(2, 1024), (129, 1024)}:
            raise RuntimeError('Unexpected interface or endpoints')
        self.detached = self.dev.is_kernel_driver_active(0)
        if self.detached:
            self.dev.detach_kernel_driver(0)
        usb.util.claim_interface(self.dev, 0)
        return self

    def __exit__(self, exc_type, *_):
        try:
            usb.util.release_interface(self.dev, 0)
            if self.detached:
                self.dev.attach_kernel_driver(0)
        except usb.core.USBError as error:
            # A cable loss must preserve the original transfer exception.
            if exc_type is None:
                raise
            warnings.warn(f'USB cleanup after transfer failure: {error}')
        finally:
            usb.util.dispose_resources(self.dev)

    def send(self, kind, body):
        packet = frame(kind, body)
        if self.dev.write(2, packet, timeout=5000) != len(packet):
            raise RuntimeError('Short USB write; stop and inspect RAM before retry')

    def read(self, address, length):
        checked_range(address, length)
        data = bytearray()
        report_at = 1024 * 1024
        while len(data) < length:
            n = min(CHUNK, length - len(data))
            self.send(5, b'ufgt' + struct.pack('<IQ', n, address + len(data)))
            packet = bytes(self.dev.read(129, 1024, timeout=5000))
            if len(packet) != 48 + n or packet[:8] != MAGIC or packet[28] != 1:
                raise RuntimeError(f'Unexpected USB read response at offset {len(data):#x}: {len(packet)} bytes')
            if struct.unpack_from('<HHII', packet, 36) != (2, 12, n, 0):
                raise RuntimeError('Unexpected response inner header')
            if struct.unpack_from('<II', packet, 20) != (1, 0):
                raise RuntimeError('Unexpected response fragmentation')
            data.extend(packet[48:])
            if len(data) >= report_at:
                print(f'read {len(data)}/{length}', flush=True)
                report_at += 1024 * 1024
        return bytes(data)

    def write(self, address, data):
        checked_range(address, len(data))
        self.send(4, b'uftr' + struct.pack('<IQ', len(data), address))
        offset = 0
        report_at = 1024 * 1024
        for chunk in data_chunks(data):
            self.send(4, chunk)
            offset += len(chunk)
            if offset >= report_at:
                print(f'wrote {offset}/{len(data)}', flush=True)
                report_at += 1024 * 1024


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('operation', choices=['read', 'write-verify'])
    parser.add_argument('address', type=lambda s: int(s, 0))
    parser.add_argument('file', type=Path)
    parser.add_argument('--length', type=lambda s: int(s, 0))
    parser.add_argument('--report', type=Path, required=True)
    args = parser.parse_args()
    if args.report.exists():
        parser.error('Report already exists')
    if args.operation == 'read':
        if args.file.exists() or args.length is None:
            parser.error('Read requires new destination and --length')
        checked_range(args.address, args.length)
    else:
        data = args.file.read_bytes()
        checked_range(args.address, len(data))
    start = time.monotonic()
    with Transfer() as transfer:
        if args.operation == 'read':
            data = transfer.read(args.address, args.length)
            with args.file.open('xb') as f:
                f.write(data)
        else:
            transfer.write(args.address, data)
            readback = transfer.read(args.address, len(data))
            if readback != data:
                mismatch = next(i for i, (a, b) in enumerate(zip(data, readback)) if a != b)
                raise RuntimeError(f'RAM readback mismatch at offset {mismatch:#x}; do not boot')
    result = dict(operation=args.operation, address=hex(args.address), file=str(args.file), **digest(data), seconds=round(time.monotonic()-start, 3), verified=True)
    args.report.write_text(json.dumps(result, indent=2)+'\n')
    print(json.dumps(result, indent=2))

if __name__ == '__main__':
    main()
