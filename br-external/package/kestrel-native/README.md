# Native AR9311 receiver deployment

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

All native receivers share `S46kestrel-state-ubifs`. The board's
`/etc/default/kestrel-state` specifies the existing partition, size and volume
names: Ascent uses `fpv_data`, P1 goggles and SteadyDigital use `usr_data`.
Settings and pairing live under `/persist/fpvos/kestrel`, linked from
`/var/lib/kestrel`; SSH host keys are kept there when `/etc/dropbear` is a link.
No SD settings are imported. Existing internal settings are authoritative.
The helper never formats storage or changes vendor files. Missing storage
produces a warning and RAM-only state. Attachments it creates are detached on
stop so clean-mode flashing can require all writable UBI devices detached.
`S60kestrel-gnd` starts after SD, radio and decoder setup, and stops before SD
unmount. The shared supervisor is also used by Kestrel Air; its tests remain in
`../kestrel-air/tests/test_supervise.py`. Application logs stay in bounded RAM
files. Missing HDMI and application crashes retry without reloading SDIO.

Recording uses a writable mount at `/mnt/sd` independently of the settings
migration marker. `fpvos` and `fpvos/recordings` may be links, but only to a
directory on the card itself; one pointing elsewhere (or dangling) disables
recording rather than writing to the RAM root.
No writable SD means no recording; settings remain on internal flash. The full UI
still boots from internal flash. Card hotplug needs a storage/service restart.
Existing recordings can be migrated by moving their folder or linking it at
`/mnt/sd/fpvos/recordings` (the target on the same card); preserve all
thumbnail/telemetry sidecars.
