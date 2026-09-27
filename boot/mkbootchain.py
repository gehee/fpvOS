#!/usr/bin/env python3
"""Build the VRX Pro SD-card boot chain from the stock firmware's own images.

Inputs are the two stock boot images, unmodified, as extract-vendor.py puts
them under vendor/stock/:

  uboot.img  U-Boot, ARM Trusted Firmware and OP-TEE in one FIT (4 MB: two
             identical 2 MB copies)
  boot.img   the kernel FIT: device tree, LZ4 kernel, Rockchip resource
             bundle (the kernel device tree again, plus two boot logos)

Outputs, into --out, are what boot/mk-sd-image.sh writes onto the card:

  uboot-patched.bin      stock U-Boot with three board hooks stubbed out
  boot-sd3.img           the kernel FIT, re-made with an SD-card device tree
  rk3568-pro-patched.dtb the device tree for the p1 fallback (extlinux)
  Image                  the stock kernel, decompressed, for the same fallback

Nothing here is copied from Caddx beyond what the user's own download holds;
everything fpvOS changes is below, in the open.

Why the U-Boot stubs. Booting from SD, stock U-Boot stops before it has set up
power and memory (and the video decoder hangs later). Three functions are to
blame, each replaced by an immediate return:

  0x3ef4  the boot beep (buzzer on PWM fe700010)          -> return 0
  0x3fbc  rockchip_set_ethaddr (vendor storage MAC)       -> return 0
  0x67d0  vendor_storage_init (looks for it on the SD)    -> return -1

The addresses are offsets into the U-Boot image of the known stock builds;
the stock instructions there are checked before anything is written, so a
different build is refused rather than patched blind.
"""
import argparse
import hashlib
import os
import re
import struct
import subprocess
import sys
import tempfile

# SHA-256 of the U-Boot image (FIT image "uboot") of stock builds this is known
# to patch correctly. Same code, different build timestamps.
KNOWN_UBOOT = {
    "21e604ba916b603b70b1043af895c967edca9425c3bd442b37f46b1607988b05": "18.21.10 (download)",
    "0548dd678e8f91e298bc79d0098ef6464265c881c82457bab4b3b14586f39be1": "18.21.7",
}
UBOOT_STUBS = {  # offset in the U-Boot image: (stock bytes, replacement)
    0x3EF4: ("fd7bbea9200a0090", "00008052c0035fd6"),  # mov w0, #0  ; ret
    0x3FBC: ("fd7bb2a902038052", "00008052c0035fd6"),  # mov w0, #0  ; ret
    0x67D0: ("fd7bb0a9fd030091", "00008012c0035fd6"),  # mov w0, #-1 ; ret
}
BOOTARGS = ("earlycon=uart8250,mmio32,0xfe660000 console=ttyFIQ0 "
            "root=/dev/mmcblk1p2 rootfstype=ext4 rootwait rw")


def die(msg):
    sys.exit(f"mkbootchain: {msg}")


# ---- FIT (flattened device tree) -------------------------------------------

def fdt_props(b):
    """{node path: {prop: (offset of value, value bytes)}} for a flat tree."""
    magic, total, off_struct, off_strings = struct.unpack(">IIII", b[:16])
    if magic != 0xD00DFEED:
        die("not a FIT image")
    props, path, p = {}, [], off_struct
    while True:
        tok = struct.unpack(">I", b[p:p + 4])[0]
        p += 4
        if tok == 1:
            e = b.index(b"\0", p)
            path.append(b[p:e].decode())
            p = (e + 4) & ~3
            props.setdefault("/".join(path), {})
        elif tok == 2:
            path.pop()
        elif tok == 3:
            ln, no = struct.unpack(">II", b[p:p + 8])
            p += 8
            e = b.index(b"\0", off_strings + no)
            props["/".join(path)][b[off_strings + no:e].decode()] = (p, b[p:p + ln])
            p = (p + ln + 3) & ~3
        elif tok == 9:
            return total, props


def fit_image(b, name):
    """(data offset, size, hash value offset) of FIT image `name`."""
    total, props = fdt_props(b)
    node = props.get(f"/images/{name}")
    if node is None:
        die(f"FIT has no image '{name}'")
    if "data" in node:
        off, data = node["data"]
        size = len(data)
    else:
        size = struct.unpack(">I", node["data-size"][1])[0]
        if "data-position" in node:
            off = struct.unpack(">I", node["data-position"][1])[0]
        else:
            off = ((total + 3) & ~3) + struct.unpack(">I", node["data-offset"][1])[0]
    h = props.get(f"/images/{name}/hash", {}).get("value")
    return off, size, (h[0] if h else None), (h[1] if h else None)


# ---- U-Boot -----------------------------------------------------------------

def patch_uboot(img):
    if len(img) < 0x400000:
        die("uboot.img is shorter than two 2 MB copies")
    out = b""
    for copy in (0, 0x200000):
        b = bytearray(img[copy:copy + 0x200000])
        off, size, hoff, hval = fit_image(bytes(b), "uboot")
        data = bytearray(b[off:off + size])
        digest = hashlib.sha256(data).hexdigest()
        if hval is None or hashlib.sha256(data).digest() != hval:
            die("U-Boot image does not match its own hash - damaged uboot.img?")
        if digest not in KNOWN_UBOOT:
            die(f"unknown stock U-Boot build (sha256 {digest}); refusing to patch it blind")
        for at, (stock, new) in UBOOT_STUBS.items():
            if data[at:at + 8].hex() != stock:
                die(f"unexpected code at U-Boot +{at:#x}")
            data[at:at + 8] = bytes.fromhex(new)
        b[off:off + size] = data
        b[hoff:hoff + 32] = hashlib.sha256(data).digest()
        out += bytes(b)
    print(f"mkbootchain: U-Boot patched (stock {KNOWN_UBOOT[digest]})")
    return out


# ---- device tree ------------------------------------------------------------

def dts_edit(dts, sd_speed):
    """The fpvOS edits, applied to decompiled stock source."""
    def sub1(pattern, repl, text, what):
        new, n = re.subn(pattern, repl, text, count=1, flags=re.M)
        if n != 1:
            die(f"device tree: could not {what}")
        return new

    dts = sub1(r'^(\s*bootargs = )".*";$', rf'\1"{BOOTARGS}";', dts, "set /chosen bootargs")
    if sd_speed:
        # p1 fallback only: the SD card at 3.3 V high speed.
        node = re.search(r"^\t(dwmmc@fe2b0000) \{\n(.*?)^\t\};", dts, flags=re.M | re.S)
        if not node:
            die("device tree: no dwmmc@fe2b0000 (sdmmc0)")
        body = node.group(2)
        body = sub1(r"^(\s*max-frequency = )<0x[0-9a-f]+>;$", r"\1<0x2faf080>;", body,
                    "set sdmmc0 max-frequency")
        body = sub1(r"^\s*sd-uhs-sdr104;\n", "", body, "drop sd-uhs-sdr104")
        body = sub1(r"^(\s*max-frequency = <0x2faf080>;\n)", r"\1\t\tno-1-8-v;\n", body,
                    "add no-1-8-v")
        dts = dts[:node.start(2)] + body + dts[node.end(2):]
    else:
        # The live SD boot (boot-sd3.img): the board presented as itself.
        dts = sub1(r'^(\tcompatible = )"rpdzkj,pro-rk3568-v10", ("rockchip,rk3568";)$',
                   r"\1\2", dts, "set / compatible")
        dts = sub1(r'^(\tmodel = )"pro-rk3568";$', r'\1"rk3568-vrxpro";', dts, "set / model")
        dts = sub1(r'^\t\trpdzkj = "/rpdzkj_config";\n', "", dts, "drop the rpdzkj alias")
    return dts


def dtb_build(dtb, dtc, tmp, sd_speed):
    src = os.path.join(tmp, "in.dtb")
    open(src, "wb").write(dtb)
    dts = subprocess.run([dtc, "-q", "-I", "dtb", "-O", "dts", src],
                         check=True, capture_output=True, text=True).stdout
    edited = os.path.join(tmp, "out.dts")
    open(edited, "w").write(dts_edit(dts, sd_speed))
    return subprocess.run([dtc, "-q", "-I", "dts", "-O", "dtb", edited],
                          check=True, capture_output=True).stdout


# ---- Rockchip resource bundle -------------------------------------------------

def resource_replace(res, name, blob):
    """res with entry `name` replaced by `blob`, in place (it must still fit).

    Entry layout (512-byte blocks, after the RSCE header): "ENTR", name[220],
    hash[32], hash_size, data offset (blocks), data size. The hash is a SHA-1
    of the entry's data (hash_size 20). It has to be recomputed: left as the
    stock tree's, U-Boot's view of the device tree no longer matched it and
    the goggle hung during boot."""
    b = bytearray(res)
    if b[:4] != b"RSCE":
        die("resource is not an RSCE bundle")
    tbl_off, tbl_blks = b[9], b[10]
    n = struct.unpack("<I", b[12:16])[0]
    ents = []
    for i in range(n):
        e = (tbl_off + i * tbl_blks) * 512
        if b[e:e + 4] != b"ENTR":
            die("resource: bad entry table")
        ents.append((e, b[e + 4:e + 224].split(b"\0")[0].decode(),
                     *struct.unpack("<III", b[e + 256:e + 268])))
    for e, nm, hsize, off, size in ents:
        if nm != name:
            continue
        nxt = min([o for _, _, _, o, _ in ents if o > off] + [len(b) // 512])
        room = (nxt - off) * 512
        if len(blob) > room:
            die(f"resource: new {name} ({len(blob)} B) does not fit ({room} B)")
        b[off * 512:off * 512 + room] = blob + bytes(room - len(blob))
        b[e + 264:e + 268] = struct.pack("<I", len(blob))
        if hsize == 20:
            digest = hashlib.sha1(blob).digest()
        elif hsize == 32:
            digest = hashlib.sha256(blob).digest()
        elif hsize == 0:
            digest = b""
        else:
            die(f"resource: unknown hash size {hsize} for {name}")
        b[e + 224:e + 256] = digest + bytes(32 - len(digest))
        return bytes(b)
    die(f"resource has no {name}")


# ---- FIT with external data ----------------------------------------------------

def fit_build(its, files, dtc, tmp, timestamp):
    """The kernel FIT the SD boot uses, laid out like the known-good one:
    a header-only tree padded to 512 bytes, then each image's data at a
    512-aligned data-offset (from the end of the header), each with its
    SHA-256 in the header. Built with dtc alone - mkimage's host package pulls
    in gnutls, which does not build on current distributions."""
    blobs, offset, order = {}, 0, []
    def image(m):
        nonlocal offset
        name, path = m.group(1), m.group(2)
        data = files[path]
        blobs[name] = (offset, data)
        order.append(name)
        digest = hashlib.sha256(data).hexdigest()
        rest, n = re.subn(r'hash \{ algo = "sha256"; \};',
                          'hash { value = [%s]; algo = "sha256"; };' % digest, m.group(3))
        if n != 1:
            die(f"sd3.its: image '{name}' has no sha256 hash node")
        line = "\t\t%s { data-size = <%#x>; data-offset = <%#x>;%s" % (name, len(data), offset, rest)
        offset = (offset + len(data) + 511) & ~511
        return line
    src = re.sub(r'^\s*(\w+)\s*\{ data = /incbin/\("([^"]+)"\);(.*)$', image, its, flags=re.M)
    if len(order) != len(files):
        die("sd3.its: expected one /incbin/ per image")
    src = src.replace("/ {", "/ {\n\ttimestamp = <%#x>;" % timestamp, 1)
    dts = os.path.join(tmp, "fit.dts")
    open(dts, "w").write(src)
    head = subprocess.run([dtc, "-q", "-I", "dts", "-O", "dtb", "-a", "512", dts],
                          check=True, capture_output=True).stdout
    out = bytearray(head)
    for name in order:
        off, data = blobs[name]
        out += bytes(len(head) + off - len(out)) + data
    return bytes(out)


# ---- main -------------------------------------------------------------------

def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--stock", required=True, help="dir with stock uboot.img and boot.img")
    ap.add_argument("--its", required=True, help="boot/sd3.its")
    ap.add_argument("--out", required=True)
    ap.add_argument("--dtc", default="dtc")
    ap.add_argument("--lz4", default="lz4")
    a = ap.parse_args()

    uboot = open(os.path.join(a.stock, "uboot.img"), "rb").read()
    boot = open(os.path.join(a.stock, "boot.img"), "rb").read()
    os.makedirs(a.out, exist_ok=True)
    open(os.path.join(a.out, "uboot-patched.bin"), "wb").write(patch_uboot(uboot))

    with tempfile.TemporaryDirectory() as tmp:
        parts = {}
        for name in ("fdt", "kernel", "resource"):
            off, size, _, hval = fit_image(boot, name)
            data = boot[off:off + size]
            if hval is not None and hashlib.sha256(data).digest() != hval:
                die(f"boot.img: image '{name}' does not match its hash")
            parts[name] = data

        live_dtb = dtb_build(parts["fdt"], a.dtc, tmp, sd_speed=False)
        p1_dtb = dtb_build(parts["fdt"], a.dtc, tmp, sd_speed=True)
        open(os.path.join(a.out, "rk3568-pro-patched.dtb"), "wb").write(p1_dtb)

        # boot-sd3.img: the same kernel, the SD device tree in both places
        # U-Boot may take it from (the FIT and the resource bundle). The
        # stock image's own timestamp keeps the output reproducible.
        stamp = fdt_props(boot)[1].get("", {}).get("timestamp")
        fit = fit_build(open(a.its).read(), {
            "fdt-sd2.dtb": live_dtb,
            "kernel.lz4": parts["kernel"],
            "resource-sd.img": resource_replace(parts["resource"], "rk-kernel.dtb", live_dtb),
        }, a.dtc, tmp, struct.unpack(">I", stamp[1])[0] if stamp else 0)
        open(os.path.join(a.out, "boot-sd3.img"), "wb").write(fit)

        # The kernel is an LZ4 frame followed by 4 bytes of its decompressed
        # size (little-endian), for the kernel's own decompressor. The lz4
        # tool reads that trailer as a broken second frame, so it is checked
        # against the output and left off.
        k = parts["kernel"]
        want = struct.unpack("<I", k[-4:])[0]
        framed = os.path.join(tmp, "kernel-frame.lz4")
        open(framed, "wb").write(k[:-4])
        image = os.path.join(a.out, "Image")
        subprocess.run([a.lz4, "-d", "-f", "-q", framed, image], check=True)
        if os.path.getsize(image) != want:
            die(f"kernel: decompressed to {os.path.getsize(image)} B, trailer says {want}")
    print(f"mkbootchain: boot chain written to {a.out}")


if __name__ == "__main__":
    main()
