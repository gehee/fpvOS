/* SPDX-License-Identifier: GPL-2.0-or-later */
#ifndef FPVOS_AR9311_GPT_H
#define FPVOS_AR9311_GPT_H
#ifdef __KERNEL__
#include <linux/string.h>
#else
#include <string.h>
#endif
#include "fpvos-bytes.h"
#define AR9311_GPT_BYTES 0x4400
static inline int ar9311_gpt_valid(const unsigned char *g, unsigned int slot)
{
	unsigned char h[92];
	for (unsigned int i = 0; i < sizeof(h); i++) h[i] = g[512 + i];
	if (memcmp(h, "EFI PART", 8) || fpvos_get_le32(h + 8) != 0x10000 ||
	    fpvos_get_le32(h + 12) != 92 || fpvos_get_le64(h + 24) != (slot ? 0x3f7ffU : 1U) ||
	    fpvos_get_le64(h + 32) != (slot ? 1U : 0x3f7ffU) ||
	    fpvos_get_le64(h + 40) != 0xc00 || fpvos_get_le64(h + 48) != 0x3f7de ||
	    (fpvos_get_le64(h + 72) != 2 && (!slot || fpvos_get_le64(h + 72) != 0x3f7df)) ||
	    fpvos_get_le32(h + 80) != 128 || fpvos_get_le32(h + 84) != 128) return 0;
	unsigned int saved = fpvos_get_le32(h + 16);
	for (unsigned int i = 16; i < 20; i++) h[i] = 0;
	return fpvos_crc32(h, sizeof(h)) == saved &&
	       fpvos_crc32(g + 1024, 16384) == fpvos_get_le32(h + 88);
}
#endif
