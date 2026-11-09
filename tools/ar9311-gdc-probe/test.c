// SPDX-License-Identifier: GPL-2.0-or-later
#include "probe_abi.h"
#include <errno.h>
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
static void fail(const char *s) {
  perror(s);
  exit(1);
}
static unsigned pattern(unsigned x, unsigned y) {
  return ((x / 32 + y / 32) & 1) ? 220 : 32;
}
int main(int argc, char **argv) {
  unsigned w = argc > 1 ? atoi(argv[1]) : 320,
           h = argc > 2 ? atoi(argv[2]) : 192;
  double angle = argc > 3 ? atof(argv[3]) : 0;
  unsigned count = argc > 4 ? atoi(argv[4]) : 1;
  const char *prefix = argc > 5 ? argv[5] : "gdc";
  struct gp_job j = {
      .sw = (w + 128 + 63) & ~63, .sh = (h + 128 + 1) & ~1, .dw = w, .dh = h};
  if (!w || !h || w > 1920 || h > 1024 || (w & 63) || (h & 63) || j.sw > 2048 ||
      j.sh > 1152 || !count || count > 10000 || !isfinite(angle) ||
      fabs(angle) > 10) {
    fprintf(stderr, "invalid dimensions/angle/count\n");
    return 2;
  }
  int fd = open("/dev/gdc-probe", O_RDWR);
  if (fd < 0)
    fail("open");
  uint8_t *b = mmap(NULL, GP_BYTES, PROT_READ | PROT_WRITE, MAP_SHARED, fd, 0);
  if (b == MAP_FAILED)
    fail("mmap");
  memset(b, 0xa5, GP_BYTES);
  for (unsigned y = 0; y < j.sh; y++)
    for (unsigned x = 0; x < j.sw; x++)
      b[y * j.sw + x] = pattern(x, y);
  memset(b + GP_SRC_U, 96, j.sw * j.sh / 4);
  memset(b + GP_SRC_V, 160, j.sw * j.sh / 4);
  unsigned cols = (w + 63) / 64 + 1, rows = (h + 63) / 64 + 1,
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
  if (ioctl(fd, GP_INIT))
    fail("init");
  uint64_t sum = 0, min = UINT64_MAX, max = 0, wall = ns();
  for (unsigned i = 0; i < count; i++) {
    if (ioctl(fd, GP_RUN, &j)) {
      fprintf(stderr, "job failed: state=%x irq=%x elapsed=%llu ns\n", j.state,
              j.irq, (unsigned long long)j.elapsed_ns);
      fail("run");
    }
    sum += j.elapsed_ns;
    if (j.elapsed_ns < min)
      min = j.elapsed_ns;
    if (j.elapsed_ns > max)
      max = j.elapsed_ns;
  }
  wall = ns() - wall;
  unsigned same = 0, changed = 0, err = 0;
  for (unsigned y = 0; y < h; y++)
    for (unsigned x = 0; x < w; x++) {
      unsigned v = b[GP_DST_Y + y * w + x];
      same += (v == pattern(x + 64, y + 64));
      changed += (v != 0xa5);
      if (angle == 0)
        err += abs((int)v - (int)pattern(x + 64, y + 64));
    }
  unsigned guard = 0;
  const unsigned off[] = {GP_SRC_Y, GP_SRC_U, GP_SRC_V,
                          GP_DST_Y, GP_DST_U, GP_DST_V};
  for (unsigned p = 0; p < 6; p++) {
    unsigned size = (p < 3 ? j.sw * j.sh : w * h) / ((p % 3) ? 4 : 1);
    for (unsigned k = 0; k < 64; k++)
      guard += b[off[p] + size + k] != 0xa5;
  }
  char path[512];
  snprintf(path, sizeof(path), "%s.pgm", prefix);
  FILE *f = fopen(path, "wb");
  if (!f)
    fail("output");
  fprintf(f, "P5\n%u %u\n255\n", w, h);
  fwrite(b + GP_DST_Y, 1, w * h, f);
  fclose(f);
  snprintf(path, sizeof(path), "%s.lut", prefix);
  f = fopen(path, "wb");
  if (!f)
    fail("lut output");
  fwrite(lut, 4, ls * rows, f);
  fclose(f);
  printf("{\"width\":%u,\"height\":%u,\"angle\":%.2f,\"jobs\":%u,\"hw_mean_"
         "ms\":%.4f,\"hw_min_ms\":%.4f,\"hw_max_ms\":%.4f,\"wall_mean_ms\":%."
         "4f,\"changed_pixels\":%u,\"identity_equal_pixels\":%u,\"identity_abs_"
         "error\":%u,\"guard_changes\":%u,\"u0\":%u,\"v0\":%u,\"state\":%u,"
         "\"irq\":%u}\n",
         w, h, angle, count, sum / (count * 1e6), min / 1e6, max / 1e6,
         wall / (count * 1e6), changed, same, err, guard, b[GP_DST_U],
         b[GP_DST_V], j.state, j.irq);
  munmap(b, GP_BYTES);
  close(fd);
  return guard || (angle == 0 && err) ? 3 : 0;
}
