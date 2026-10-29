/* SPDX-License-Identifier: GPL-2.0-or-later */
/* AR9311 OTRA/uImage and Gnd485 device-tree policy. */
#include "board.h"
#include <string.h>
static uint32_t le32(const unsigned char *p)
{
	return (uint32_t)p[0] | (uint32_t)p[1] << 8 | (uint32_t)p[2] << 16 | (uint32_t)p[3] << 24;
}
static uint32_t be32(const unsigned char *p)
{
	return (uint32_t)p[3] | (uint32_t)p[2] << 8 | (uint32_t)p[1] << 16 | (uint32_t)p[0] << 24;
}
static uint32_t crc(uint32_t c, const unsigned char *p, size_t n)
{
	while (n--) {
		c ^= *p++;
		for (int i = 0; i < 8; i++)
			c = (c >> 1) ^ ((0 - (c & 1)) & 0xedb88320U);
	}
	return c;
}
static int zeros(const unsigned char *p, size_t n)
{
	while (n--)
		if (*p++)
			return 0;
	return 1;
}
/* Validate the structure walk and the root board identity before accepting a DTB. */
static int dtb_valid(const unsigned char *b, size_t n, unsigned kind)
{
	if (n < 40 || be32(b) != 0xd00dfeed || be32(b + 4) != n || be32(b + 20) < 17)
		return 0;
	size_t structure = be32(b + 8), strings = be32(b + 12);
	size_t structure_size = be32(b + 36), strings_size = be32(b + 32);
	if (structure < 40 || structure % 4 || structure > n || structure_size > n - structure ||
	    strings < 40 || strings > n || strings_size > n - strings)
		return 0;
	size_t pos = structure, end = structure + structure_size;
	unsigned depth = 0, roots = 0;
	int compatible = 0;
	const char *expected = kind ? "artosyn,proxima-9311" : "caddx,ascent-gnd485";
	while (pos + 4 <= end) {
		uint32_t token = be32(b + pos);
		pos += 4;
		if (token == 1) {
			const unsigned char *zero = memchr(b + pos, 0, end - pos);
			if (!zero || depth >= 64 || (!depth && (++roots != 1 || b[pos])))
				return 0;
			pos = ((size_t)(zero - b) + 4) & ~(size_t)3;
			depth++;
		} else if (token == 2) {
			if (!depth)
				return 0;
			depth--;
		} else if (token == 3) {
			if (!depth || pos + 8 > end)
				return 0;
			size_t len = be32(b + pos), name = be32(b + pos + 4);
			pos += 8;
			if (len > end - pos || name >= strings_size ||
			    !memchr(b + strings + name, 0, strings_size - name))
				return 0;
			if (depth == 1 && !strcmp((const char *)b + strings + name, "compatible")) {
				for (size_t i = 0; i < len;) {
					const unsigned char *zero = memchr(b + pos + i, 0, len - i);
					if (!zero)
						return 0;
					if (!strcmp((const char *)b + pos + i, expected))
						compatible = 1;
					i = (size_t)(zero - b) - pos + 1;
				}
			}
			pos = (pos + len + 3) & ~(size_t)3;
		} else if (token == 9) {
			return !depth && roots == 1 && compatible;
		} else if (token != 4) {
			return 0;
		}
	}
	return 0;
}
int fpvos_board_image_valid(unsigned index, const unsigned char *b, size_t n, unsigned kind)
{
	/* Restoration carries complete original partitions, including trailing
	 * vendor data. Validate the embedded image while hashing/writing all bytes. */
	if (kind) {
		if (index > 1 || n != fpvos_board.limits[index])
			return 0;
		size_t embedded = index == 0 ? 64ULL + le32(b + 16) : be32(b + 4);
		if (embedded > n || embedded < 64)
			return 0;
		n = embedded;
	}
	if (index == 1)
		return dtb_valid(b, n, kind);
	size_t skip = index == 0 ? 64 : 0;
	if (n < skip + 64)
		return 0;
	if (skip) {
		uint32_t sum = 0;
		for (size_t i = 64; i < n; i++)
			sum += b[i];
		if (memcmp(b, "OTRA", 4) || le32(b + 12) != (kind ? 0x200a0000U : 0x20200000U) ||
		    le32(b + 16) != n - 64 || le32(b + 32) != sum)
			return 0;
	}
	const unsigned char *h = b + skip;
	uint32_t len = be32(h + 12);
	if (be32(h) != 0x27051956 || h[28] != 5 || h[29] != 22 || h[30] != (index == 0 ? 2 : 3) ||
	    h[31] != (index == 0 ? 5 : 0))
		return 0;
	if (len > n - skip - 64)
		return 0;
	if (index == 0 &&
	    (be32(h + 16) != (kind ? 0x200a0000U : 0x20200000U) || be32(h + 20) != be32(h + 16)))
		return 0;
	unsigned char copy[64];
	memcpy(copy, h, 64);
	memset(copy + 4, 0, 4);
	if (~crc(~0U, copy, 64) != be32(h + 4) || ~crc(~0U, h + 64, len) != be32(h + 24))
		return 0;
	if (index == 2)
		return n == 64 + len && len >= 2 && h[64] == 0x1f && h[65] == 0x8b;
	return n % 256 == 0 && n - skip - 64 - len < 256 &&
	       zeros(h + 64 + len, n - skip - 64 - len);
}
