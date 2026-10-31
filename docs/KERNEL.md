# The kernel

fpvOS builds its kernel from source. It used to boot the stock kernel out of
the user's own firmware; that kernel is Forlinx's build of Rockchip's 5.10
tree, and its source was never published.

## Where it comes from

| | |
|---|---|
| Tree | Rockchip `develop-6.12`, [rockchip-linux/kernel](https://github.com/rockchip-linux/kernel) |
| Commit | `470f9dccbdc4` (2026-06-25), Linux 6.12.69. The tarball is checked against `br-external/board/ascent-vrx-pro/linux.hash` (`external.mk`): Buildroot itself skips the check for a kernel that is not its own latest |
| Config | `br-external/board/ascent-vrx-pro/linux-5.10.198-stock.config`, read out of the stock kernel image (`CONFIG_IKCONFIG`), carried forward by `olddefconfig`, plus `linux.fragment` |
| Patches | `br-external/board/ascent-vrx-pro/linux-patches/` (below) |
| Device tree | the stock one as `boot/mkbootchain.py` has always made it, plus the edits below |

Rockchip's 6.12 tree keeps the vendor drivers the goggle depends on - VOP2
display with writeback, the MPP video decoder and encoders, RGA, the RK817
PMIC, SCMI clocks - under the same device-tree bindings as 5.10, so the stock
device tree needs only the few edits below.

The stock config carries forward nearly whole; `linux.fragment` then:

- turns off what stock built as modules but never shipped (TV, radio and SDR
  tuners, Broadcom WiFi) and the camera interface, which the device tree
  disables;
- builds Panfrost as a module and leaves Arm's kbase driver out (see GPU);
- adds the mainline `rtl8xxxu` WiFi driver;
- turns the SoC's OTP back on: stock's `ROCKCHIP_OTP`, renamed
  `NVMEM_ROCKCHIP_OTP` since, so the carried-forward config lost it. The
  thermal sensor's trim, the per-chip CPU/GPU/DDR voltage selection and the
  CPU serial (`ROCKCHIP_CPUINFO`) all read from it;
- builds in the board driver (below);
- turns off `-Werror` (6.12's default; several Rockchip drivers and the AR8030
  driver warn under GCC 14), the ITE IT6161 bridge driver, which no longer
  builds on 6.12 and is not on this board, and HDMI-CEC, which crashes 6.12's
  dw-hdmi at boot.

## Patches

| Patch | Why |
|---|---|
| `0001-drm-rockchip-dw_hdmi-no-external-PHY-in-late_register` | RK3568 drives HDMI with the PHY inside the DesignWare controller, so there is no external PHY, and `late_register` dereferenced it unconditionally: a panic while registering the display |
| `0002-misc-rpdzkj-board` | the board driver: see below |
| `0003-video-rockchip-mpp-rkvdec2-stream-mode` | the decoder starts a picture on its first slice and takes the rest as it arrives: see Stream decode |
| `0004-wifi-rtl8xxxu-keep-the-group-key-when-a-station-leaves` | the onboard WiFi as an access point: a phone leaving took the group key with it, and the others lost their broadcast traffic |
| `0005-wifi-rtl8xxxu-hold-the-frames-of-a-dozing-station-in-AP-mode` | a phone in power save (most of them, most of the time) gets its frames held until it wakes, instead of dropped |

## Stream decode

Over the radio a picture comes in slices, the second a good part of a frame
after the first. Patch 0003 lets the RK3568's rkvdec2 start on the first slice
and go on with each next one as it arrives (`MPP_CMD_STREAM_APPEND`), and
tells user space when the first slice's rows are decoded (`MPP_STREAM_WAIT`).
The MPP side is `rockchip-mpp/0002-h265d-decode-a-picture-as-its-slices-arrive`
(`MPP_PACKET_FLAG_STREAM_START`, `MPP_DEC_SET_STREAM_APPEND`,
`MPP_DEC_GET_STREAM_TOP`; the stream buffer is sized for a whole key picture),
with `0001-h265d-refuse-a-slice-whose-PPS-names-a-missing-SPS` (a damaged
stream no longer reaches the decoder with parameter sets it does not have) and
`0003-h265d-stream-each-appended-part-on-a-page-of-its-own` (each appended
part on its own page, so the hardware never reads across a boundary).

- `rk_vcodec.rkvdec2_stream` (default 1, read at probe) turns the RK3568's
  link mode off, which a paused picture cannot work with: every decode runs
  one task at a time. Turning it back on means `rk_vcodec.rkvdec2_stream=0`
  on the kernel command line, which `mkbootchain.py` fixes - a new image.
  kestrel can stop streaming at run time without that (below).
- `rk_vcodec.rkvdec2_stream_wait_ms` (default 400, writable): how long a
  picture waits for its next part before it is ended with what it has. It
  is also kept under the task's own 500 ms timeout from its start.
- `rk_vcodec.rkvdec2_stream_stall_ms` (default 50, writable, 0 off): the
  decoder's watchdog in software, which a streamed picture runs without. A
  decoder that works on the data it has this long without an interrupt is
  taken for hung and reset ("taken for hung" in dmesg) instead of holding
  the video until the task's 500 ms timeout.
- MPP: `h265d_stream=0` in the environment turns streaming off,
  `h265d_stream_debug=1` logs it (to syslog).
- kestrel-gnd: `stream_decode: 0`, `early_present: 0` and `video_halves: 0` in
  `/etc/kestrel/kestrel-gnd.yaml` turn each part off for good;
  `/tmp/kestrel-stream-off`, `/tmp/kestrel-early-off` and
  `/tmp/kestrel-split-off` do it until the next reboot.

## The board driver

The goggle's device tree has three nodes for drivers that exist only in the
vendor kernel, which was never published: `rp_power` and `rp_gpio` set the
board's fixed GPIO lines at boot, and `fan_gpio_control` runs the fan.
`drivers/misc/rpdzkj-board.c` (patch 0002) binds the same nodes and does what
the vendor code in the stock kernel does with them, read out of the stock
kernel binary:

| Line | Pin | Set to |
|---|---|---|
| `usb_pwr` | GPIO0_A6 | high |
| `hub_rst` | GPIO0_B0 | high |
| `sd_pwren` | GPIO0_A5 | low (active low) |
| `otg_mode` | GPIO1_A4 | low (active low) |
| `spk_en` | GPIO1_B1 | high |
| `spk_mute` | GPIO1_B2 | low (active low) |
| `led` | GPIO0_D6 | blinking, 1 Hz |
| `gpio3b5`, `gpio3a7` | GPIO3_B5, GPIO3_A7 | high |
| fan | GPIO3_B6 | high from 60 C (`soc-thermal`), off 5 C below after at least 10 s |

The fan is polled every second rather than bound to the thermal zone as a
cooling device: the zone's `power_allocator` governor only drives devices with
a power model, so it would never switch a GPIO fan. If the zone cannot be
read, the fan runs.

## How it boots

`fpvos-bootchain` passes the built `Image` to `boot/mkbootchain.py --kernel`,
which LZ4-frames it exactly as the stock kernel is framed and puts it in the
SD card's FIT (p3) and the p1 fallback. U-Boot and the resource image are
unchanged. Every image gets one device-tree edit, whatever its kernel:

- Esmart1 moved from video port 1 (wired to nothing on this board) to video
  port 0, the HDMI screen (`vop_planes_edit`: VP0 plane-mask 0x15 -> 0x1d,
  VP1 0x2a -> 0x22 with Smart1 as its primary). The screen then has two
  windows that take the decoder's NV12, and kestrel shows the top and the
  rest of a picture on one each, each as soon as it is decoded. kestrel
  puts its OSD on a window that cannot show video.

And three more for a kernel built from source:

- the GPU node for Panfrost (`gpu_edit`, see GPU);
- the USB2 PHYs' 480 MHz clocks renamed as Linux 6.10 and later register them
  (`usbphy_clock_edit`) - without it PHY 0, and the USB gadget port behind it,
  never probe;
- the GIC and its ITS marked `dma-noncoherent` (`gic_noncoherent_edit`) -
  without it every ITS command times out and boot stalls for about ten
  seconds.

The last two depend on the kernel's version, read from the `Image`'s banner;
`mkbootchain.py` refuses an `Image` it cannot read the version of.

## Kernel modules

| Module | Source |
|---|---|
| `arlink.ko` (AR8030 radio) | fpvOS's own driver (package `ar-libre`), built against this kernel, with its client library in place of Artosyn's daemon and library. kbuild installs it under `updates/`; `bb_only.sh` loads it with `modprobe` |
| `rtl8xxxu.ko` (onboard WiFi, an RTL8188FTV) | in-tree, with access-point mode for the RTL8188F; firmware from `linux-firmware` (`rtlwifi/rtl8188fufw.bin`, with its licence next to it). `fpvos-wifi` loads it |
| `panfrost.ko` | in-tree, see GPU |

The stock binary modules in `vendor/rootfs` (Artosyn's `artosyn_drv.ko`,
`RTL8189FU.ko`, the unused IMU driver) only load into a kernel binary-compatible
with the stock 5.10 one. `post-build.sh` leaves out every vendor module built
for another kernel release than the image's.

## GPU

The Mali-G52 runs on Panfrost: `panfrost.ko` from the kernel tree, and Mesa's
Gallium panfrost driver for EGL, GLES and GBM in `/usr/lib`.
`/etc/init.d/S09gpu` loads the module before kestrel starts. Arm's kbase
driver and the stock `libmali` are not in the image.

Mesa is built without LLVM (`br-external/external.mk`). Panfrost's shader
compiler is Mesa's own, and the OpenCL-C shaders Mesa precompiles are built on
the host by `host-mesa3d`. Buildroot still installs LLVM, Clang, libclc and the
SPIR-V tools into the target for that precompiler, so `post-build.sh` removes
them (about 220 MB) and fails the build if anything left still links them.

The device tree's GPU node is edited for Panfrost (`boot/mkbootchain.py`,
`gpu_edit`): lower-case interrupt names, clocks named `gpu` and `bus`, the
frequency table's entries for other chip bins dropped, and the remaining
entries' chip-bin masks removed (without a bin to match them against, the
kernel treats masked entries as unsupported).
