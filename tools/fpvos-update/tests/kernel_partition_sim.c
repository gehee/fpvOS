/* SPDX-License-Identifier: GPL-2.0-or-later */
/* Compile the actual board-specific kernel quirk against a bounded MTD stub. */
#include <assert.h>
#include <errno.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
typedef uint8_t u8;
typedef uint32_t u32;
#define ARRAY_SIZE(a) (sizeof(a) / sizeof((a)[0]))
#define MTD_NANDFLASH 4
#define MTD_WRITEABLE 0x400
#define GFP_KERNEL 0
#define kmalloc(n, flags) malloc(n)
#define kfree free
#define pr_info(...) printf(__VA_ARGS__)
struct mtd_info { unsigned type, erasesize, writesize, oobsize; uint64_t size; };
struct mtd_partition { const char *name; uint64_t offset, size; unsigned mask_flags; };
static int mtd_is_bitflip(int error) { return error == -EUCLEAN; }
static int mtd_read(struct mtd_info *mtd, uint64_t offset, size_t size, size_t *length, void *data)
{
    assert(offset + size <= mtd->size);
    if (getenv("TEST_READ_FAIL")) return -EIO;
    FILE *f = fopen("dev/mtd0", "rb"); assert(f);
    assert(!fseek(f, offset, SEEK_SET)); *length = fread(data, 1, size, f); fclose(f);
    return *length == size ? 0 : -EIO;
}
#include "ofpart_ar9311.h"
int main(void)
{
    struct mtd_info mtd = {MTD_NANDFLASH, 0x20000, 2048, 128, 0x8000000};
    struct mtd_partition parts[] = {
        {"boot-protected",0,0xb40000,MTD_WRITEABLE}, {"kernel",0xb40000,0x600000,0},
        {"dtb",0x1140000,0x60000,0}, {"vendor-rootfs",0x11a0000,0x1500000,MTD_WRITEABLE},
        {"fpvos",0x26a0000,0x1500000,0}, {"vendor-data",0x3ba0000,0x4460000,MTD_WRITEABLE}
    };
    if (getenv("TEST_BAD_MAP")) parts[3].offset++;
    int result = ar9311_partitions_post_parse(&mtd, parts, ARRAY_SIZE(parts));
    if (result) return 1;
    assert(parts[0].mask_flags & MTD_WRITEABLE);
    assert(parts[3].mask_flags & MTD_WRITEABLE);
    assert(!(parts[4].mask_flags & MTD_WRITEABLE));
    assert(parts[5].mask_flags & MTD_WRITEABLE);
    printf("vendor=%llx fpvos=%llx\n", (unsigned long long)parts[3].offset, (unsigned long long)parts[4].offset);
    return 0;
}
