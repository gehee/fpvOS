/* SPDX-License-Identifier: GPL-2.0-or-later */
#ifndef FPVOS_SD_ROOT_H
#define FPVOS_SD_ROOT_H
#include <stddef.h>
#include <stdint.h>
#include <string.h>
#include "fpvos-bytes.h"
/* The main root is a squashfs (4.0, gzip or xz, what the kernel reads) that
 * the recovery mounts where it lies in the bundle volume. Its first 96 bytes
 * are the superblock; bytes_used may not reach past the component. */
#define SD_ROOT_SUPERBLOCK 96
static inline int sd_root_valid(const unsigned char *sb, size_t have, uint64_t size)
{
    if (have < SD_ROOT_SUPERBLOCK || size < 4096 || memcmp(sb,"hsqs",4)) return 0;
    unsigned block = fpvos_get_le32(sb+12), log = sb[22] | sb[23] << 8;
    unsigned compression = sb[20] | sb[21] << 8, major = sb[28] | sb[29] << 8, minor = sb[30] | sb[31] << 8;
    unsigned long long used = fpvos_get_le64(sb+40);
    return major == 4 && minor == 0 && (compression == 1 || compression == 4) &&
           log >= 12 && log <= 20 && block == 1U << log &&
           used >= SD_ROOT_SUPERBLOCK && used <= size;
}
#endif
