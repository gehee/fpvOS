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
The source-camera route needs an AArch64 V4L2 backend once P1 capture and
encoding are validated. Reuse its ar_libre connection with the tested P1 SDIO
settings. The stock-runtime bundle remains a radio/login reference, without
a dummy Kestrel executable or a HiSilicon backend.

Before persistent activation, verify the application/media interface, cold
boot, USB recovery and a stock-return path. The P1 has no independent hardware
UART in the current setup. Its paired partitions alone do not prove automatic
rollback. Never install Ascent's bootloader or partition layout on this board.

## Source camera development

`./build.sh p1-air-source` is the separate, experimental source-kernel target.
It builds Linux 6.18, a RAM root filesystem and the SC231AI module into
`output/p1-air-source/`. The original `p1-air` target remains the stock-runtime
reference. No P1 updater or flashable image is produced by the source target.

The source DT uses P1's measured memory layout and SPL `ar-spin-table` CPU
handoff. USB gadget code is shared with Ascent VRX; identity, addresses and
MACs are board configuration. The source image provides root:root SSH at
192.168.3.100. Development uses a tested RAM handoff from stock Linux; a cold
power cycle returns to stock. This is not a bootloader recovery mechanism or
a persistent installer. Do not flash it with the Ascent updater.

### Camera pipeline

The source target builds the SC231AI sensor driver, CSI receiver, VIF, ISP,
CVISP capture and Wave5 encoder. The sensor uses standard I2C, GPIO, clock,
runtime PM and V4L2 controls. Its mode is fixed 1920x1080 at 60 fps, RAW10,
with grouped exposure and analogue/digital gain updates. Board timing, wiring
and the tuning filename live in the P1 device tree.

`p1-air-camera-firmware` extracts and verifies the SC231 tuning and P1's
low-memory codec microcode from the pinned official firmware. These remain
proprietary data inputs; vendor camera applications and media libraries are
not used by the source pipeline.

`ar9311-camera-control` builds automatic exposure from pinned source, adapts
the 478-entry P1 exposure table to the SC231AI V4L2 controls, and drives the
ISP's gain-dependent tuning. A source-built white-balance controller uses
the ISP's raw channel statistics, rejects dark/clipped or strongly coloured
zones, and gradually adjusts red/blue gains toward a robust neutral estimate.
P1 selects its measured statistics channel order through board configuration;
this order is distinct from the sensor's bus Bayer order.

After booting the development image:

```
ar9311-camera-record /tmp/short.h265 120
```

For longer recordings, stream to the host rather than filling the small RAM
filesystem. `ar9311-camera-record - 600` writes only HEVC data to stdout and
status to stderr. The wrapper discovers video nodes by name, owns its encoder
and exposure/white-balance processes, and prevents concurrent recordings. Driver-owned
scratch buffers keep idle capture DMA away from released application buffers.
Drivers stay initialized between recordings.

The underlying `ar9311-camera-test` imports camera DMA-BUFs directly into the
hardware encoder and returns each camera buffer only after encoder completion.
No CPU pixel copies or vendor media libraries are required. The default is
1080p60 HEVC, an 8 Mbit/s bitrate request and a 60-frame GOP. This is a camera
validation tool, not a Kestrel Air backend or a wireless video transmitter.

Cold-start capture, automatic exposure and hardware encoding produce
1080p video at approximately 60 fps. Validation includes 6,000-frame recordings,
recording interruption/restart, and complete camera-module unload/reload.
Receiver hardware decoding matches the host decoder byte for byte.

The VIF driver preserves its shared AXI enable/run state across restarts;
clearing those bits can leave frame interrupts running while pixel output stops.
The sensor and camera drivers still remain initialized between recordings.

`WB_MODE=auto` in `/etc/default/ar9311-camera` enables automatic white balance.
`WB_RED` and `WB_BLUE` are initial Q8 gains and anchor the neutral-selection
window. If insufficient neutral regions are available, the controller holds
its last valid gains. Set `WB_MODE=fixed` to use the configured gains directly.
Automatic gain changes are bounded and rate limited; stale statistics cause
the controller to fail and the recorder to report an error.

Automatic exposure and white balance have been exercised on the P1 in the
lit bench scene. This conservative neutral-selection algorithm is not the
vendor's AWB implementation, and is not colour-chart calibration or validation
under every illuminant. A scene dominated by a single colour may require
fixed gains. Host estimator tests run with
`python3 br-external/package/ar9311-camera-control/tests/test_awb.py`.

### Kestrel Air development

The source profile selects Kestrel's AR9311 backend and native SDIO radio
transport. It uses the same source camera drivers and DMA-BUF encoder path as
the recorder, with Kestrel owning encoded frame packetization, bitrate control,
receiver commands and AE/AWB lifecycle. No vendor media libraries are linked.
The initial mode is complete-frame HEVC at 1920x1080 and 60 fps; slice output,
other camera modes, FC UART and board buttons/LEDs are not implemented yet.

Until the backend is published and the package revision is updated, use a local
Kestrel checkout containing the AR9311 backend. After configuring the source
profile, add this to the ignored `output/p1-air-source/local.mk`:

```make
KESTREL_AIR_OVERRIDE_SRCDIR = /absolute/path/to/kestrel-air
```

Build with `./build.sh p1-air-source`. After changing Kestrel source, run
`make -C output/p1-air-source kestrel-air-rebuild all`.

Before starting the radio, provision `/lib/firmware/p1-air-radio.json` with
this unit's verified AP configuration and power calibration. The stock JSON
can contain DEV defaults that its application replaces at runtime; copying it
unchanged is insufficient. Keep per-unit files outside Git. Use matching,
validated Open8030 builds on air and receiver, with native SDIO framing.
Start the radio with `/etc/init.d/S44ar9311-radio start`, provide the paired
receiver's four-byte `bb_mac_addr_0` array in
`/var/lib/kestrel-air/peer.json`, then run `kestrel-air-run`.

The launcher shares the recorder's camera lock and supplies board tuning and
initial white-balance settings. Kestrel currently uses automatic white balance.
It runs explicitly, rather than starting an incompletely provisioned radio at
boot. Settings in this RAM image disappear on power loss. A persistent P1
installer, automatic factory calibration provisioning, and complete board
controls remain separate work; this is not an installable replacement for
stock air firmware.
