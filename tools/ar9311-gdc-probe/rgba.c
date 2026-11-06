// SPDX-License-Identifier: GPL-2.0-or-later
/* Four luma passes with cached planar sources and NEON RGBA packing. */
#include "probe_abi.h"
#include <arm_neon.h>
#include <fcntl.h>
#include <math.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/ioctl.h>
#include <sys/mman.h>
#include <time.h>
#include <unistd.h>
static uint64_t ns(void) {
  struct timespec t;
  clock_gettime(CLOCK_MONOTONIC, &t);
  return (uint64_t)t.tv_sec * 1000000000 + t.tv_nsec;
}
static int compare(const void *a, const void *b) {
  uint64_t x = *(const uint64_t *)a, y = *(const uint64_t *)b;
  return (x > y) - (x < y);
}
static void fail(const char *s) {
  perror(s);
  exit(1);
}
int main(int argc, char **argv) {
  unsigned w = argc > 1 ? atoi(argv[1]) : 384,
           h = argc > 2 ? atoi(argv[2]) : 256;
  double angle = argc > 3 ? atof(argv[3]) : 5;
  unsigned count = argc > 4 ? atoi(argv[4]) : 100;
  const char *prefix = argc > 5 ? argv[5] : "rgba";
  struct gp_job j = {.sw = (w + 128 + 63) & ~63,
                     .sh = (h + 128 + 63) & ~63,
                     .dw = w,
                     .dh = (h + 63) & ~63};
  unsigned n = w * h, sn = j.sw * j.sh, dn = w * j.dh;
  unsigned copies = getenv("GDC_COPIES") ? atoi(getenv("GDC_COPIES")) : 1;
  if (!copies || copies > 2 || !w || !h || w > 1920 || h > 1024 || (w & 63) ||
      (h & 1) || j.sw > 2048 || j.sh > 1152 ||
      copies * 4 * sn + 64 > GP_Y_BYTES || copies * 4 * dn + 64 > GP_Y_BYTES ||
      !count || count > 10000 || !isfinite(angle) || fabs(angle) > 10) {
    fprintf(stderr, "invalid dimensions/angle/count\n");
    return 2;
  }
  int fd = open("/dev/gdc-probe", O_RDWR);
  if (fd < 0)
    fail("open");
  uint8_t *b = mmap(NULL, GP_BYTES, PROT_READ | PROT_WRITE, MAP_SHARED, fd, 0);
  if (b == MAP_FAILED)
    fail("mmap");
  uint64_t *times = calloc(count, sizeof(*times));
  if (!times)
    fail("times");
  uint8_t *out = malloc(copies * 4 * n), *cached = b + GP_DST_Y;
  if (!out)
    fail("malloc");
  uint8_t *input = NULL;
  if (argc > 6) {
    input = malloc(4 * n);
    if (!input)
      fail("malloc input");
    FILE *f = fopen(argv[6], "rb");
    if (!f)
      fail("input");
    if (fread(input, 1, 4 * n, f) != 4 * n) {
      fprintf(stderr, "short input\n");
      return 2;
    }
    fclose(f);
  }
  uint64_t prepare = ns();
  memset(b, 0xa5, GP_BYTES);
  memset(b, 0, 4 * sn);
  for (unsigned y = 0; y < h; y++)
    for (unsigned x = 0; x < w; x++) {
      unsigned a = 255, r = 255, g = (x / 32 & 1) ? 180 : 50,
               bl = (y / 32 & 1) ? 80 : 230;
      if (input) {
        unsigned at = 4 * (y * w + x);
        r = input[at];
        g = input[at + 1];
        bl = input[at + 2];
        a = input[at + 3];
      } else {
        double dx = x - w / 2., dy = y - h / 2., rad = fmin(w, h) * .42;
        double d = sqrt(dx * dx + dy * dy);
        a = (unsigned)fmax(0, fmin(255, (rad - d) * 64));
      }
      unsigned p = (y + 64) * j.sw + x + 64;
      /* Premultiply before interpolation to preserve antialiased transparent
       * edges. */
      b[p] = (r * a + 127) / 255;
      b[sn + p] = (g * a + 127) / 255;
      b[2 * sn + p] = (bl * a + 127) / 255;
      b[3 * sn + p] = a;
    }
  for (unsigned k = 1; k < copies; k++)
    memcpy(b + k * 4 * sn, b, 4 * sn);
  memset(b + GP_SRC_U, 128, sn / 4);
  memset(b + GP_SRC_V, 128, sn / 4);
  unsigned cols = (w + 63) / 64 + 1, rows = (j.dh + 63) / 64 + 1,
           ls = (cols + 3) & ~3;
  uint32_t *lut = (uint32_t *)(b + GP_LUT);
  double c = cos(angle * M_PI / 180), s = sin(angle * M_PI / 180);
  for (unsigned y = 0; y < rows; y++)
    for (unsigned x = 0; x < ls; x++) {
      double dx = x * 64.0 - w / 2., dy = y * 64.0 - h / 2.;
      int sx = (int)((c * dx + s * dy + w / 2. + 64) * 4),
          sy = (int)((-s * dx + c * dy + h / 2. + 64) * 4);
      lut[y * ls + x] = x < cols ? ((uint32_t)sy << 16) | (sx & 65535) : 0;
    }
  prepare = ns() - prepare;
  if (ioctl(fd, GP_INIT))
    fail("init");
  uint64_t hw = 0, packing = 0, copying = 0, wall = ns(), max = 0,
           min = UINT64_MAX;
  for (unsigned frame = 0; frame < count; frame++) {
    uint64_t start = ns();
    for (unsigned ch = 0; ch < 4 * copies; ch++) {
      j.src_offset = ch * sn;
      j.dst_offset = ch * dn;
      if (ioctl(fd, GP_RUN, &j))
        fail("run");
      hw += j.elapsed_ns;
    }
    uint64_t pstart = ns();
    copying += ns() - pstart;
    pstart = ns();
    for (unsigned k = 0; k < copies; k++)
      for (unsigned p = 0; p < n; p += 16) {
        uint8x16x4_t v;
        for (unsigned ch = 0; ch < 4; ch++)
          v.val[ch] = vld1q_u8(cached + (k * 4 + ch) * dn + p);
        vst4q_u8(out + (k * n + p) * 4, v);
      }
    packing += ns() - pstart;
    uint64_t elapsed = ns() - start;
    times[frame] = elapsed;
    if (elapsed > max)
      max = elapsed;
    if (elapsed < min)
      min = elapsed;
  }
  wall = ns() - wall;
  unsigned bad = 0, guard = 0, alpha = 0, identity_errors = 0;
  unsigned copy_errors = 0;
  for (unsigned k = 1; k < copies; k++)
    copy_errors += memcmp(out, out + k * 4 * n, 4 * n) != 0;
  for (unsigned p = 0; p < n; p++) {
    alpha += out[p * 4 + 3] > 0;
    for (unsigned ch = 0; ch < 3; ch++)
      bad += out[p * 4 + ch] > out[p * 4 + 3] + 1;
    if (angle == 0)
      for (unsigned ch = 0; ch < 4; ch++)
        identity_errors +=
            out[p * 4 + ch] != b[ch * sn + (p / w + 64) * j.sw + p % w + 64];
  }
  for (unsigned k = 0; k < 64; k++)
    guard += (b[copies * 4 * sn + k] != 0xa5) +
             (b[GP_DST_Y + copies * 4 * dn + k] != 0xa5) +
             (b[GP_SRC_U + sn / 4 + k] != 0xa5) +
             (b[GP_SRC_V + sn / 4 + k] != 0xa5) +
             (b[GP_DST_U + dn / 4 + k] != 0xa5) +
             (b[GP_DST_V + dn / 4 + k] != 0xa5);
  qsort(times, count, sizeof(*times), compare);
  unsigned late = 0;
  for (unsigned i = 0; i < count; i++)
    late += times[i] > 16666667;
  char path[512];
  snprintf(path, sizeof(path), "%s.rgba", prefix);
  FILE *f = fopen(path, "wb");
  if (!f)
    fail("output");
  fwrite(out, 1, 4 * n, f);
  fclose(f);
  snprintf(path, sizeof(path), "%s.lut", prefix);
  f = fopen(path, "wb");
  if (!f)
    fail("lut output");
  fwrite(lut, 4, ls * rows, f);
  fclose(f);
  printf("{\"width\":%u,\"height\":%u,\"angle\":%.2f,\"frames\":%u,\"copies\":%"
         "u,\"p95_ms\":%.3f,\"p99_ms\":%.3f,\"over_16_7ms\":%u,\"prepare_ms\":%"
         ".3f,\"four_pass_ms\":%.3f,\"copy_ms\":%.3f,\"pack_ms\":%.3f,\"total_"
         "mean_ms\":%.3f,\"total_min_ms\":%.3f,\"total_max_ms\":%.3f,\"alpha_"
         "pixels\":%u,\"invalid_premult_channels\":%u,\"identity_errors\":%u,"
         "\"copy_mismatches\":%u,\"guard_changes\":%u}\n",
         w, h, angle, count, copies, times[(count - 1) * 95 / 100] / 1e6,
         times[(count - 1) * 99 / 100] / 1e6, late, prepare / 1e6,
         hw / (count * 1e6), copying / (count * 1e6), packing / (count * 1e6),
         wall / (count * 1e6), min / 1e6, max / 1e6, alpha, bad,
         identity_errors, copy_errors, guard);
  free(times);
  free(input);
  free(out);
  munmap(b, GP_BYTES);
  close(fd);
  return bad || guard || identity_errors || copy_errors ? 3 : 0;
}
