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
other camera modes and FC UART are not implemented yet.

Until the backend is published and the package revision is updated, use a local
Kestrel checkout containing the AR9311 backend. After configuring the source
profile, add this to the ignored `output/p1-air-source/local.mk`:

```make
KESTREL_AIR_OVERRIDE_SRCDIR = /absolute/path/to/kestrel-air
```

Build with `./build.sh p1-air-source`. After changing Kestrel source, run
`make -C output/p1-air-source kestrel-air-rebuild all`.

The build extracts the pinned stock radio defaults and adapts them for
Open8030 AP operation. At boot, `S43factory` mounts this unit's factory data
read-only, then `S44ar9311-radio` validates and merges its power offsets into
`/run/ar9311-radio/config.json`. The firmware loader uses that RAM file through
`/lib/firmware/p1-air-radio.json`. No private radio JSON needs to be uploaded.
Use matching, validated Open8030 builds on air and receiver, with native SDIO
framing. After fixing a provisioning failure, retry
`/etc/init.d/S44ar9311-radio start`. Provide the paired
receiver's four-byte `bb_mac_addr_0` array in
`/var/lib/kestrel-air/peer.json`, then run `kestrel-air-run`.

The launcher shares the recorder's camera lock and supplies board tuning and
initial white-balance settings. Kestrel currently uses automatic white balance.
Kestrel runs explicitly; radio provisioning and loading run automatically.
Settings in this RAM image disappear on power loss. A persistent P1
installer and physical board-control validation remain separate work; this is not an installable replacement for
stock air firmware.

### Bind button and status LEDs

The source DT declares GPIO42 as an active-low, 20ms-debounced bind input.
`gpio-keys-polled` supplies `KEY_WPS_BUTTON` through an input named
`p1-air-bind`, using 20ms polling until GPIO interrupt support is available.
GPIO0/1 are LED-class outputs named `p1-air:status-0` and `p1-air:status-1`.
Kestrel accesses these standard interfaces; it does not export board GPIOs.
A press/release starts pairing; long holds do not start a firmware upgrade.
Pairing persistence is limited by the RAM-only settings directory.

Software-triggered pairing and LED register/state checks pass. Physical button
presses and visible LED colors/polarity still require bench confirmation.

### Factory partition preservation

Both P1 profiles preserve the unit's existing `factory` partition in place.
It remains the authoritative source of factory calibration, including
`/factory/ar8030_pwr.json`; calibration is not copied from another unit or
bundled into a generic firmware image. The installer/updater must exclude
this partition from erase, format, replacement and migration operations.
Do not run the vendor startup fallback that formats an unavailable factory
filesystem.

The source profile accesses factory storage read-only. The shared optional
`radio-calibrate` helper accepts only `baseband.basic.power.pwr_offset`: exactly
four integers in Open8030's supported range of -6 through +6. The factory JSON
must contain only that nested schema; unknown fields, duplicate keys, malformed
JSON and oversized inputs are rejected. Board calibration tables, identity,
channel policy and pairing cannot be overwritten by the factory file.

The helper replaces the offsets in the extracted board configuration and
atomically publishes a mode-0600 file in RAM. Startup requires the factory
mount to be read-only and the firmware loader path to resolve to that generated
file. Failure stops startup before loading SDIO, even if a previous runtime
configuration exists. It never formats storage or substitutes generic offsets.
A running radio is left alone; applying changed calibration requires a cold
boot. VRX boards without host provisioning retain Open8030's radio-side factory
reader; the helper and JSON library are selected only where needed.

Host tests (a C compiler and Jansson development headers are required):

```sh
python3 br-external/package/ar9311-radio/tests/test_calibration.py -v
```

Pairing and user preferences belong in separate writable persistent storage.
Import existing pairing from stock user data when supported, and preserve it
across updates without writing to factory storage. A verified pre-installation
backup remains part of recovery preparation.

The source profile builds the shared Artosyn QSPI driver and mainline SPI-NAND,
UBI and UBIFS as modules. Its device tree exposes only the existing 6 MiB factory
partition at offset 2 MiB, marked read-only. The partitioned master device and
command-line partition overrides are disabled. Bootloader, firmware banks and
user data are not exposed through this profile's MTD interface.

`S43factory` runs after USB/SSH startup. It checks the factory partition name,
offset, size, erase/page geometry and write protection, attaches UBI in read-only
mode, finds the volume named `factory`, and mounts `/factory` with
`ro,nodev,nosuid,noexec`. It never formats, repairs or resizes storage. Failure
leaves USB/SSH available and reports calibration unavailable. To retry:

```sh
/etc/init.d/S43factory start
```

Host guard tests run with
`python3 br-external/board/p1-air/tests/test_factory.py`.
The hardware test compares every factory byte before/after attach and remount,
checks calibration hashes against stock and verifies that writable opens of
MTD and factory files are rejected. This is read-only storage support;
installation and P1 NAND update writes remain unimplemented.
