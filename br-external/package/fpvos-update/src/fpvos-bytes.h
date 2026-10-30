/* SPDX-License-Identifier: GPL-2.0-or-later */
/* Bytewise wire/image helpers shared with the kernel GPT parser. */
#ifndef FPVOS_BYTES_H
#define FPVOS_BYTES_H
#ifdef __KERNEL__
#include <linux/types.h>
#else
#include <stddef.h>
#endif

static inline unsigned int fpvos_get_le32(const unsigned char *p)
{
	return (unsigned int)p[0] | (unsigned int)p[1] << 8 |
	       (unsigned int)p[2] << 16 | (unsigned int)p[3] << 24;
}
static inline unsigned long long fpvos_get_le64(const unsigned char *p)
{
	return fpvos_get_le32(p) | ((unsigned long long)fpvos_get_le32(p + 4) << 32);
}
static inline unsigned int fpvos_get_be32(const unsigned char *p)
{
	return (unsigned int)p[3] | (unsigned int)p[2] << 8 |
	       (unsigned int)p[1] << 16 | (unsigned int)p[0] << 24;
}
static inline void fpvos_put_le32(unsigned char *p, unsigned int value)
{
	p[0] = value;
	p[1] = value >> 8;
	p[2] = value >> 16;
	p[3] = value >> 24;
}
static inline void fpvos_put_le64(unsigned char *p, unsigned long long value)
{
	fpvos_put_le32(p, value);
	fpvos_put_le32(p + 4, value >> 32);
}
/* CRC-32/ISO-HDLC: initialize with ~0U, feed chunks, complement once at end. */
static inline unsigned int fpvos_crc32_update(unsigned int state,
					    const unsigned char *p, size_t n)
{
	while (n--) {
		state ^= *p++;
		for (unsigned int i = 0; i < 8; i++)
			state = (state >> 1) ^ ((0U - (state & 1)) & 0xedb88320U);
	}
	return state;
}
static inline unsigned int fpvos_crc32(const unsigned char *p, size_t n)
{
	return ~fpvos_crc32_update(~0U, p, n);
}
#endif
