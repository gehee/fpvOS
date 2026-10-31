#!/usr/bin/env python3
"""Build the VRX Pro SD-card boot chain from the stock firmware's own images.

Inputs are the two stock boot images, unmodified, as extract-ascent-vrx-pro-firmware.py puts
them under vendor/stock/:

  uboot.img  U-Boot, ARM Trusted Firmware and OP-TEE in one FIT (4 MB: two
             identical 2 MB copies)
  boot.img   the kernel FIT: device tree, LZ4 kernel, Rockchip resource
             bundle (the kernel device tree again, plus two boot logos)

Outputs, into --out, are what boot/mk-sd-image.sh writes onto the card:

  uboot-patched.bin      stock U-Boot with three board hooks stubbed out
  boot-sd3.img           the kernel FIT, re-made with an SD-card device tree
  rk3568-pro-patched.dtb the device tree for the p1 fallback (extlinux)
  Image                  the kernel, decompressed, for the same fallback

The kernel is the stock one unless --kernel names an Image built from source
(Buildroot's linux package): that is then LZ4-framed the way the stock kernel
is and goes into both places instead.

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

def gpu_edit(dts):
    """The GPU node as Panfrost reads it, for a kernel built from source.

    Stock names the node's interrupts GPU/MMU/JOB and its clocks clk_mali and
    clk_gpu, for Arm's kbase driver. Panfrost looks the interrupts up by the
    lower-case names and takes its second clock as "bus". kbase copes with
    both: it tries the upper-case interrupt names first, then the lower-case
    ones, and takes its clocks by index. So the renamed node serves either
    driver, and the image can boot with either.

    The frequency table also carries entries for two other chip bins
    (opp-j-*, opp-m-*), which Rockchip's code filters out by the chip's fuses.
    Panfrost reads the table generically, and opp-m-800000000 clashes with
    opp-800000000 (same frequency, different voltage), which fails the whole
    table. They are dropped, leaving the plain entries; the highest of them,
    800 MHz at 1.0 V, is also the table's maximum voltage.

    The plain entries lose their opp-supported-hw masks too. Rockchip's code
    supplies the chip's bin to match them against; Panfrost supplies none, and
    then the kernel's OPP core treats every entry that has a mask as
    unsupported - "no supported OPPs", and Panfrost fails to probe.
    """
    def sub1(pattern, repl, text, what):
        new, n = re.subn(pattern, repl, text, count=1, flags=re.M)
        if n != 1:
            die(f"device tree: could not {what}")
        return new

    node = re.search(r"^\t(gpu@fde60000) \{\n(.*?)^\t\};", dts, flags=re.M | re.S)
    if not node:
        die("device tree: no gpu@fde60000")
    body = node.group(2)
    body = sub1(r'^(\s*interrupt-names = )"GPU", "MMU", "JOB";$', r'\1"gpu", "mmu", "job";',
                body, "rename the GPU interrupts")
    body = sub1(r'^(\s*clock-names = )"clk_mali", "clk_gpu";$', r'\1"gpu", "bus";',
                body, "rename the GPU clocks")
    opp = re.search(r"^\s*operating-points-v2 = <(0x[0-9a-f]+)>;$", body, flags=re.M)
    if not opp:
        die("device tree: GPU has no operating-points-v2")
    dts = dts[:node.start(2)] + body + dts[node.end(2):]

    table = None
    for t in re.finditer(r"^\t(opp-table[\w-]*) \{\n(.*?)^\t\};", dts, flags=re.M | re.S):
        if re.search(rf"^\t\tphandle = <{opp.group(1)}>;$", t.group(2), flags=re.M):
            table = t
    if not table:
        die("device tree: no GPU opp table")
    body, n = re.subn(r"^\t\topp-[jm]-\d+ \{\n.*?^\t\t\};\n\n?", "", table.group(2),
                      flags=re.M | re.S)
    if n != 2:
        die(f"device tree: expected 2 other-bin GPU OPPs, found {n}")
    body, n = re.subn(r"^\t\t\topp-supported-hw = <[^>]*>;\n", "", body, flags=re.M)
    if n != 6:
        die(f"device tree: expected 6 GPU OPP bin masks, found {n}")
    return dts[:table.start(2)] + body + dts[table.end(2):]


def usbphy_clock_edit(dts):
    """The USB2 PHYs' 480 MHz clocks as Linux 6.10 and later name them.

    Since 6.10 the RK3568 clock driver registers a mux called "usb480m_phy"
    itself, fed by the two PHYs as "clk_usbphy0_480m" and "clk_usbphy1_480m".
    The stock (5.10) device tree still gives PHY 0's output the mux's name, so
    registering it fails with -EEXIST and the PHY - and the USB gadget port
    behind it - never probes. Rename both outputs, and parent the USB480M
    clock on the new mux rather than on PHY 0 directly.
    """
    def sub1(pattern, repl, text, what):
        new, n = re.subn(pattern, repl, text, count=1, flags=re.M)
        if n != 1:
            die(f"device tree: could not {what}")
        return new

    cru = re.search(r'^\t(clock-controller@fdd20000) \{\n(.*?)^\t\};', dts, flags=re.M | re.S)
    ph = cru and re.search(r"^\t\tphandle = <(0x[0-9a-f]+)>;$", cru.group(2), flags=re.M)
    if not ph or "rockchip,rk3568-cru" not in cru.group(2):
        die("device tree: no RK3568 CRU phandle")
    for addr, name, first in (("fe8a0000", "clk_usbphy0_480m", True),
                              ("fe8b0000", "clk_usbphy1_480m", False)):
        node = re.search(rf"^\t(usb2-phy@{addr}) \{{\n(.*?)^\t\}};", dts, flags=re.M | re.S)
        if not node:
            die(f"device tree: no usb2-phy@{addr}")
        body = node.group(2)
        if first:
            body = sub1(r'^(\t\tclock-output-names = )"usb480m_phy";$', rf'\1"{name}";', body,
                        "rename PHY 0's clock")
            body = sub1(r"^(\t\tassigned-clock-parents = )<0x[0-9a-f]+>;$",
                        rf"\1<{ph.group(1)} 0x0c>;", body,          # USB480M_PHY = 12
                        "parent USB480M on the usb480m_phy mux")
        else:
            body = sub1(r"^(\t\t#clock-cells = <0x00>;\n)", rf'\1\t\tclock-output-names = "{name}";\n',
                        body, "name PHY 1's clock")
        dts = dts[:node.start(2)] + body + dts[node.end(2):]
    return dts


def gic_noncoherent_edit(dts):
    """RK3568's GIC and ITS marked dma-noncoherent, as Linux 6.5 and later want.

    The RK3568 interconnect cannot keep the GIC's ITS tables coherent. Newer
    kernels learn that from a dma-noncoherent property on the GIC and its ITS
    (as mainline's rk356x device tree has); without it they treat the tables
    as shareable, every ITS command times out, and boot stalls for about ten
    seconds bringing up the four CPUs.
    """
    gic = re.search(r"^\t(interrupt-controller@fd400000) \{\n(.*?)^\t\};", dts, flags=re.M | re.S)
    if not gic or '"arm,gic-v3"' not in gic.group(2):
        die("device tree: no GICv3 at fd400000")
    body = gic.group(2)
    body, n = re.subn(r'^(\t\tcompatible = "arm,gic-v3";\n)', r"\1\t\tdma-noncoherent;\n", body,
                      count=1, flags=re.M)
    body, m = re.subn(r'^(\t\t\tcompatible = "arm,gic-v3-its";\n)', r"\1\t\t\tdma-noncoherent;\n",
                      body, count=1, flags=re.M)
    if n != 1 or m != 1:
        die("device tree: could not mark the GIC and its ITS dma-noncoherent")
    return dts[:gic.start(2)] + body + dts[gic.end(2):]


def vop_planes_edit(dts):
    """A second video layer for the screen: Esmart1 moved from VP1 to VP0.

    The stock tree gives VP0 (the HDMI screen) Cluster0, Esmart0 and Smart0,
    and VP1 (wired to nothing on this board) Cluster1, Esmart1 and Smart1,
    with disable-win-move pinning them there. Of VP0's, only Esmart0 takes
    linear NV12 - the decoder's output - so the picture can only ever be one
    layer. With Esmart1 on VP0 as well, kestrel shows the top and the bottom
    of the picture on layers of their own, each half put up as soon as it is
    decoded, independent of the other. VP1 keeps Cluster1 and Smart1, with
    Smart1 as its primary.
    """
    vop = re.search(r"^\t(vop@fe040000) \{\n(.*?)^\t\};", dts, flags=re.M | re.S)
    if not vop:
        die("device tree: no vop@fe040000")
    body = vop.group(2)
    for old, new, what in (
            (r"(rockchip,plane-mask = )<0x15>;", r"\1<0x1d>;", "give VP0 Esmart1"),
            (r"(rockchip,plane-mask = )<0x2a>;", r"\1<0x22>;", "take Esmart1 from VP1"),
            (r"(rockchip,primary-plane = )<0x03>;", r"\1<0x05>;", "make Smart1 VP1's primary")):
        body, n = re.subn(old, new, body, count=1)
        if n != 1:
            die(f"device tree: could not {what}")
    return dts[:vop.start(2)] + body + dts[vop.end(2):]


def kernel_version(image):
    """(major, minor) from the banner in an uncompressed arm64 Image."""
    m = re.search(rb"Linux version (\d+)\.(\d+)", open(image, "rb").read())
    return (int(m.group(1)), int(m.group(2))) if m else None


def dts_edit(dts, sd_speed, gpu=False, usbclk=False):
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
    dts = vop_planes_edit(dts)
    if gpu:
        dts = gpu_edit(dts)
    if usbclk:
        dts = usbphy_clock_edit(dts)
        dts = gic_noncoherent_edit(dts)
    return dts


def dtb_build(dtb, dtc, tmp, sd_speed, gpu=False, usbclk=False):
    src = os.path.join(tmp, "in.dtb")
    open(src, "wb").write(dtb)
    dts = subprocess.run([dtc, "-q", "-I", "dtb", "-O", "dts", src],
                         check=True, capture_output=True, text=True).stdout
    edited = os.path.join(tmp, "out.dts")
    open(edited, "w").write(dts_edit(dts, sd_speed, gpu, usbclk))
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
    ap.add_argument("--kernel", help="an arm64 Image to use instead of the stock kernel")
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

        if a.kernel:
            # Same shape as the stock kernel: one LZ4 frame, then the
            # decompressed size as 4 bytes little-endian for the kernel's own
            # decompressor.
            raw = open(a.kernel, "rb").read()
            frame = subprocess.run([a.lz4, "-9", "-c", "-q", a.kernel],
                                   check=True, capture_output=True).stdout
            parts["kernel"] = frame + struct.pack("<I", len(raw))

        # A kernel built from source may run Panfrost: rename the GPU node's
        # interrupts and clocks for it (see gpu_edit).
        gpu = bool(a.kernel)
        # And a 6.10+ kernel needs the USB2 PHY clocks renamed (usbphy_clock_edit)
        # and the GIC marked non-coherent (gic_noncoherent_edit).
        # Without a version those edits would be skipped silently, and a 6.10+
        # kernel would boot with no USB gadget and a ten-second stall.
        ver = kernel_version(a.kernel) if a.kernel else None
        if a.kernel and not ver:
            die(f"{a.kernel}: no 'Linux version' banner - is it an uncompressed arm64 Image?")
        usbclk = bool(ver and ver >= (6, 10))
        live_dtb = dtb_build(parts["fdt"], a.dtc, tmp, sd_speed=False, gpu=gpu, usbclk=usbclk)
        p1_dtb = dtb_build(parts["fdt"], a.dtc, tmp, sd_speed=True, gpu=gpu, usbclk=usbclk)
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
