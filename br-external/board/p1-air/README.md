# P1 Air stock-runtime bring-up

The first P1 implementation keeps BETAFPV's Linux 4.9.38, device tree,
modules, camera libraries, ISP tuning and codec firmware together. It starts
from official P1_SKY 1.0.44, matching the hardware used for development.
It does not select the Ascent VRX kernel or NAND updater.

This is currently a **development bundle**, not a complete Kestrel Air port
or a flashable firmware release. The stock camera application remains in use.

## Build

```
./build.sh p1-air
```

Output is under `output/p1-air/images/`:

- `p1-air-stock/root.squashfs`: the unmodified vendor root filesystem,
  extracted from a hash-pinned download. It is a reference artifact, not a
  raw NAND image; do not flash it directly.
- `p1-air-stock/manifest.json`: source version and hashes.
- `p1-air-app.tar.gz`: the application overlay, containing the temporary
  login helper, password hash and source-built Open8030 AP firmware.

The vendor package handles downloading and extraction. Google Drive requires
a confirmation query, so a package download hook fills Buildroot's cache
atomically after checking SHA-256. Buildroot verifies the cached file again.
The extractor reuses the shared OTRA/UBI implementation. No vendor executable
is run during extraction, and no per-device calibration or pairing is bundled.

The Open8030 profile is generated from the pinned radio image. P1's stock
SDIO driver requires the opt-in DD block-tail envelope; it is incompatible
with the normal ar_libre framing. Keep the host transport and firmware mode
matched. Building the radio image does not load it or change the running unit.

## Root login

Like the other fpvOS air images, the default password is `root` for user
`root`. `FPVOS_AIR_ROOT_PASSWORD` overrides it at build time; an empty value
omits the override and leaves stock authentication in place.

For a temporary test, decompress the bundle on the host, copy the resulting
tar to `/tmp` on the verified P1 and unpack it into a new private directory.
Stock P1's BusyBox tar does not support `-z`. Run:

```
sh /tmp/TEST/air/root-login.sh apply /tmp/TEST/air/ssh/root.hash
```

The helper bind-mounts a RAM copy of the account database. P1 uses a password
hash in `/etc/passwd`; a stock runtime using shadow passwords is also handled.
It does not restart SSH, change USB networking or write the stock filesystem.
Keep the existing SSH session open while verifying a second login.

Restore the original account database with:

```
sh /tmp/TEST/air/root-login.sh restore
```

A reboot also discards the override. Persistent activation and public-key
provisioning are not implemented yet; `FPVOS_AIR_SSH_KEYS` is rejected rather
than silently ignored. The stock USB address remains `192.168.3.100`.

## Remaining integration

Kestrel Air currently builds for ARM32/HiSilicon and directly calls its SDK.
P1 needs an AArch64 Artosyn media backend and a compatible host radio backend.
The stock 4.9 media libraries cannot be linked into the existing musl/HiSilicon
build. No dummy Kestrel executable or HiSilicon backend is included here.

Before persistent activation, verify the application/media interface, cold
boot, USB recovery and a stock-return path. The P1 has no independent hardware
UART in the current setup. Its paired partitions alone do not prove automatic
rollback. Never install Ascent's bootloader or partition layout on this board.
