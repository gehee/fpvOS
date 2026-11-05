# P1 Air profiles

The `p1-air` stock-runtime reference keeps BETAFPV's Linux 4.9.38, device tree,
modules, camera libraries, ISP tuning and codec firmware together. It starts
from official P1_SKY 1.0.44, matching the hardware used for development.
It does not select the Ascent VRX kernel or NAND updater.

That target is a **development bundle**, not a complete Kestrel Air port
or a flashable firmware release. The stock camera application remains in use.

## Build

```
./build.sh p1-air
```

Output is under `output/p1-air/images/`:

- `p1-air-stock/manifest.json`: source version and hashes of the stock
  firmware the bundle was extracted from. The vendor root filesystem itself
  stays in `output/p1-air/build/p1-air-vendor-1.0.44/stock/`, so publishing the
  images directory does not redistribute it.
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

## Stock-runtime reference

The stock-runtime bundle remains a radio/login reference. The separate source
profile below builds Kestrel with its AArch64 Artosyn camera/encoder backend.

Before persistent activation, verify the application/media interface, cold
boot, USB recovery and a stock-return path. The P1 has no independent hardware
UART in the current setup. Its paired partitions alone do not prove automatic
rollback. Never install Ascent's bootloader or partition layout on this board.

## Source camera development

`./build.sh p1-air-source` is the separate, experimental source-kernel target.
It builds Linux 6.18, a RAM root filesystem and the SC231AI module into
`output/p1-air-source/`. The original `p1-air` target remains the stock-runtime
reference. The source target also produces a P1-specific updater and firmware
bundle; see persistent installation below.

The source DT uses P1's measured memory layout and SPL `ar-spin-table` CPU
handoff. USB gadget code is shared with Ascent VRX; identity, addresses and
MACs are board configuration. The source image provides root:root SSH at
192.168.3.103 (the Ascent VRX is .102, and its setup gives the host PC .100).
Persistent boot uses the P1 SPL directly; development can load the same
kernel and DTB into RAM through U-Boot USB. Booting a test image does not
select or flash it. Do not use the Ascent updater for P1.

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
The initial mode is HEVC at 1920x1080 and 60 fps, sent as 4 slices, with intra
refresh: a band of CTU rows sweeps the picture every 17 frames, so keyframes
come only when the receiver asks for one (Wave5 controls added by
`0016-media-wave5-intra-refresh.patch`). Slice output, other camera modes and
FC UART are not implemented yet.

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
Kestrel, radio provisioning and firmware loading start automatically.
Pairing and application settings persist in the existing `usrdata` volume of
the `usr_data` partition.

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
`radio-calibrate` helper takes only `baseband.basic.power.pwr_offset` from the
factory file: exactly four integers in Open8030's supported range of -6 through
+6. Any other key in the file is named in the log and ignored, never merged, so
a unit whose file carries more than the stock template still starts. Duplicate
keys, malformed JSON and oversized inputs are rejected. Board calibration
tables, identity, channel policy and pairing cannot be overwritten by the
factory file. Every stock `ar8030_pwr.json` seen so far is the template (only
`pwr_offset`, all zero); a real unit's own file is not in the repository.

The helper replaces the offsets in the extracted board configuration and
atomically publishes a mode-0600 file in RAM. Calibrated startup requires the
factory mount to be read-only and the firmware loader path to resolve to that
generated file. Without usable factory data (`S43factory` failed, or no valid
offsets), the P1 starts the radio anyway, as stock firmware does without its
factory file: board defaults, offsets 0, and at most
`calibration_fallback_power` (14 dBm, about 25 mW) at start-up, with a warning
on the console and in the kernel log. Kestrel's TX power setting still applies
once it runs, uncalibrated. With `calibration_fallback_power` empty, a failure
stops startup before loading SDIO, as before. A previous runtime configuration
is never reused, storage is never formatted, and generic offsets never replace
a unit's own. A running radio is left alone; applying changed calibration
requires a cold boot. VRX boards without host provisioning retain Open8030's radio-side factory
reader; the helper and JSON library are selected only where needed.

Host tests (a C compiler and Jansson development headers are required):

```sh
python3 br-external/package/ar9311-radio/tests/test_calibration.py -v
```

Pairing and user preferences use the existing `usr_data` partition, separate
from factory calibration. A verified pre-installation backup remains part of
recovery preparation. Firmware updates must preserve both factory and user data.

The source profile builds the shared Artosyn QSPI driver and mainline SPI-NAND,
UBI and UBIFS into the recovery kernel. Its device tree exposes the existing 6 MiB factory partition at offset 2 MiB,
marked read-only, and the existing 6 MiB `usr_data` partition at `0x7100000`,
writable. The partitioned master device and command-line partition overrides
are disabled. Bootloader, environment and stock rootfs banks are not exposed for writes.
The updater exposes bank-0 kernel/DTB/rootfs and the two GPT records.

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
the firmware updater preserves factory and stock bank 1.

### Persistent application settings

`S45settings` validates the stock `usr_data` partition geometry and discovers its
existing UBI volume by name: stock creates it as `usrdata`, without the underscore. It mounts UBIFS at `/persist`, creates only
`/persist/fpvos/kestrel-air`, and bind-mounts that directory at
`/var/lib/kestrel-air`. Vendor files under `lowdelay` are left intact. The existing
filesystem is reused without formatting, resizing, repartitioning or changing
its format. On a failure SSH stays available and Kestrel still starts, on
default settings in `/run/kestrel-air-settings` (RAM): changes made then are
not saved, and both the supervisor's log and the kernel log say so
(`persistent settings unavailable`). The fallback never writes to the empty
`/var/lib/kestrel-air` mountpoint, so `S45settings` can still mount the volume
afterwards (stop Kestrel first). The unit then also has no saved pairing.

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
file. Settings persist across power cycles, stock boots and firmware updates.
The NAND installer below handles firmware persistence separately.

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
to start without the radio device; without the settings mount it starts on
defaults in RAM (see above). Startup failures leave USB and SSH available. No radio reflash, system reboot or NAND
firmware write is part of recovery.

The supervisor gives each launcher, Kestrel and its AE/AWB helpers a process
group. It reaps orphaned helpers after crashes before restarting. A shared kernel
file lock excludes the standalone camera recorder and releases automatically
when the last worker exits. Stop the service before using `ar9311-camera-record`
or running `kestrel-air-run` manually.

Exited applications restart after two seconds. Each further run shorter than
60 seconds doubles the wait, up to 10 seconds; a longer run resets it. The
supervisor never gives up: in flight, video must come back whenever it can.
Normal shutdown sends TERM to the launcher and Kestrel for camera cleanup,
then terminates surviving helpers. After five seconds it escalates to KILL.
A group that still exists five seconds after that never gets a competing
camera owner: during a stop the supervisor exits (`failed-cleanup`);
after a crash it reports `stuck-cleanup`, keeps killing, and restarts once
the group is gone. This is process supervision, not a general
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

### USB modes

The source profile carries fpvOS_usb (`fpvos-usb` package). The serial port
(CDC-ACM) is there in every mode, and the updater on it changes the mode
(command 3 `normal`, `bridge` or `update`; fpvOS_usb `docs/protocol.md`):

- normal: USB Ethernet at 192.168.3.103 and SSH, as booted.
- update: the updater's clean mode, in RAM, for flashing.
- bridge: Kestrel stops and the USB network becomes the unit's AR8030, as an
  AR8030 on USB, for a host running ar_libre's `arlink.ko`. The host's
  upload is loaded into the chip over SDIO (it must be an SDIO build).
  `normal` reboots the unit back to its own firmware.

`tools/fpvos-update/client.py --board p1-air --port /dev/ttyACM0 bridge`
switches from the host. Bridge mode needs the FunctionFS gadget in the
kernel, so the stock-runtime profile has no bridge mode. Not yet run on a
unit.

### Persistent installation and USB recovery

The source profile boots fpvOS Linux 6.18 directly from NAND bank 0, using the
original SPL/U-Boot. It does not boot stock Linux or need a stock userspace hook
for normal operation or updates. The kernel embeds a small fpvOS recovery
root with USB Ethernet, SSH and the shared CDC-ACM update service.

The fixed P1_SKY 1.0.44 partition geometry is validated before writes. The
updater first selects preserved stock bank 1, writes and reads back bank-0
kernel and DTB, then updates the existing `userapp0` UBI volume with the full
`FPVOSUP1` bundle. Only a successful full readback permits GPT activation of
bank 0. GPT updates erase the nonselected copy, increment its generation,
recompute CRCs and verify the new record. Every readback that decides or
verifies a write (both GPT records, kernel0, dtb0) also checks the partition's
ECC failure count, since a read returns the data even when ECC could not
correct it. A failed GPT write is erased again and read back clean, which
leaves the previous valid selection. No formatting, resizing, repartitioning,
bootloader update, or factory write is performed. Settings remain in their
existing directory. **Keep the unit powered during installation.** A power cut
in the middle of a GPT write can leave a page ECC cannot correct, and the SPL
then does not boot at all.

What the stock 1.0.44 SPL does, from its code (the same in 2.0.5): it reads
both GPT records and boots the valid one with the higher 32-bit generation at
record byte 532 (a tie goes to `gpt0`); the reserved field is not checked. It
stops, waiting for a reset, when both records are invalid or when a record
cannot be read (an uncorrectable ECC error). Each record's second erase block
is a spare, read only once the first is marked bad, so only the first block is
written. Every load (GPT, U-Boot, kernel, DTB) skips bad blocks from the start
of the partition, as the installer writes them. That holds for the compressed
kernel the installer requires; an uncompressed uImage would be read from
another offset.

At boot, embedded recovery validates the stored bundle and checks that its
kernel/DTB match NAND before unpacking the rootfs into RAM. A clean-mode request
is consumed once. Missing, damaged or mismatched bundles remain in USB recovery
instead of starting Kestrel. Clean mode therefore uses the same source-built
kernel and requires no stock services.

The kernel entry guard arms the hardware watchdog and counts its boots in the
SPL's volatile scratch word. Recovery adopts the watchdog; a normal Linux
reboot and a power cycle clear the count. A panic or hang resets with the count
kept, and the SPL boots fpvOS again, so a crash in flight gets video back. Only
the third reset in a row without a clean reboot requests the USB boot, so a
kernel that keeps failing ends in U-Boot's USB downloader (about 4.5 minutes
when each try hangs until the 89-second watchdog). Leave the unit powered for
that: a power cycle starts the count over. This is not recovery from damaged SPL, U-Boot or a kernel that fails before
entry. It is also not A/B fpvOS: bank 1 remains the stock system. Loss of power
during installation leaves stock selected until activation completes.

`./build.sh p1-air-source` produces these files under
`output/p1-air-source/images/`:

- `kernel.img`: OTRA/uImage with LZ4-compressed guarded kernel and recovery.
- `betafpv-p1-air.dtb`: source device tree.
- `fpvos-p1-air.fwu`: kernel, board DTB and compressed root filesystem.
- `fpvos-update-p1-air`: standalone initial installer for stock clean mode.
- `fpvos-p1-air-bootstrap.sh`: one-time stock clean-mode launcher.

For initial installation, back up the device first. On the supported stock
release, copy the standalone installer to `/usrdata/fpvos-update` and launcher
to `/usrdata/fpvos-bootstrap.sh`, verify hashes and mark them executable. Refuse
to overwrite an existing clean flag or another installer. Write
`web:/usrdata/fpvos-bootstrap.sh` plus a newline to
`/usrdata/sirius-clean-system-flag`, sync, then reboot. The launcher removes its
staging files after copying the installer to RAM. This is a one-time installer,
not a persistent stock patch. Its diagnostic SSH retains stock credentials;
source recovery uses root:root, as does the default normal fpvOS profile.

Use the P1's native USB port, identified by serial `fpvos-p1-air`:

```sh
python3 tools/fpvos-update/client.py --board p1-air --port /dev/ttyACM<N> info
python3 tools/fpvos-update/client.py --board p1-air --port /dev/ttyACM<N> verify output/p1-air-source/images/fpvos-p1-air.fwu
python3 tools/fpvos-update/client.py --board p1-air --port /dev/ttyACM<N> install output/p1-air-source/images/fpvos-p1-air.fwu
```

`install` enters clean recovery, transfers and verifies the bundle, installs it,
reboots and checks the running image hash. `--no-reboot` leaves the completed
installation in recovery for inspection. Updates are unsigned development
bundles with integrity checks, without signature or version-order enforcement.

To select the preserved stock kernel, DTB and rootfs and reboot:

```sh
python3 tools/fpvos-update/client.py --board p1-air --port /dev/ttyACM<N> stock
```

Stock has a different USB identity; verify its boot separately. The custom bank
remains stored but inactive. Stock reflashing may replace bank 0 or GPT flags;
reinstall fpvOS through the initial installer afterward. It must not depend on
old hooks surviving a vendor reflash.
