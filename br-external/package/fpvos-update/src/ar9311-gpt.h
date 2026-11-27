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
/* The disk's last LBA a record describes: 0x3f7ff (127 MiB: the goggles, the
 * Ascent VRX) or 0x3ffff (the whole 128 MiB: a P1 Nano VRX's stock). */
static inline unsigned long long ar9311_gpt_last(const unsigned char *g, unsigned int slot)
{
	return fpvos_get_le64(g + 512 + (slot ? 24 : 32));
}
static inline int ar9311_gpt_valid(const unsigned char *g, unsigned int slot)
{
	unsigned char h[92];
	unsigned long long last = ar9311_gpt_last(g, slot);
	for (unsigned int i = 0; i < sizeof(h); i++) h[i] = g[512 + i];
	if (memcmp(h, "EFI PART", 8) || fpvos_get_le32(h + 8) != 0x10000 ||
	    (last != 0x3f7ffU && last != 0x3ffffU) ||
	    fpvos_get_le32(h + 12) != 92 || fpvos_get_le64(h + 24) != (slot ? last : 1U) ||
	    fpvos_get_le64(h + 32) != (slot ? 1U : last) ||
	    fpvos_get_le64(h + 40) != 0xc00 || fpvos_get_le64(h + 48) != last - 0x21 ||
	    (fpvos_get_le64(h + 72) != 2 && (!slot || fpvos_get_le64(h + 72) != last - 0x20)) ||
	    fpvos_get_le32(h + 80) != 128 || fpvos_get_le32(h + 84) != 128) return 0;
	unsigned int saved = fpvos_get_le32(h + 16);
	for (unsigned int i = 16; i < 20; i++) h[i] = 0;
	return fpvos_crc32(h, sizeof(h)) == saved &&
	       fpvos_crc32(g + 1024, 16384) == fpvos_get_le32(h + 88);
}
#endif
