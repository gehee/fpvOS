/* SPDX-License-Identifier: GPL-2.0-or-later */
#ifndef FPVOS_AR9311_IMAGE_H
#define FPVOS_AR9311_IMAGE_H
#include "fpvos-bytes.h"
#include <string.h>
/* Unsigned OTRA containing a checksummed ARM64 Linux legacy LZ4 uImage. */
static inline int ar9311_kernel_valid(const unsigned char *b, size_t n, unsigned load)
{
    if (n < 128 || n % 256 || memcmp(b,"OTRA",4) ||
        fpvos_get_le32(b+12) != load || fpvos_get_le32(b+16) != n-64) return 0;
    unsigned sum = 0;
    for (size_t i = 64; i < n; i++) sum += b[i];
    if (fpvos_get_le32(b+32) != sum) return 0;
    const unsigned char *h = b+64;
    unsigned length = fpvos_get_be32(h+12);
    if (fpvos_get_be32(h) != 0x27051956 || h[28] != 5 || h[29] != 22 || h[30] != 2 || h[31] != 5 ||
        fpvos_get_be32(h+16) != load || fpvos_get_be32(h+20) != load || length > n-128 || n-128-length >= 256) return 0;
    unsigned char copy[64]; memcpy(copy,h,64); memset(copy+4,0,4);
    if (fpvos_crc32(copy,64) != fpvos_get_be32(h+4) || fpvos_crc32(h+64,length) != fpvos_get_be32(h+24)) return 0;
    for (size_t i = 128+length; i < n; i++) if (b[i]) return 0;
    return 1;
}
#endif
