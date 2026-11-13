/* SPDX-License-Identifier: GPL-2.0-or-later */
#ifndef FPVOS_BUNDLE_H
#define FPVOS_BUNDLE_H
#include <stdint.h>
#include <string.h>
#include "board.h"
#include "fpvos-bytes.h"

/* An FPVOSUP1 header: 512 bytes, then each component in order. Component i is
 * at 96 + 104*i: name[32], le32 size, sha256 hex[64], le32 0. */
#define FPVOS_BUNDLE_ENTRY(h, i) ((h) + 96 + 104 * (i))

static inline int fpvos_bundle_zeros(const unsigned char *p, size_t n)
{
	while (n--)
		if (*p++)
			return 0;
	return 1;
}

/* 1 when h is a well-formed header of this board for a bundle of exactly size
 * bytes (its CRC, kind, component names, sizes and hash fields), else 0. The
 * components themselves are not looked at. */
static inline int fpvos_bundle_header_valid(const unsigned char *header, uint64_t size)
{
	unsigned char h[512];
	memcpy(h, header, sizeof(h));
	if (size < 512 || memcmp(h, "FPVOSUP1", 8) || fpvos_get_le32(h + 8) != 1 ||
	    fpvos_get_le32(h + 12) != fpvos_board.board_id || fpvos_get_le32(h + 16) != size)
		return 0;
	unsigned kind = fpvos_get_le32(h + 88), count = fpvos_get_le32(h + 20);
	if (kind > 1 || !fpvos_board.counts[kind] || count != fpvos_board.counts[kind] ||
	    size > fpvos_board.bundle_limits[kind] ||
	    !fpvos_bundle_zeros(FPVOS_BUNDLE_ENTRY(h, count), 104 * (3 - count)))
		return 0;
	uint32_t expected = fpvos_get_le32(h + 508);
	memset(h + 508, 0, 4);
	if (~fpvos_crc32_update(~0U, h, 512) != expected || !memchr(h + 24, 0, 64) ||
	    !fpvos_bundle_zeros(h + 92, 4) || !fpvos_bundle_zeros(h + 408, 100))
		return 0;
	uint64_t sum = 512;
	for (unsigned i = 0; i < count; i++) {
		const unsigned char *entry = FPVOS_BUNDLE_ENTRY(h, i);
		size_t name_len = strlen(fpvos_board.names[i]);
		uint32_t n = fpvos_get_le32(entry + 32);
		if (memcmp(entry, fpvos_board.names[i], name_len) ||
		    !fpvos_bundle_zeros(entry + name_len, 32 - name_len) ||
		    !fpvos_bundle_zeros(entry + 100, 4) || !n || n > fpvos_board.limits[i])
			return 0;
		for (unsigned j = 36; j < 100; j++)
			if (!((entry[j] >= '0' && entry[j] <= '9') || (entry[j] >= 'a' && entry[j] <= 'f')))
				return 0;
		sum += n;
	}
	return sum == size;
}
#endif
