#!/usr/bin/env python3
"""
Caddx Ascent Lite/Lite+ air-unit (H_Sky) firmware images that the stock Caddx PC
tool flashes: unpack a stock ASW image, and repack it with sections of ours.

    mkascentimg.py extract STOCK.img DIR          unpack sections + both UBIFS trees
    mkascentimg.py pack --base STOCK.img --fpv DIR [--rootfs DIR] -o OUT.img
    mkascentimg.py info IMG                       header, sections, UBI parameters

STOCK.img is vendor/stock/air/Ascent_H_Sky_*.img (scripts/extract-ascent-vrx-pro-firmware.py).
Sections not replaced stay byte-identical to the base. The PC tool's receiver
(ar_fpvhs_upgrade, in the app volume) and the clean-system update boot (in the
rootfs) must survive every image, or the unit can only be reflashed over the
serial console; `pack` refuses an app volume that would lose the updater (see
lint_fpv).

ASW container (verified by disassembling ar_fpvhs_upgrade and by flashing):
  0x00 "ASW\\0"  0x04 board id  0x08/0c/10 version major/minor/patch
  0x14 5 x 12-byte sections {u8 id, u8 flags[3], u32 flash alloc, u32 file off}
  0x70 CRC32(bytes 0x80..EOF)  0x74 total size
  0x78 build tag (NOT a checksum, preserved)  0x7c const
Sections are contiguous, in table order, the last one running to EOF.
"""

import argparse
import hashlib
import os
import re
import shutil
import struct
import subprocess
import sys
import tempfile
import zlib
from pathlib import Path

HDR = 0x80
NSEC = 5
SEC_NAMES = {0: "boot", 1: "env", 2: "kernel", 4: "rootfs", 5: "fpv"}
COMPR = {0: "none", 1: "lzo", 2: "zlib", 3: "zstd"}
UBIFS_SPACE_FIXUP = 4
# from the stock env's mtdparts: rootfs0/1 16M, usrdata0/1 32M
PART_SIZE = {4: 16 << 20, 5: 32 << 20}


def die(msg):
    sys.exit(f"mkimg: {msg}")


# ---------------------------------------------------------------- ASW ----

def read_asw(path):
    d = Path(path).read_bytes()
    if d[:4] != b"ASW\0":
        die(f"{path}: not an ASW image")
    secs = []
    for i in range(NSEC):
        e = d[0x14 + 12 * i:0x20 + 12 * i]
        secs.append({"id": e[0], "flags": e[1:4], "alloc": struct.unpack("<I", e[4:8])[0],
                     "off": struct.unpack("<I", e[8:12])[0]})
    for i, s in enumerate(secs):
        end = secs[i + 1]["off"] if i + 1 < NSEC else len(d)
        s["data"] = d[s["off"]:end]
    crc, size = struct.unpack("<II", d[0x70:0x78])
    if size != len(d):
        die(f"{path}: header size {size:#x} != file size {len(d):#x}")
    if crc != zlib.crc32(d[HDR:]):
        die(f"{path}: payload CRC mismatch")
    return d[:HDR], secs


def write_asw(path, header, secs, version=None):
    h = bytearray(header)
    if version:
        struct.pack_into("<III", h, 0x08, *version)
    off = HDR
    for i, s in enumerate(secs):
        struct.pack_into("<I", h, 0x14 + 12 * i + 8, off)
        off += len(s["data"])
    payload = b"".join(s["data"] for s in secs)
    struct.pack_into("<II", h, 0x70, zlib.crc32(payload), HDR + len(payload))
    Path(path).write_bytes(bytes(h) + payload)


def version_of(header):
    return struct.unpack("<III", header[0x08:0x14])


def sec_by_id(secs, sid):
    for s in secs:
        if s["id"] == sid:
            return s
    die(f"no section id {sid}")


# ---------------------------------------------------------------- UBI ----

def ubi_params(data):
    """Everything mkfs.ubifs + ubinize need to reproduce a stock volume."""
    if data[:4] != b"UBI#":
        die("section is not UBI")
    vid_off, data_off, seq = struct.unpack(">III", data[0x10:0x1c])
    peb = data.find(b"UBI#", 4)
    p = {"peb": peb, "vid_off": vid_off, "data_off": data_off, "image_seq": seq}
    vol = sb = None
    for base in range(0, len(data), peb):
        vid = data[base + vid_off:base + vid_off + 64]
        if vid[:4] != b"UBI!":
            continue
        vol_id, lnum = struct.unpack(">II", vid[8:16])
        body = data[base + data_off:base + peb]
        if vol_id == 0x7fffefff and vol is None:          # layout volume
            rec = body[:172]
            nlen = struct.unpack(">H", rec[14:16])[0]
            vol = {"vol_type": "dynamic" if rec[12] == 1 else "static",
                   "name": rec[16:16 + nlen].decode(),
                   "autoresize": bool(rec[16 + 128] & 1),
                   "alignment": struct.unpack(">I", rec[4:8])[0]}
        elif vol_id == 0 and lnum == 0 and sb is None:
            if struct.unpack("<I", body[:4])[0] != 0x06101831 or body[20] != 6:
                die("volume 0 LEB 0 is not a UBIFS superblock")
            (key_hash, key_fmt, flags, min_io, leb, leb_cnt, max_leb_cnt) = \
                struct.unpack("<BBIIIII", body[26:48])
            log_lebs, lpt_lebs, orph_lebs, jhead, fanout, lsave, fmt = \
                struct.unpack("<IIIIIII", body[56:84])
            compr = struct.unpack("<H", body[84:86])[0]
            sb = {"min_io": min_io, "leb": leb, "max_leb_cnt": max_leb_cnt,
                  "flags": flags, "fanout": fanout, "log_lebs": log_lebs,
                  "orph_lebs": orph_lebs, "fmt": fmt, "compr": COMPR[compr],
                  "key_hash": key_hash}
    if not vol or not sb:
        die("could not find UBI volume table / UBIFS superblock")
    p.update(vol)
    p.update(sb)
    return p


def build_ubi(tree, params, work):
    """tree -> UBI image with the same geometry/naming/sequence as stock."""
    work = Path(work)
    ubifs, ubi, cfg = work / "vol.ubifs", work / "vol.ubi", work / "ubinize.cfg"
    mk = ["mkfs.ubifs", "-r", str(tree), "-o", str(ubifs),
          "-m", str(params["min_io"]), "-e", str(params["leb"]),
          "-c", str(params["max_leb_cnt"]), "-x", params["compr"],
          "-f", str(params["fanout"]), "-l", str(params["log_lebs"]),
          "-p", str(params["orph_lebs"]),
          # stock is all 0:0; build as the invoking user and squash owners
          "-U"]
    if params["flags"] & UBIFS_SPACE_FIXUP:
        mk.append("-F")
    subprocess.run(mk, check=True)
    lines = ["[ubifs]", "mode=ubi", f"image={ubifs}", "vol_id=0",
             f"vol_type={params['vol_type']}", f"vol_name={params['name']}",
             f"vol_alignment={params['alignment']}"]
    if params["autoresize"]:
        lines.append("vol_flags=autoresize")
    cfg.write_text("\n".join(lines) + "\n")
    subprocess.run(["ubinize", "-o", str(ubi), "-p", str(params["peb"]),
                    "-m", str(params["min_io"]), "-O", str(params["vid_off"]),
                    "-Q", str(params["image_seq"]), str(cfg)], check=True)
    return ubi.read_bytes()


def extract_ubi(data, out):
    """UBI section -> directory, modes intact (fakeroot satisfies -k's root check)."""
    out = Path(out)
    with tempfile.TemporaryDirectory() as t:
        src = Path(t) / "sec.bin"
        src.write_bytes(data)
        raw = Path(t) / "x"
        subprocess.run(["fakeroot", "ubireader_extract_files", "-k", "-o", str(raw), str(src)],
                       check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        vols = list(raw.glob("*/*"))
        if len(vols) != 1:
            die(f"expected one UBIFS volume, got {vols}")
        if out.exists():
            shutil.rmtree(out)
        shutil.move(str(vols[0]), str(out))


def tree_manifest(root):
    root = Path(root)
    m = {}
    for p in sorted(root.rglob("*")):
        rel = str(p.relative_to(root))
        st = p.lstat()
        if p.is_symlink():
            m[rel] = ("l", os.readlink(p))
        elif p.is_dir():
            m[rel] = ("d", oct(st.st_mode & 0o7777))
        else:
            m[rel] = ("f", oct(st.st_mode & 0o7777), st.st_size,
                      hashlib.sha256(p.read_bytes()).hexdigest())
    return m


# --------------------------------------------------------------- lint ----

# The PC tool reaches the unit only through ar_fpvhs_upgrade on the USB ACM
# gadget. It runs from this volume in normal boot (fpv_run_cx*.sh) AND in the
# clean-system boot (the stock rootfs copies these files to /tmp and runs them
# from there). Losing any of them makes the unit unflashable without serial.
RECOVERY_FILES = [
    "fpv_run.sh", "fpv_run_by_type.sh", "ar_fpvhs_upgrade", "ar_fpvhs_boardtype",
    "ar_adc_mv_read_hs", "config_serial.sh", "disable_config_serial.sh",
    "config_ether.sh", "disable_config_ether.sh", "usb_ip.sh",
    "ko_cv610_20s/ot_osal.ko", "ko_cv610_20s/ot_adc.ko",
    "ko_cv610_20s/load3516cv610/fpv_load3516cv610_20s_debug",
]
# The unit runs busybox ash; host dash rejects ash's `function f()` that the
# stock scripts use, so check with busybox when there is one, else bash.
SH_CHECK = ["busybox", "sh", "-n"] if shutil.which("busybox") else ["bash", "-n"]
EXEC_FILES = [f for f in RECOVERY_FILES if not f.endswith(".ko")]


def lint_fpv(tree):
    """tree is the volume root (it contains fpv/). Returns a list of errors."""
    fpv = Path(tree) / "fpv"
    errs = []
    for f in RECOVERY_FILES:
        p = fpv / f
        if not p.is_file():
            errs.append(f"missing recovery file fpv/{f}")
        elif f in EXEC_FILES and not os.access(p, os.X_OK):
            errs.append(f"fpv/{f} is not executable")
    for sh in list(fpv.rglob("*.sh")):
        b = sh.read_bytes()
        if b"\r\n" in b:
            errs.append(f"{sh.relative_to(tree)} has CRLF line endings")
        r = subprocess.run(SH_CHECK + [str(sh)], capture_output=True, text=True)
        if r.returncode:
            errs.append(f"{sh.relative_to(tree)}: {' '.join(SH_CHECK)}: {r.stderr.strip()}")
    # Every board script must launch the updater before it hands anything to
    # our code, so a crash or hang in air/ cannot take the updater with it.
    for run in sorted(fpv.glob("fpv_run_cx*.sh")):
        lines = [l.split("#", 1)[0] for l in run.read_text().splitlines()]
        upd = next((i for i, l in enumerate(lines)
                    if re.search(r"ar_fpvhs_upgrade\s+-c\s+1\b.*&\s*$", l)), None)
        ours = next((i for i, l in enumerate(lines) if "/air/" in l or "air/start.sh" in l), None)
        if upd is None:
            errs.append(f"{run.name}: never starts 'ar_fpvhs_upgrade -c 1 ... &'")
        elif ours is not None and ours < upd:
            errs.append(f"{run.name}: runs air/ (line {ours + 1}) before the updater (line {upd + 1})")
    return errs


# ----------------------------------------------------------- commands ----

def cmd_info(a):
    header, secs = read_asw(a.img)
    print(f"{a.img}: board {header[4]} version {'.'.join(map(str, version_of(header)))}")
    for s in secs:
        print(f"  id{s['id']} {SEC_NAMES.get(s['id'], '?'):6} off {s['off']:#9x} "
              f"len {len(s['data']):#9x} alloc {s['alloc']:#x}")
        if s["data"][:4] == b"UBI#":
            p = ubi_params(s["data"])
            print("        " + " ".join(f"{k}={v}" for k, v in p.items()))


def cmd_extract(a):
    header, secs = read_asw(a.img)
    out = Path(a.dir)
    (out / "sections").mkdir(parents=True, exist_ok=True)
    for s in secs:
        name = SEC_NAMES.get(s["id"], f"id{s['id']}")
        (out / "sections" / f"id{s['id']}_{name}.bin").write_bytes(s["data"])
    extract_ubi(sec_by_id(secs, 4)["data"], out / "rootfs")
    extract_ubi(sec_by_id(secs, 5)["data"], out / "fpv")
    print(f"extracted to {out}/ (rootfs/, fpv/, sections/)")


def cmd_pack(a):
    header, secs = read_asw(a.base)
    version = tuple(int(x) for x in a.version.split(".")) if a.version else version_of(header)
    want = "Ascent_H_Sky_%d_%d_%d.img" % version
    if Path(a.out).name != want:
        # the PC tool matches this pattern before it looks inside the file
        die(f"output must be named {want} for the PC tool (got {Path(a.out).name})")
    if header[4] != 3:
        die("base is not an H_Sky (board 3) image")

    errs = lint_fpv(a.fpv)
    if errs:
        die("app volume would break PC-tool recovery:\n  " + "\n  ".join(errs))

    replace = {5: Path(a.fpv)}
    if a.rootfs:
        replace[4] = Path(a.rootfs)
    with tempfile.TemporaryDirectory() as t:
        for sid, tree in replace.items():
            s = sec_by_id(secs, sid)
            params = ubi_params(s["data"])
            w = Path(t) / f"id{sid}"
            w.mkdir()
            s["data"] = build_ubi(tree, params, w)
            # alloc is not the partition (stock's own kernel overruns its
            # 0x300000), but every stock UBI section sits under it, so stay
            # there too; the partition itself is the hard limit.
            limit = min(PART_SIZE[sid], s["alloc"])
            if len(s["data"]) > limit:
                die(f"id{sid} is {len(s['data']):#x}, over {limit:#x}")
            # round-trip: what the unit will mount must be exactly the input tree
            back = Path(t) / f"id{sid}.check"
            extract_ubi(s["data"], back)
            if tree_manifest(back) != tree_manifest(tree):
                die(f"id{sid} did not round-trip (modes/content differ)")
            print(f"id{sid} {SEC_NAMES[sid]}: {len(s['data'])} bytes, round-trip OK")
    write_asw(a.out, header, secs, version)
    read_asw(a.out)                      # re-validate CRC/size from disk
    print(f"wrote {a.out}")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("info"); p.add_argument("img"); p.set_defaults(fn=cmd_info)
    p = sub.add_parser("extract"); p.add_argument("img"); p.add_argument("dir"); p.set_defaults(fn=cmd_extract)
    p = sub.add_parser("pack")
    p.add_argument("--base", required=True, help="stock (or stock+ssh) Ascent_H_Sky_*.img")
    p.add_argument("--fpv", required=True, help="app volume tree (contains fpv/)")
    p.add_argument("--rootfs", help="rootfs tree; default keeps the base's rootfs byte-identical")
    p.add_argument("--version", help="M.m.p to stamp in the header (default: base's)")
    p.add_argument("-o", "--out", required=True)
    p.set_defaults(fn=cmd_pack)
    a = ap.parse_args()
    a.fn(a)


if __name__ == "__main__":
    main()
