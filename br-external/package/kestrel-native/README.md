# Native Ascent receiver deployment

This package embeds an independently built static Kestrel runtime, including its
baked 720p/1080p UI, in the normal firmware image. Build the ground repository
with its native `ar9311` CMake target, then run `tools/package_ascent.py`. Pass the
result as `KESTREL_NATIVE_IMAGE=/absolute/path/runtime.squashfs` to Buildroot.
After replacing that file, run `kestrel-native-reinstall` before the final build.
The default Ascent profile enables this package; disable it explicitly for a
platform-only development image.

The read-only SquashFS mounts at `/opt/kestrel`. Linux must include loop devices
and SquashFS/XZ; the Ascent fragment enables them. This layout keeps images
compressed in the RAM root instead of expanding all themes/resolutions at boot.
The existing updater enforces its image and NAND-region limits unchanged.

`S46kestrel-state` selects existing writable SD storage or RAM. It preserves SSH
keys alongside receiver data without putting device-specific keys into firmware.
`S60kestrel-gnd` starts after SD, radio and decoder setup, and stops before SD
unmount. The shared supervisor is also used by Kestrel Air; its tests remain in
`../kestrel-air/tests/test_supervise.py`. Application logs stay in bounded RAM
files. Missing HDMI and application crashes retry without reloading SDIO.

No writable SD means temporary settings/pairing and no recording. The full UI
still boots from internal flash. Card hotplug needs a storage/service restart.
Existing recordings can be migrated by moving their folder or linking it at
`/mnt/sd/fpvos/recordings`; preserve all thumbnail/telemetry sidecars.
