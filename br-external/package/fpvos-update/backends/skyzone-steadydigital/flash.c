/* SPDX-License-Identifier: GPL-2.0-or-later */
#define _GNU_SOURCE
#include "p1.h"
#include "layout.h"
#include <errno.h>
#include <fcntl.h>
#include <mtd/mtd-user.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <sys/ioctl.h>
#include <sys/stat.h>
#include <unistd.h>

static int write_exact(int fd, const void *data, size_t size, off_t offset)
{
    const unsigned char *p = data;
    while (size) {
        ssize_t n = pwrite(fd,p,size,offset);
        if (n < 0 && errno == EINTR) continue;
        if (n <= 0) return -1;
        p += n; size -= n; offset += n;
    }
    return 0;
}

static int writable(int readonly, unsigned number)
{
    char path[64]; struct stat before, after;
    if (fstat(readonly,&before)) return -1;
    snprintf(path,sizeof(path),"/dev/mtd%u",number);
    int fd = open(path,O_RDWR|O_NOFOLLOW|O_CLOEXEC);
    if (fd >= 0 && (fstat(fd,&after) || before.st_rdev != after.st_rdev)) {
        close(fd); return -1;
    }
    return fd;
}

/* Writes data (SD_GPT_BYTES) over the first gpt0 block and reads it back. */
static int write_record(int fd, const unsigned char *data)
{
    struct erase_info_user erase = {.start=0,.length=0x20000};
    unsigned char check[SD_GPT_BYTES];
    /* MTD character writes are synchronous; mtdchar has no fsync method. */
    return ioctl(fd,MEMERASE,&erase) || write_exact(fd,data,SD_GPT_BYTES,0) ||
           p1_read_checked(fd,check,sizeof(check),0) || memcmp(check,data,SD_GPT_BYTES);
}

int p1_select_bank(unsigned bank)
{
    unsigned char now[SD_GPT_BYTES], next[SD_GPT_BYTES];
    unsigned current, number;
    if (bank > 1 || p1_gpt_read(now) || !sd_layout(now,&current)) return -1;
    if (current == bank) return 0;
    memcpy(next,now,sizeof(next));
    sd_set_bank(next,bank);
    if (!sd_layout(next,&current) || current != bank) return -1;

    int stock = p1_stock();
    if (stock < 0) return -1;
    int ro = p1_mtd(stock ? "gpt0" : "boot-state",0x100000,stock ? 0x40000 : 0x80000,&number);
    if (ro < 0) return -1;
    int fd = writable(ro,number); close(ro);
    if (fd < 0) return -1;
    /* The rewrite keeps only the record and the vendor table after it, so the
     * rest of the block must hold nothing. */
    unsigned char *rest = malloc(0x20000-SD_GPT_BYTES);
    loff_t offset = 0;
    int rc = !rest || ioctl(fd,MEMGETBADBLOCK,&offset) ||
             p1_read_checked(fd,rest,0x20000-SD_GPT_BYTES,SD_GPT_BYTES);
    for (size_t i = 0; !rc && i < 0x20000-SD_GPT_BYTES; i++) if (rest[i] != 0xff) rc = -1;
    free(rest);
    /* This is the vendor's own slot flip: the one record is rewritten in place
     * (gpt1 is erased and unused). Between the erase and the last page the
     * unit has no valid table, so power must stay on until this returns. A
     * failed write is erased and the previous record put back. */
    if (!rc && (rc = write_record(fd,next)) && write_record(fd,now))
        fprintf(stderr,"SteadyDigital: the GPT could not be written back; keep the unit powered: it may not boot\n");
    close(fd);
    if (!rc) rc = p1_gpt_read(now) || !sd_layout(now,&current) || current != bank;
    return rc ? -1 : 0;
}

int p1_flash_image(unsigned index, const char *path, int writing)
{
    if (index > 1) return -1;
    unsigned number, size = index ? 0x60000 : 0x600000;
    int ro = p1_mtd(index ? "dtb1" : "kernel1",index ? 0x16a0000 : 0x1040000,size,&number);
    if (ro < 0) return -1;
    int fd = writing ? writable(ro,number) : ro;
    if (writing) close(ro);
    if (fd < 0) return -1;
    int in = open(path,O_RDONLY|O_NOFOLLOW|O_CLOEXEC|O_NONBLOCK);
    struct stat st; int rc = -1;
    if (in < 0 || fstat(in,&st) || !S_ISREG(st.st_mode) || st.st_size <= 0 || st.st_size > size) goto done;
    unsigned capacity = 0;
    for (loff_t off = 0; off < size; off += 0x20000) {
        int bad = ioctl(fd,MEMGETBADBLOCK,&off);
        if (bad < 0) goto done;
        if (!bad) capacity += 0x20000;
    }
    if ((uint64_t)st.st_size > capacity) goto done;
    unsigned char *data = malloc(0x40000);
    if (!data) goto done;
    size_t consumed = 0;
    rc = 0;
    for (loff_t off = 0; off < size && consumed < (size_t)st.st_size; off += 0x20000) {
        int bad = ioctl(fd,MEMGETBADBLOCK,&off);
        if (bad < 0) { rc = -1; break; }
        if (bad) continue;
        size_t n = st.st_size-consumed;
        if (n > 0x20000) n = 0x20000;
        memset(data,0xff,0x20000);
        if (p1_exact(in,data,n,consumed)) { rc = -1; break; }
        if (writing) {
            struct erase_info_user erase = {.start=off,.length=0x20000};
            if (ioctl(fd,MEMERASE,&erase) || write_exact(fd,data,0x20000,off)) { rc = -1; break; }
        }
        if (p1_read_checked(fd,data+0x20000,writing ? 0x20000 : n,off) ||
            memcmp(data,data+0x20000,writing ? 0x20000 : n)) { rc = -1; break; }
        consumed += n;
    }
    free(data);
    if (consumed != (size_t)st.st_size) rc = -1;
done:
    if (in >= 0) close(in);
    close(fd);
    return rc ? -1 : 0;
}
