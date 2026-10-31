/* SPDX-License-Identifier: GPL-2.0-or-later */
/* Shared by the RAM updater and the kernel's opt-in AR9311 partition quirk.
 * Pure read-only decoding; never edits GPT or changes the selected stock bank. */
#ifndef FPVOS_AR9311_LAYOUT_H
#define FPVOS_AR9311_LAYOUT_H
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
/* On failure, *stock_bank is untouched. Equal-generation conflicts are unsafe. */
static inline int ar9311_stock_bank(const unsigned char records[2][AR9311_GPT_BYTES],
				   unsigned int *stock_bank)
{
	int valid[2];
	for (unsigned int slot = 0; slot < 2; slot++) {
		valid[slot] = ar9311_gpt_valid(records[slot], slot);
		if (!valid[slot])
			for (unsigned int i = 0; i < AR9311_GPT_BYTES; i++)
				if (records[slot][i] != 0xff) return -1;
	}
	if (!valid[0] && !valid[1]) return -1;
	if (valid[0] && valid[1] && fpvos_get_le32(records[0] + 532) == fpvos_get_le32(records[1] + 532) &&
	    memcmp(records[0] + 1024, records[1] + 1024, 16384)) return -1;
	unsigned int selected = valid[1] && (!valid[0] ||
		fpvos_get_le32(records[1] + 532) > fpvos_get_le32(records[0] + 532));
	const unsigned char *g = records[selected];
	const char *names[] = {"kernel", "dtb", "userapp0", "userapp1"};
	const unsigned int offsets[] = {0xb40000, 0x1140000, 0x11a0000, 0x26a0000};
	const unsigned int sizes[] = {0x600000, 0x60000, 0x1500000, 0x1500000};
	unsigned int found = 0, active = 0;
	for (unsigned int i = 0; i < 128; i++) {
		const unsigned char *e = g + 1024 + i * 128;
		char name[37] = {0};
		for (unsigned int j = 0; j < 36; j++) {
			if (e[56 + 2 * j + 1]) return -1;
			name[j] = e[56 + 2 * j];
		}
		for (unsigned int j = 0; j < 4; j++) if (!strcmp(name, names[j])) {
			unsigned long long begin = fpvos_get_le64(e + 32), end = fpvos_get_le64(e + 40);
			unsigned int enabled = !!(fpvos_get_le64(e + 48) & (1ULL << 47));
			if ((found & (1U << j)) || begin != offsets[j] / 512 ||
			    end != (offsets[j] + sizes[j]) / 512 - 1 || (j < 2 && !enabled)) return -1;
			found |= 1U << j;
			if (j >= 2 && enabled) active |= 1U << (j - 2);
		}
	}
	if (found != 15 || (active != 1 && active != 2)) return -1;
	*stock_bank = active == 2;
	return 0;
}
#endif
