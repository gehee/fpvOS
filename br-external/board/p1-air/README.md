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
`/var/lib/kestrel-air/peer.json`. The source profile starts Kestrel automatically.

The launcher shares the recorder's camera lock and supplies board tuning and
initial white-balance settings. Kestrel currently uses automatic white balance.
Kestrel runs explicitly; radio provisioning and loading run automatically.
Pairing and application settings persist in the existing `usr_data` volume.
A persistent P1 firmware installer remains separate work; this is not an installable replacement for
stock air firmware.

### Bind button and status LEDs

The source DT declares GPIO42 as an active-low, 20ms-debounced bind input.
`gpio-keys-polled` supplies `KEY_WPS_BUTTON` through an input named
`p1-air-bind`, using 20ms polling until GPIO interrupt support is available.
GPIO0/1 are LED-class outputs named `p1-air:status-0` and `p1-air:status-1`.
Kestrel accesses these standard interfaces; it does not export board GPIOs.
A press/release starts pairing; long holds do not start a firmware upgrade.
Pairing is saved in the persistent fpvOS settings directory.

Physical checks on P1 confirm output 0 is red and output 1 is green, with
active-low control. Press/release successfully pairs and saves the receiver; red lights during pairing, green blinks when disconnected, and green is
steady with red off during video. An 11.6-second continuous hold leaves Kestrel
running and triggers pairing only on release, without an upgrade or reboot.
These checks complement the software-triggered pairing and input-state tests.

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

Pairing and user preferences use the existing `usr_data` partition, separate
from factory calibration. A verified pre-installation backup remains part of
recovery preparation. Firmware updates must preserve both factory and user data.

The source profile builds the shared Artosyn QSPI driver and mainline SPI-NAND,
UBI and UBIFS as modules. Its device tree exposes the existing 6 MiB factory partition at offset 2 MiB,
marked read-only, and the existing 6 MiB `usr_data` partition at `0x7100000`,
writable. The partitioned master device and command-line partition overrides
are disabled. Bootloader and firmware banks are not exposed through this
profile's MTD interface.

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
MTD and factory files are rejected. The factory path remains read-only;
firmware installation and P1 NAND update writes remain unimplemented.

### Persistent application settings

`S45settings` validates the stock `usr_data` partition geometry and discovers its
existing UBI volume by name. It mounts UBIFS at `/persist`, creates only
`/persist/fpvos/kestrel-air`, and bind-mounts that directory at
`/var/lib/kestrel-air`. Vendor files under `lowdelay` are left intact. The existing
filesystem is reused without formatting, resizing, repartitioning or changing
its format. Failure leaves SSH available and Kestrel refuses to start without
the writable settings mount; there is no silent fallback to RAM.

Kestrel writes `settings.json` and `peer.json` there. Saves write a complete
temporary file, sync it, rename it over the previous file and sync the directory.
An interrupted save leaves the old or new complete file. An interrupted writer
can leave a temporary file; Kestrel does not read it as settings. New files use
mode 0600. The writers return an error when saving fails, including when durability
cannot be confirmed after a rename; pairing logs report failed saves.

```sh
/etc/init.d/S45settings start
/etc/init.d/S60kestrel-air start
```

Stop Kestrel with `/etc/init.d/S60kestrel-air stop` before
`/etc/init.d/S45settings stop`. The shutdown entry unmounts
the bind and underlying volume. Stock settings are not automatically imported;
fpvOS owns its separate directory. Pair once under fpvOS to populate its peer
file. Firmware still boots from RAM; settings persist across power cycles and
stock boots. This does not implement the P1 firmware updater or failed-boot
recovery.

Host storage guards: `python3 br-external/board/p1-air/tests/test_settings.py -v`.
Kestrel's `make test` includes injected save failures and a killed-writer test.

Hardware validation saved a paired receiver and a changed preference using
Kestrel's writers, then power-cycled without a global sync after the saves.
Stock Linux mounted the same volume and both files matched byte-for-byte.
A second fpvOS RAM boot loaded them automatically and resumed wireless video
without re-pairing. The test preference was restored afterward; the pairing
remains saved. Factory bytes and the vendor's user configuration were preserved.

### Autostart and supervision

The source profile starts the shared `S60kestrel-air` service after factory
calibration, radio initialization and persistent settings. The launcher refuses
to start without the radio device or required writable settings mount. Startup
failures leave USB and SSH available. No radio reflash, system reboot or NAND
firmware write is part of recovery.

The supervisor gives each launcher, Kestrel and its AE/AWB helpers a process
group. It reaps orphaned helpers after crashes before restarting. A shared kernel
file lock excludes the standalone camera recorder and releases automatically
when the last worker exits. Stop the service before using `ar9311-camera-record`
or running `kestrel-air-run` manually.

Exited applications restart after two seconds. Five consecutive runs shorter
than 60 seconds exhaust the retry budget; a longer run resets that budget.
The service then remains stopped until an explicit start/restart or next boot.
Normal shutdown sends TERM to the launcher and Kestrel for camera cleanup,
then terminates surviving helpers. After five seconds it escalates to KILL;
if the group still exists after another five seconds, recovery stops instead of
starting another camera owner. This is process supervision, not a general
kernel-hang watchdog; the encoder's existing stall and helper-exit checks still
provide application-level fault detection.

```sh
/etc/init.d/S60kestrel-air status
/etc/init.d/S60kestrel-air stop
/etc/init.d/S60kestrel-air start
/etc/init.d/S60kestrel-air restart
cat /run/kestrel-air/status
tail /run/kestrel-air/current.log
```

`current.log` and `previous.log` are each capped at 1 MiB in RAM. Shutdown stops
Kestrel before unmounting settings. The service is installed for the AR9311
backend; each board chooses whether to invoke it from init. Other air backends
retain their existing startup scripts.

Host supervision checks: `python3 br-external/package/kestrel-air/tests/test_supervise.py -v`.

Hardware checks covered cold-boot autostart, Kestrel SIGKILL during video,
an exposure-worker SIGKILL, restart cleanup, missing-storage retry exhaustion,
and clean stop during streaming. Recovered HEVC streams decoded successfully;
the receiver repeated its stream-setup exchange after application restarts.
Continuous playback across a crash has not been validated. The standalone
recorder was excluded while Kestrel owned the camera and worked after service
stop. Factory and vendor configuration remained unchanged.
