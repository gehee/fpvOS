# Native Ascent receiver deployment

This package embeds an independently built static Kestrel runtime, including its
baked 720p/1080p UI, in the normal firmware image. Build the ground repository
with its native `ar9311` CMake target, then run `tools/package_ascent.py`. Pass the
result as `KESTREL_NATIVE_IMAGE=/absolute/path/runtime.squashfs` to Buildroot.
After replacing that file, run `kestrel-native-reinstall` before the final build.
Set `KESTREL_NATIVE_SHA256` (make line or environment) to the image's sha256 to
pin it: any other file then fails the build. Pinned or not, the image's sha256
is installed as `/usr/share/kestrel/runtime.sha256`, so a firmware image records
which runtime it carries. Nothing checks the runtime's board or version: build
it for the board you are building.
The default Ascent profile enables this package; disable it explicitly for a
platform-only development image.

The read-only SquashFS mounts at `/opt/kestrel`. Linux must include loop devices
and SquashFS/XZ; the Ascent fragment enables them. This layout keeps images
compressed in the RAM root instead of expanding all themes/resolutions at boot.
The existing updater enforces its image and NAND-region limits unchanged.

`/var/lib/kestrel` holds settings and pairing. On the Ascent VRX,
`S46kestrel-state` links it to existing writable SD storage or RAM and keeps SSH
keys alongside, without putting device-specific keys into firmware; on the
SteadyDigital it links it to the stock `usr_data` UBIFS (RAM without it); on the
P1 goggles it is a plain directory in the RAM root. If it is not a writable
directory when the receiver starts (a card removed since boot), `run` uses
`/run/kestrel-state` for that start and says so.
`S60kestrel-gnd` starts after SD, radio and decoder setup, and stops before SD
unmount. The shared supervisor is also used by Kestrel Air; its tests remain in
`../kestrel-air/tests/test_supervise.py`. Application logs stay in bounded RAM
files. Missing HDMI and application crashes retry without reloading SDIO.

Recording uses a writable mount at `/mnt/sd` independently of the settings
migration marker. `fpvos` and `fpvos/recordings` may be links, but only to a
directory on the card itself; one pointing elsewhere (or dangling) disables
recording rather than writing to the RAM root.
No writable SD means temporary settings/pairing and no recording. The full UI
still boots from internal flash. Card hotplug needs a storage/service restart.
Existing recordings can be migrated by moving their folder or linking it at
`/mnt/sd/fpvos/recordings` (the target on the same card); preserve all
thumbnail/telemetry sidecars.
