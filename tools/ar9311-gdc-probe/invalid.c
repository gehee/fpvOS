// SPDX-License-Identifier: GPL-2.0-or-later
/* Reject invalid requests before any DMA job is submitted. */
#include "probe_abi.h"
#include <errno.h>
#include <fcntl.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <sys/ioctl.h>
#include <sys/mman.h>
#include <unistd.h>
static void expect(int got, int error, const char *name) {
  if (got != -1 || errno != error) {
    fprintf(stderr, "%s: result=%d errno=%d expected=%d\n", name, got, errno,
            error);
    exit(1);
  }
  printf("PASS %s\n", name);
}
int main(void) {
  int fd = open("/dev/gdc-probe", O_RDWR);
  if (fd < 0) {
    perror("open");
    return 1;
  }
  expect(open("/dev/gdc-probe", O_RDWR), EBUSY, "exclusive open");
  void *bad = mmap(NULL, 4096, PROT_READ | PROT_WRITE, MAP_SHARED, fd, 0);
  expect(bad == MAP_FAILED ? -1 : 0, EINVAL, "wrong mapping length");
  uint8_t *b = mmap(NULL, GP_BYTES, PROT_READ | PROT_WRITE, MAP_SHARED, fd, 0);
  if (b == MAP_FAILED) {
    perror("mmap");
    return 1;
  }
  if (ioctl(fd, GP_INIT)) {
    perror("init");
    return 1;
  }
  expect(ioctl(fd, _IO('G', 9)), ENOTTY, "unknown ioctl");
  struct gp_job j = {0};
  expect(ioctl(fd, GP_RUN, &j), EINVAL, "zero dimensions");
  j = (struct gp_job){.sw = 128, .sh = 128, .dw = 64, .dh = 65};
  expect(ioctl(fd, GP_RUN, &j), EINVAL, "unaligned height");
  j.dh = 64;
  j.src_offset = UINT32_MAX;
  expect(ioctl(fd, GP_RUN, &j), ERANGE, "invalid offset");
  j.src_offset = GP_Y_BYTES;
  expect(ioctl(fd, GP_RUN, &j), ERANGE, "offset outside owned plane");
  j.src_offset = 0;
  *(uint32_t *)(b + GP_LUT) = UINT32_MAX;
  expect(ioctl(fd, GP_RUN, &j), ERANGE, "map outside source");
  munmap(b, GP_BYTES);
  close(fd);
  return 0;
}
