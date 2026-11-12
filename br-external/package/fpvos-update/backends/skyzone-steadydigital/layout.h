/* SPDX-License-Identifier: GPL-2.0-or-later */
#ifndef FPVOS_SD_LAYOUT_H
#define FPVOS_SD_LAYOUT_H
#include <string.h>
#include "fpvos-bytes.h"
/* Skyzone SteadyDigital: the stock Artosyn A/B GPT, exactly as every unit
 * ships (no conversion). It is ONE record at the start of gpt0 (0x100000);
 * gpt1 is erased and unused. For each pair env, uboot, kernel, dtb and
 * userapp the vendor boot chain starts the member with attribute bit 47, and
 * the vendor's own slot flip moves all five pairs together; the singletons
 * (vendor, factory, usr_data, usr_log) always carry bit 47. A vendor table
 * follows the record up to SD_GPT_BYTES; a rewrite keeps it byte for byte. */
#define SD_GPT_BYTES 0x4800
#define SD_ACTIVE (1ULL << 47)

static const struct { const char *name; unsigned start, size; } sd_partitions[] = {
    {"vendor",0x180000,0x80000}, {"factory",0x200000,0x600000},
    {"env0",0x800000,0x60000}, {"env1",0x860000,0x60000},
    {"uboot0",0x8c0000,0xc0000}, {"uboot1",0x980000,0xc0000},
    {"kernel0",0xa40000,0x600000}, {"kernel1",0x1040000,0x600000},
    {"dtb0",0x1640000,0x60000}, {"dtb1",0x16a0000,0x60000},
    {"userapp0",0x1700000,0x2d00000}, {"userapp1",0x4400000,0x2d00000},
    {"usr_data",0x7100000,0x600000}, {"usr_log",0x7700000,0x600000}
};
/* Entries 2..11 are the pairs; even = bank A (suffix 0), odd = bank B. */
#define SD_PAIR(j) ((j) >= 2 && (j) <= 11)

/* Index into sd_partitions of a used entry, -1 for an empty one, -2 for an
 * unknown or malformed one. The name is read up to its NUL: stock leaves
 * non-zero bytes after it. */
static inline int sd_entry(const unsigned char *e)
{
    unsigned nonzero = 0;
    for (unsigned j = 0; j < 128; j++) nonzero |= e[j];
    if (!nonzero) return -1;
    char name[37] = {0};
    for (unsigned j = 0; j < 36 && (e[56+2*j] || e[57+2*j]); j++) {
        if (e[57+2*j]) return -2;
        name[j] = e[56+2*j];
    }
    for (unsigned j = 0; j < sizeof(sd_partitions)/sizeof(sd_partitions[0]); j++)
        if (!strcmp(name,sd_partitions[j].name)) return (int)j;
    return -2;
}

/* 1 when g holds the expected table with one whole bank selected (*bank: 0 =
 * A/stock, 1 = B/fpvOS), else 0. */
static inline int sd_layout(const unsigned char *g, unsigned *bank)
{
    const unsigned char *h = g + 512;
    unsigned char copy[92];
    if (memcmp(h,"EFI PART",8) || fpvos_get_le32(h+8) != 0x10000 || fpvos_get_le32(h+12) != 92 ||
        fpvos_get_le64(h+24) != 1 || fpvos_get_le64(h+32) != 0x3ffff ||
        fpvos_get_le64(h+40) != 0xc00 || fpvos_get_le64(h+48) != 0x3ffde ||
        fpvos_get_le64(h+72) != 2 || fpvos_get_le32(h+80) != 128 || fpvos_get_le32(h+84) != 128) return 0;
    memcpy(copy,h,92); memset(copy+16,0,4);
    if (fpvos_crc32(copy,92) != fpvos_get_le32(h+16) ||
        fpvos_crc32(g+1024,16384) != fpvos_get_le32(h+88)) return 0;
    unsigned found = 0, active = 0;
    for (unsigned i = 0; i < 128; i++) {
        const unsigned char *e = g + 1024 + 128*i;
        int j = sd_entry(e);
        if (j == -1) continue;
        if (j < 0 || (found & (1U<<j))) return 0;
        unsigned long long attr = fpvos_get_le64(e+48);
        if (fpvos_get_le64(e+32) != sd_partitions[j].start/512 ||
            fpvos_get_le64(e+40) != (sd_partitions[j].start+sd_partitions[j].size)/512-1 ||
            (SD_PAIR(j) ? (attr & ~SD_ACTIVE) != 0 : attr != SD_ACTIVE)) return 0;
        if (SD_PAIR(j) && attr) active |= 1U << (j-2);
        found |= 1U << j;
    }
    if (found != (1U<<14)-1 || (active != 0x155 && active != 0x2aa)) return 0;
    if (bank) *bank = active == 0x2aa;
    return 1;
}

/* Select bank (0 = A, 1 = B) for all five pairs and recompute both CRCs. The
 * caller checks the result with sd_layout before writing it. */
static inline void sd_set_bank(unsigned char *g, unsigned bank)
{
    for (unsigned i = 0; i < 128; i++) {
        unsigned char *e = g + 1024 + 128*i;
        int j = sd_entry(e);
        if (j >= 0 && SD_PAIR(j)) {
            unsigned long long attr = fpvos_get_le64(e+48) & ~SD_ACTIVE;
            fpvos_put_le64(e+48, attr | ((unsigned)(j-2)%2 == bank ? SD_ACTIVE : 0));
        }
    }
    fpvos_put_le32(g+512+88,fpvos_crc32(g+1024,16384));
    fpvos_put_le32(g+512+16,0);
    fpvos_put_le32(g+512+16,fpvos_crc32(g+512,92));
}
#endif
