#!/usr/bin/env python3
"""Derive P1 Open8030 board data from the pinned stock radio (no execution).

A bounded interpreter follows only the vendor default-register initializer.
It accepts the instructions encountered in this exact hashed release, records
baseband stores and rejects other memory writes or unknown instructions.
"""
import argparse
import hashlib
from pathlib import Path
import re
import struct
import subprocess
import tempfile


def require(ok, message):
    if not ok:
        raise ValueError(message)


parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--radio", type=Path, required=True)
parser.add_argument("--tool-prefix", required=True)
parser.add_argument("--output", type=Path, required=True)
args = parser.parse_args()
image = args.radio.read_bytes()
require(hashlib.sha256(image).hexdigest() ==
        "fa80c8d72af34c8b25830b34124b0b08e0073b2d6d1dc7eb530cec42eaf4f12f",
        "P1 radio hash mismatch")
raw = image[17920:17920 + 266432]
require(hashlib.sha256(raw).hexdigest() ==
        "fcfdb46210f990b5b62c31c5d8c6ddcce436a62b43ec3d202b1af3a7eaf48e9c",
        "P1 radio segment hash mismatch")
with tempfile.TemporaryDirectory() as temporary:
    d = Path(temporary)
    (d / "radio.bin").write_bytes(raw)
    (d / "radio.S").write_text('.section .text\n.global _start\n_start:\n.incbin "radio.bin"\n')
    subprocess.run([args.tool_prefix + "gcc", "-march=rv32imc_xtheadbb",
                    "-mabi=ilp32", "-c", "radio.S", "-o", "radio.elf"],
                   cwd=d, check=True)
    assembly = subprocess.check_output([args.tool_prefix + "objdump", "-D", "--adjust-vma=0x204000",
                                         str(d / "radio.elf")], text=True)
ins = {}
for line in assembly.splitlines():
    m = re.match(r'\s*([0-9a-f]+):\s+([0-9a-f]+)\s+([\w.]+)\s*(.*)', line)
    if m:
        ins[int(m[1], 16)] = (len(m[2]) // 2, m[3], m[4].split('#')[0].split('<')[0].strip())

def extract(role):
    registers = dict.fromkeys(
        "zero ra sp gp tp t0 t1 t2 s0 s1 a0 a1 a2 a3 a4 a5 a6 a7 "
        "s2 s3 s4 s5 s6 s7 s8 s9 s10 s11 t3 t4 t5 t6".split(), 0)
    registers.update(sp=0x2ff000, gp=0x2450c0, a0=1, a1=role)
    memory = {0x243208 + i: value
              for i, value in enumerate(struct.pack("<I", 0x200))}
    writes = []
    pc = 0x20c10c

    def value(operand):
        return registers[operand] if operand in registers else int(operand, 0)

    def address(operand):
        match = re.fullmatch(r"(-?\d+)\((\w+)\)", operand)
        require(match, "invalid memory operand: " + operand)
        return (registers[match[2]] + int(match[1])) & 0xffffffff

    def read(location, size):
        if all(location + i in memory for i in range(size)):
            return int.from_bytes(bytes(memory[location + i] for i in range(size)), "little")
        if 0x204000 <= location and location + size <= 0x204000 + len(raw):
            return int.from_bytes(raw[location - 0x204000:location - 0x204000 + size], "little")
        raise ValueError(f"unknown load at {pc:#x}: {location:#x}, size {size}")

    for _ in range(10000):
        if pc == 0x20d3e8:
            break
        size, op, operand = ins[pc]
        operands = operand.split(",")
        next_pc = pc + size
        if op == "lui":
            registers[operands[0]] = value(operands[1]) << 12
        elif op in ("li", "mv"):
            registers[operands[0]] = value(operands[1])
        elif op == "slli":
            registers[operands[0]] = value(operands[1]) << value(operands[2])
        elif op == "ori":
            registers[operands[0]] = value(operands[1]) | value(operands[2])
        elif op == "seqz":
            registers[operands[0]] = int(value(operands[1]) == 0)
        elif op == "addi":
            registers[operands[0]] = value(operands[1]) + value(operands[2])
        elif op == "th.extu":
            high, low = value(operands[2]), value(operands[3])
            registers[operands[0]] = (value(operands[1]) >> low) & ((1 << (high - low + 1)) - 1)
        elif op in ("lw", "lbu"):
            registers[operands[0]] = read(address(operands[1]), 4 if op == "lw" else 1)
        elif op == "sw":
            location, data = address(operands[1]), value(operands[0])
            if 0xa110000 <= location < 0xa111000:
                writes.append((location - 0xa110000, data))
            elif 0x2fe000 <= location <= 0x2ff000 - 4:
                memory.update({location + i: byte for i, byte in enumerate(struct.pack("<I", data))})
            else:
                raise ValueError(f"unexpected store at {pc:#x}: {location:#x}")
        elif op == "j":
            next_pc = int(operands[0], 16)
        elif op in ("beqz", "bnez"):
            if (value(operands[0]) == 0) == (op == "beqz"):
                next_pc = int(operands[1], 16)
        elif op in ("beq", "bne"):
            if (value(operands[0]) == value(operands[1])) == (op == "beq"):
                next_pc = int(operands[2], 16)
        else:
            raise ValueError(f"unsupported instruction at {pc:#x}: {op} {operand}")
        registers = {key: data & 0xffffffff for key, data in registers.items()}
        registers["zero"] = 0
        pc = next_pc
    else:
        raise ValueError("instruction limit")
    expected = list(range(0, 0x500, 4)) + list(range(0x800, 0xe00, 4))
    require(len(writes) == 704 and [address for address, _ in writes] == expected,
            "invalid defaults")
    return writes


functions = ([(0, pin, 24 + pin) for pin in range(5)] +
             [(1, 0, 29), (1, 3, 152), (1, 4, 151), (2, 2, 74), (2, 5, 71), (2, 4, 73)] +
             [(3, 0, 40), (3, 1, 41), (3, 2, 42)] +
             [(3, pin, 123 + pin) for pin in range(4, 10)] +
             [(3, pin, 40 + pin) for pin in range(10, 13)])
pins = []
for bank, pin, function in functions:
    offset = 0x243e88 - 0x204000 + ([0, 5, 10, 16][bank] + pin) * 120
    matches = [raw[offset + i + 4] for i in range(0, 112, 8)
               if struct.unpack_from("<I", raw, offset + i)[0] == function]
    require(len(matches) == 1 and matches[0] < 16, "invalid pin function")
    # D0/D2 output, D1 input; retain the mux/drive fields.
    pad = (0x40 if pin == 1 else 0x20) if bank == 3 and pin < 3 else 0
    pins.extend([bank, pin, matches[0], pad])

def c_array(name, data):
    rows = ["    " + ",".join(f"0x{v:02x}" for v in data[i:i+16]) + ","
            for i in range(0, len(data), 16)]
    return "static const uint8_t " + name + "[] = {\n" + "\n".join(rows) + "\n};\n"


defaults = b"".join(struct.pack("<II", *w) for w in extract(0))
require(hashlib.sha256(defaults).hexdigest() ==
        "9987cdba49455ce3cfd4572ca5f3e3767ea4f653e709d0b8daf2c4333a16369d",
        "unexpected AP register defaults")
require(hashlib.sha256(bytes(pins)).hexdigest() ==
        "518584c82b390844692baa4c44261b6612dcb8e569143a196e60b05b51c9e449",
        "unexpected pin records")
keys = raw[217556:217656]
# JEDEC descriptors from the stock supported-parts table. These describe the
# radio's optional factory storage, not the AR9311 host NAND layout.
parts = [("ef6019",24),("c22539",24),("c22538",24),("c22019",24),
         ("c86719",24),("ef4019",24),("ef7019",24),("ef4016",22),
         ("ef6015",21),("ef8015",21),("205015",21),("a12815",21),
         ("c46015",21),("5e5015",21),("c84015",21),("0b4017",23),
         ("c46016",21),("c86017",23),("c46016",22)]
text = '/* Generated from hashed P1 1.0.44 board data. */\n#include "ar_boot.h"\n'
text += c_array("defaults", defaults) + c_array("pins", bytes(pins)) + c_array("fch_keys", keys)
text += "static const struct ar_flash_part flash_parts[] = {\n"
for jedec, bits in parts:
    text += "    {{" + ",".join(f"0x{v:02x}" for v in bytes.fromhex(jedec) + bytes(3)) + "}, 3, 0, " + str(1 << bits) + "},\n"
text += "};\n" + """const struct ar_boot_profile ar_boot_embedded_profile = {
    .defaults = defaults, .pins = pins, .io_domains = 2,
    .defaults_length = sizeof defaults, .pins_length = sizeof pins,
    .fch_keys = fch_keys, .keys_length = sizeof fch_keys,
    .flash_parts = flash_parts,
    .flash_part_count = sizeof flash_parts / sizeof flash_parts[0],
};
"""
args.output.write_text(text)
