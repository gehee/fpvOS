/* SPDX-License-Identifier: GPL-2.0-or-later */
/* The stock system left on a Gnd485 under fpvOS, as Caddx's image holds it:
 * UBI volume 0 of the stock bank, a SquashFS, cut at its bytes_used. Its
 * SHA-256 tells the Flasher which Caddx VRX image the stock kernel and device
 * tree for a return to stock must come from. Read only. The same assembly as
 * ar9311-firmware's extractor, for a live bank: erased and free blocks are
 * skipped, and a logical block found twice (a wear-levelling copy) is taken
 * from its newer copy. */
#ifndef AR9311_STOCK_ROOT_H
#define AR9311_STOCK_ROOT_H
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/types.h>
#include <unistd.h>
#include "fpvos-bytes.h"

#define STOCK_ROOT_PEB 0x20000U

static inline uint32_t stock_root_be32(const unsigned char *p)
{
	return (uint32_t)p[0] << 24 | (uint32_t)p[1] << 16 | (uint32_t)p[2] << 8 | p[3];
}
static inline int stock_root_erased(const unsigned char *p, size_t n)
{
	while (n--)
		if (*p++ != 0xff)
			return 0;
	return 1;
}
/* A UBI header's CRC: CRC-32 of its first 60 bytes, started at ~0 and not
 * complemented, big-endian at 60. */
static inline int stock_root_header(const unsigned char *h, const char *magic)
{
	return !memcmp(h, magic, 4) && h[4] == 1 && fpvos_crc32_update(~0U, h, 60) == stock_root_be32(h + 60);
}

/* Writes the SquashFS of the UBI image in fd's first `size` bytes to `out`.
 * `bad` says whether the eraseblock at an offset is bad (NULL: none are).
 * 0, or -1 with the reason on stderr. */
static int ar9311_stock_root(int fd, uint32_t size, int (*bad)(int, off_t), FILE *out)
{
	unsigned pebs = size / STOCK_ROOT_PEB;
	unsigned char *peb = malloc(STOCK_ROOT_PEB), *data = NULL, *have = calloc(pebs ? pebs : 1, 1);
	uint64_t *seq = calloc(pebs ? pebs : 1, sizeof(*seq));
	uint32_t vid_at = 0, data_at = 0, leb = 0;
	const char *why = NULL;
	if (!peb || !have || !seq || !pebs || size % STOCK_ROOT_PEB) {
		why = "stock bank: no memory or bad geometry";
		goto done;
	}
	for (unsigned i = 0; i < pebs && !why; i++) {
		off_t at = (off_t)i * STOCK_ROOT_PEB;
		if (bad && bad(fd, at))
			continue;
		size_t got = 0;
		while (got < STOCK_ROOT_PEB) {
			ssize_t n = pread(fd, peb + got, STOCK_ROOT_PEB - got, at + (off_t)got);
			if (n <= 0) {
				why = "stock bank: read failed";
				break;
			}
			got += (size_t)n;
		}
		if (why)
			break;
		if (stock_root_erased(peb, 64))
			continue;
		if (!stock_root_header(peb, "UBI#")) {
			why = "stock bank: not UBI";
			break;
		}
		uint32_t v = stock_root_be32(peb + 16), d = stock_root_be32(peb + 20);
		if (v < 64 || v + 64 > d || d >= STOCK_ROOT_PEB) {
			why = "stock bank: bad UBI offsets";
			break;
		}
		if (!data) {
			vid_at = v;
			data_at = d;
			leb = STOCK_ROOT_PEB - d;
			data = malloc((size_t)pebs * leb);
			if (!data) {
				why = "stock bank: no memory";
				break;
			}
			memset(data, 0xff, (size_t)pebs * leb);
		} else if (v != vid_at || d != data_at) {
			why = "stock bank: mixed UBI geometry";
			break;
		}
		const unsigned char *vid = peb + v;
		if (stock_root_erased(vid, 64))
			continue; /* a free eraseblock */
		if (!stock_root_header(vid, "UBI!")) {
			why = "stock bank: bad UBI volume header";
			break;
		}
		if (stock_root_be32(vid + 8) != 0)
			continue;
		uint32_t lnum = stock_root_be32(vid + 12);
		uint64_t sqnum = (uint64_t)stock_root_be32(vid + 24) << 32 | stock_root_be32(vid + 28);
		if (lnum >= pebs) {
			why = "stock bank: UBI block out of range";
			break;
		}
		if (have[lnum] && seq[lnum] >= sqnum)
			continue;
		memcpy(data + (size_t)lnum * leb, peb + d, leb);
		have[lnum] = 1;
		seq[lnum] = sqnum;
	}
	if (!why) {
		uint64_t used = 0;
		if (!data || !have[0] || memcmp(data, "hsqs", 4))
			why = "stock bank: no SquashFS in UBI volume 0";
		else {
			used = (uint64_t)fpvos_get_le32(data + 40) | (uint64_t)fpvos_get_le32(data + 44) << 32;
			if (used < 96 || used > (uint64_t)pebs * leb)
				why = "stock bank: bad SquashFS size";
		}
		for (uint64_t l = 0; !why && l < (used + leb - 1) / leb; l++)
			if (!have[l])
				why = "stock bank: UBI volume 0 has a missing block";
		if (!why && (fwrite(data, 1, (size_t)used, out) != used || fflush(out)))
			why = "stock bank: could not write its SquashFS";
	}
done:
	if (why)
		fprintf(stderr, "%s\n", why);
	free(peb);
	free(data);
	free(have);
	free(seq);
	return why ? -1 : 0;
}
#endif
