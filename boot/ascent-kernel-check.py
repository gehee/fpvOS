#!/usr/bin/env python3
"""
Check a kernel built by `./build.sh air kernel` against the stock Ascent Lite/Lite+
kernel, before it goes anywhere near a unit.

    ascent-kernel-check.py [--stock STOCK.img] [--linux BUILD_DIR] [--out DIR]

Fails (exit 1) when:
  - the vermagic differs from the stock vendor modules' (they would not load);
  - a stock module imports a symbol that neither our kernel nor another stock
    module exports (it would not load either);
  - the kernel and device tree do not fit the 4 MiB kernel0/kernel1 partition.

Also reports, without failing, the exported symbols only the stock kernel has
and only ours has. Those point at config differences: the stock image carries
no config (no IKCONFIG), so this is how ours is brought close to it. The names
come from each image's __ksymtab_strings, where the linker merges a name into
the tail of a longer one (printk inside vprintk), so both sides are read the
same way and only compared with each other.

A clean result does not prove the vendor modules work: a config difference
can change a struct layout without changing any symbol or the vermagic.
"""

import argparse
import glob
import re
import subprocess
import sys
import tempfile
import zlib
from pathlib import Path

from elftools.elf.elffile import ELFFile

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(HERE))
import mkascentimg  # noqa: E402

KERNEL_PART = 4 << 20              # kernel0/kernel1 in the stock mtdparts
FIT_OVERHEAD = 4096                # FIT structure around the kernel and dtb


def die(msg):
    sys.exit(f"ascent-kernel-check: {msg}")


# ------------------------------------------------------------ stock side ----

def fit_images(fit):
    """{name: bytes} of a FIT, through dumpimage (u-boot-tools)."""
    out = {}
    with tempfile.TemporaryDirectory() as t:
        f = Path(t) / "fit"
        f.write_bytes(fit)
        listing = subprocess.run(["mkimage", "-l", str(f)], capture_output=True,
                                 text=True, check=True).stdout
        names = re.findall(r"Image (\d+) \((\S+)\)", listing)
        for idx, name in names:
            o = Path(t) / name
            subprocess.run(["dumpimage", "-T", "flat_dt", "-p", idx, "-o", str(o), str(f)],
                           capture_output=True, check=True)
            out[name] = o.read_bytes()
    return out


def zimage_payload(z):
    """Uncompressed kernel Image out of a gzip zImage."""
    i = z.find(b"\x1f\x8b\x08")
    while i >= 0:
        try:
            return zlib.decompressobj(31).decompress(z[i:])
        except zlib.error:
            i = z.find(b"\x1f\x8b\x08", i + 1)
    die("no gzip payload in the stock zImage")


def export_names(image):
    """Exported symbol names from a raw kernel Image (its __ksymtab_strings):
    the longest run of NUL-separated C identifiers."""
    best = b""
    for m in re.finditer(rb"(?:[A-Za-z_][A-Za-z0-9_.]{1,127}\x00){500,}", image):
        if len(m.group(0)) > len(best):
            best = m.group(0)
    if not best:
        die("no exported-symbol table found in a kernel image")
    return {n.decode() for n in best.split(b"\x00") if n}


def module_info(path):
    """(vermagic, undefined symbols, exported symbols) of a .ko."""
    with open(path, "rb") as f:
        e = ELFFile(f)
        vermagic = None
        for kv in e.get_section_by_name(".modinfo").data().split(b"\x00"):
            if kv.startswith(b"vermagic="):
                vermagic = kv[9:].decode().strip()
        undef = set()
        for s in e.get_section_by_name(".symtab").iter_symbols():
            if s.name and s["st_shndx"] == "SHN_UNDEF":
                undef.add(s.name)
        ks = e.get_section_by_name("__ksymtab_strings")
        exports = {n.decode() for n in ks.data().split(b"\x00") if n} if ks else set()
    return vermagic, undef, exports


# -------------------------------------------------------------- our side ----

def our_vermagic(linux):
    """vermagic of a module our build produced; failing that, as
    include/linux/vermagic.h builds it for ARM, from .config."""
    for ko in sorted(linux.rglob("*.ko")):
        return module_info(ko)[0]
    cfg = (linux / ".config").read_text()
    on = lambda k: re.search(rf"^CONFIG_{k}=y$", cfg, re.M) is not None
    rel = (linux / "include/config/kernel.release").read_text().strip()
    # __LINUX_ARM_ARCH__ is the highest architecture selected (v6K and v7 both are)
    archs = [int(n) for n in re.findall(r"^CONFIG_CPU_32v(\d+)K?=y$", cfg, re.M)]
    arch = re.match(r"(\d+)", str(max(archs))) if archs else None
    v = rel + " "
    v += "SMP " if on("SMP") else ""
    v += "preempt " if on("PREEMPT") else ""
    v += "preempt_rt " if on("PREEMPT_RT") else ""
    v += "mod_unload " if on("MODULE_UNLOAD") else ""
    v += "modversions " if on("MODVERSIONS") else ""
    v += f"ARMv{arch.group(1) if arch else '?'} "
    v += "thumb2 " if on("THUMB2_KERNEL") else ""
    v += "p2v8 " if on("ARM_PATCH_PHYS_VIRT") else ""
    return v.strip()


def our_exports(linux):
    """{symbol: providing module} from Module.symvers (vmlinux = the kernel)."""
    out = {}
    for line in (linux / "Module.symvers").read_text().splitlines():
        f = line.split("\t")
        if len(f) >= 3:
            out[f[1]] = f[2]
    return out


# ------------------------------------------------------------------ main ----

def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    stock = sorted(glob.glob(str(ROOT / "vendor/stock/air/Ascent_H_Sky_*.img")))
    ap.add_argument("--stock", default=stock[-1] if stock else None,
                    help="stock H_Sky image (default: vendor/stock/air/)")
    ap.add_argument("--linux", default=str(ROOT / "output/ascent-lite/build/linux-custom"),
                    help="our kernel build directory")
    ap.add_argument("--out", default=str(ROOT / "output/ascent-lite/kernel-check"),
                    help="where the full symbol lists go")
    a = ap.parse_args()
    if not a.stock:
        die("no stock image: run scripts/extract-ascent-vrx-pro-firmware.py")
    linux, out = Path(a.linux), Path(a.out)
    for need in (".config", "Module.symvers", "arch/arm/boot/zImage", "arch/arm/boot/Image"):
        if not (linux / need).is_file():
            die(f"{linux / need} missing: run ./build.sh air kernel")
    out.mkdir(parents=True, exist_ok=True)
    fail = []

    _, secs = mkascentimg.read_asw(a.stock)
    fit = fit_images(mkascentimg.sec_by_id(secs, 2)["data"])
    stock_image = zimage_payload(fit["linux_kernel"])

    # vendor modules, from the app volume
    with tempfile.TemporaryDirectory() as t:
        mkascentimg.extract_ubi(mkascentimg.sec_by_id(secs, 5)["data"], Path(t) / "fpv")
        mods = {str(p.relative_to(Path(t) / "fpv")): module_info(p)
                for p in sorted((Path(t) / "fpv").rglob("*.ko"))}

    # 1. vermagic
    ours = our_vermagic(linux)
    theirs = {v for v, _, _ in mods.values()}
    print(f"vermagic  ours:  {ours}")
    print(f"          stock: {' | '.join(sorted(theirs))}")
    if theirs != {ours}:
        fail.append("vermagic differs from the stock modules")

    # 2. every import of every stock module resolves
    kernel = our_exports(linux)
    by_modules = set().union(*(x for _, _, x in mods.values()))
    missing = {}
    for name, (_, undef, _) in mods.items():
        m = sorted(s for s in undef if s not in kernel and s not in by_modules)
        if m:
            missing[name] = m
    from_ours = sorted({kernel[s] for _, u, _ in mods.values() for s in u
                        if s in kernel and kernel[s] != "vmlinux"})
    print(f"modules   {len(mods)} stock modules, "
          f"{sum(len(u) for _, u, _ in mods.values())} imports")
    if from_ours:
        print(f"          some imports come from our own modules, not the kernel: {from_ours}")
    for name, m in missing.items():
        print(f"  UNRESOLVED {name}: {' '.join(m)}")
    if missing:
        fail.append(f"{len(missing)} stock modules import symbols nothing exports")

    # 3. size
    zimage = (linux / "arch/arm/boot/zImage").stat().st_size
    dtbs = sorted((linux / "arch/arm/boot/dts").glob("hi3516cv610-ascent.dtb"))
    dtb = dtbs[0].stat().st_size if dtbs else 0
    total = zimage + dtb + FIT_OVERHEAD
    print(f"size      zImage {zimage} + dtb {dtb} = about {total} of {KERNEL_PART} "
          f"({total * 100 // KERNEL_PART}%); stock zImage {len(fit['linux_kernel'])}")
    if not dtbs:
        fail.append("no hi3516cv610-ascent.dtb built")
    if total > KERNEL_PART:
        fail.append("kernel + dtb do not fit the 4 MiB kernel partition")

    # 4. exported symbols, stock vs ours (report only)
    s_exp = export_names(stock_image)
    o_exp = export_names((linux / "arch/arm/boot/Image").read_bytes())
    only_s, only_o = sorted(s_exp - o_exp), sorted(o_exp - s_exp)
    (out / "exports-only-stock.txt").write_text("\n".join(only_s) + "\n")
    (out / "exports-only-ours.txt").write_text("\n".join(only_o) + "\n")
    # (The uncompressed Image sizes are no guide: its sections are padded to
    # 1 MiB, so it barely moves when code is added.)
    print(f"exports   stock {len(s_exp)}, ours {len(o_exp)}, common {len(s_exp & o_exp)}; "
          f"only stock {len(only_s)}, only ours {len(only_o)} (lists in {out})")

    if fail:
        print("\nFAIL:\n  " + "\n  ".join(fail))
        sys.exit(1)
    print("\nOK: the stock vendor modules should load (symbols and vermagic; "
          "struct layouts are not checked)")


if __name__ == "__main__":
    main()
