# Native Ascent receiver deployment

This package embeds a static Kestrel runtime, including its baked 720p/1080p UI,
in the normal firmware image. There are two: `ascent` (Ascent VRX and Skyzone
SteadyDigital) and `p1goggle` (BETAFPV P1 goggles).

**Built from fpvOS's pins.** `scripts/native-runtime.sh BOARD` builds kestrel-gnd
at `KESTREL_PIN` with ar_libre's client library at `AR_LIBRE_VERSION`, natively
for AArch64 in `scripts/native-runtime/Dockerfile` (a Debian image pinned by
digest, its packages from snapshot.debian.org at a fixed date), and packages it
with kestrel-gnd's `tools/package_ascent.py`. `SOURCE_DATE_EPOCH` is
kestrel-gnd's commit time, so the same pins give the same file. It writes
`output/kestrel-runtime/runtime-BOARD.squashfs`, where this package looks, and
`runtime-BOARD.pins`, what it was built from. `build.sh` runs it for the board
it builds when that file is not the pinned one; it needs Docker (and QEMU's
binfmt for arm64 on another architecture). A new runtime file is installed
again without a reinstall.

**Pinned.** `runtime.hash` lists, per board, the runtime's sha256 and the
kestrel-gnd and ar_libre it was built from. The build refuses another file, and
a line naming other pins than the tree's (`KESTREL_PIN` or `AR_LIBRE_VERSION`
moved without a new runtime). After moving either pin, run the script for both
boards and put the sums it prints in `runtime.hash`.

A runtime of your own: `KESTREL_NATIVE_IMAGE=/absolute/path/runtime.squashfs
KESTREL_NATIVE_SHA256=` (empty: no pin, or its own sum). Pinned or not, the
image's sha256 is installed as `/usr/share/kestrel/runtime.sha256`, so a
firmware image records which runtime it carries.
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
