# AR9311 GDC hardware prototype

An opt-in diagnostic for arbitrary-angle HUD rotation on Ascent Gnd485. It is
not a production driver or part of the firmware build, and does not change the
Kestrel renderer. It was validated against the native Linux 6.18.36 kernel.

The observed vendor GDC interface takes planar Y/U/V images, not ARGB. This
prototype uses a custom coordinate map to rotate four independent luma images
(premultiplied R, G, B, and alpha), then packs them with NEON. Dummy chroma planes
are provided for every job. Register layout was recovered from the stock GDC
module and confirmed on hardware; no vendor binaries are included here.

## Build

Build in ignored `.local`, using the **same configured and built kernel tree and
toolchain as the running receiver**. `KDIR` must contain matching Module.symvers.
Set `CROSS_COMPILE` to the toolchain prefix, including its trailing dash.

```sh
mkdir -p .local/gdc-probe
cp tools/ar9311-gdc-probe/* .local/gdc-probe/
make -C .local/gdc-probe KDIR="$KDIR" CROSS_COMPILE="$CROSS_COMPILE"
```

Copy `gdc_probe.ko`, `gdc-test`, `gdc-rgba`, and `gdc-invalid` to a temporary
directory on the receiver. Run there so output images stay outside application
recordings. There is no installation or autoload step.

## Run

The module requires the `caddx,ascent-gnd485` board compatible, an unclaimed GDC
register resource, and root with CAP_SYS_RAWIO. Its default mode only reads state:

```sh
insmod ./gdc_probe.ko
cat /sys/kernel/debug/gdc-probe/state
rmmod gdc_probe
```

Enable the bounded DMA test explicitly. Cacheable pages with explicit DMA cache
synchronization are considerably faster for CPU packing than coherent mappings:

```sh
insmod ./gdc_probe.ko arm=1 cached=1
./gdc-invalid
./gdc-test 320 192 0 20 identity
./gdc-test 320 192 5 100 checkerboard
./gdc-rgba 384 256 0 20 alpha-identity
./gdc-rgba 384 256 5 100 alpha-rotation
GDC_COPIES=2 ./gdc-rgba 384 256 5 1000 two-regions
rmmod gdc_probe
```

Arguments are output width, height, angle in degrees, iteration count, and output
prefix. `gdc-rgba` optionally accepts a final input filename containing exactly
`width * height * 4` bytes of **straight RGBA**. Otherwise it creates a colored
disc with antialiased alpha edges. The output `.rgba` file is **premultiplied
RGBA**, not straight RGBA or the byte-order-native ARGB used by Kestrel. Convert
or select the appropriate image flags before displaying it. `.pgm` and `.lut`
files capture luma output and coordinate maps. All timings print as JSON.

`GDC_COPIES=2` benchmarks two independent buffer sets with identical input and
transform, including eight jobs and both packing operations. It saves the first
set's image. It is a representative two-region benchmark, not a full UI frame.

The luma test requires 64-aligned dimensions. The RGBA test accepts even logical
heights and pads the hardware output height to 64. All widths are 64-aligned.
Source padding is 64 pixels per side, with further height alignment; the kernel
rejects maps whose nodes leave the source. Some dimension/angle combinations
will therefore be rejected rather than clipped. This is intentional.

## Isolation and limitations

- Loading does not write peripheral registers. INIT requires GDC already powered,
  clocked and idle, as observed after the validated boot firmware. It returns
  EHOSTDOWN if that condition is absent; there is no untested power-up sequence.
- The successful path does not alter PLL, shared power, codec, or HDMI settings.
- A single root process uses an owned 8 MiB DMA allocation. The ioctl exposes
  validated offsets within luma slots, never caller-supplied physical addresses.
  Applications must not mutate mapped inputs/maps during a synchronous job.
- Completion is polled with a 200 ms timeout. On timeout/error, GDC gate bits
  are cleared and the module/buffers are pinned until reboot. Reset semantics
  have not been established well enough to free possibly active DMA memory.
  Do not force-unload a failed module.
- Normal unload clears DMA address registers, restores the prior interrupt mask,
  and frees the allocation. It does not stop/restart the receiver application.
- Non-aligned output heights wrote beyond the logical image in early experiments.
  This version restricts hardware dimensions to 64-pixel multiples. Source,
  destination, and chroma canaries are included in cache synchronization so
  cached reads cannot hide overwrites at the checked boundaries.
- A production driver still needs shared clock/reset ownership, interrupt-driven
  completion, recovery, managed buffers, and integration with the UI renderer.
  This root-only probe is deliberately not a stable general-purpose ABI.

## Hardware results

Identity luma and RGBA transforms were exact. Custom +5 and -5 degree maps rotated
actual Canopy wing images with valid premultiplied alpha. A bilinear CPU reference
had mean absolute channel differences below 0.5/255, but larger local differences
at sharp edges; hardware interpolation is not pixel-identical to that reference.

The initial non-cacheable mapping made packing/readback dominate execution time.
Cacheable DMA pages with explicit synchronization removed that bottleneck.
At 720p the captured wings occupied approximately 342 by 200 pixels each inside
640 by 288 region buffers. Cropping into 384 by 256 tiles was essential.

Representative results while the receiver continued live decoding and HDMI:

| Work per sample | Mean time |
| --- | ---: |
| One luma rotation, 320 by 192 | 0.55 ms |
| One luma rotation, 640 by 384 | 2.06 ms |
| One luma rotation, 1280 by 704 | 7.42 ms |
| Four passes plus synchronization/packing, cropped 384 by 256 wing | 5.5 ms |
| Four passes plus synchronization/packing, uncropped 640 by 288 wing | 10.7 ms |
| Two cropped wing copies, eight passes plus synchronization/packing | 10.91 ms |
| One larger 576 by 384 region, four passes plus synchronization/packing | 11.82 ms |

The 1,000-frame two-region run had p99 12.42 ms and maximum 16.48 ms, with no
sample above 16.67 ms. The worst sample leaves almost no headroom for final
composition. These are **prototype processing times, not measured UI
FPS**. Inputs and the angle were held constant during each timing run. Excluded
costs include HUD regeneration/source preparation, changing maps, status/other
HUD regions, UI blending, and DRM presentation. No claim of 60 FPS at 1080p is
supported by these measurements.

The next integration should cache premultiplied source planes per HUD revision,
crop each visible region, rotate around the correct screen-space pivot using
placement plus a local transform, and preserve the existing hardware video/UI
composition. Measure the complete animated frame before enabling it by default.
