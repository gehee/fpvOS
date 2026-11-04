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

/* Leaves the slot erased and reading back clean, or fails. */
static int erase_again(int fd, const struct erase_info_user *erase, loff_t offset)
{
    unsigned char check[0x4800];
    struct erase_info_user e = *erase;
    if (ioctl(fd,MEMERASE,&e) || p1_read_checked(fd,check,sizeof(check),offset)) return -1;
    for (size_t i = 0; i < sizeof(check); i++) if (check[i] != 0xff) return -1;
    return 0;
}

int p1_select_bank(unsigned bank)
{
    unsigned char records[2][AR9311_GPT_BYTES], next[AR9311_GPT_BYTES], check[AR9311_GPT_BYTES];
    unsigned selected, current, number;
    if (bank > 1 || p1_gpt_read(records) || !p1_layout(records,&selected,&current)) return -1;
    if (current == bank) return 0;
    unsigned generation = fpvos_get_le32(records[selected]+532);
    if (generation == UINT32_MAX) return -1;
    unsigned slot = selected ^ 1;
    memcpy(next,records[selected],sizeof(next));
    fpvos_put_le32(next+532,generation+1);
    fpvos_put_le64(next+536,slot ? 0x3f7ff : 1);
    fpvos_put_le64(next+544,slot ? 1 : 0x3f7ff);
    fpvos_put_le64(next+584,slot ? 0x3f7df : 2);
    for (unsigned i = 0; i < 128; i++) {
        unsigned char *e = next+1024+128*i;
        char name[37] = {0};
        for (unsigned j = 0; j < 36; j++) name[j] = e[56+2*j];
        const char *prefix[] = {"kernel","dtb","userapp"};
        for (unsigned j = 0; j < 3; j++) {
            size_t n = strlen(prefix[j]);
            if (!strncmp(name,prefix[j],n) && (name[n]=='0' || name[n]=='1') && !name[n+1])
                fpvos_put_le64(e+48, (unsigned)(name[n]-'0') == bank ? 1ULL<<47 : 0);
        }
    }
    fpvos_put_le32(next+600,fpvos_crc32(next+1024,16384));
    fpvos_put_le32(next+528,0);
    fpvos_put_le32(next+528,fpvos_crc32(next+512,92));
    if (!ar9311_gpt_valid(next,slot)) return -1;
    memcpy(records[slot],next,sizeof(next));
    if (!p1_layout(records,&selected,&current) || selected != slot || current != bank) return -1;

    int stock = p1_stock();
    if (stock < 0) return -1;
    int ro = p1_mtd(stock ? (slot ? "gpt1" : "gpt0") : "boot-state",
                    stock ? 0x100000+slot*0x40000 : 0x100000,
                    stock ? 0x40000 : 0x80000,&number);
    if (ro < 0) return -1;
    int fd = writable(ro,number); close(ro);
    if (fd < 0) return -1;
    loff_t offset = stock ? 0 : slot*0x40000;
    struct erase_info_user erase = {.start=offset,.length=0x20000};
    /* Never erase the selected record. SPL boots it while the new one fails
     * its CRC, but stops at a GPT page that ECC cannot correct, which a power
     * cut during this write can leave: a failed write is erased again, and
     * power must stay on until this returns. The slot's second block is SPL's
     * spare, read only once this one is marked bad; bad GPT blocks require
     * physical recovery. */
    unsigned char padded[0x4800];
    memset(padded,0xff,sizeof(padded)); memcpy(padded,next,sizeof(next));
    /* MTD character writes are synchronous; mtdchar has no fsync method. */
    int rc = ioctl(fd,MEMGETBADBLOCK,&offset);
    if (!rc) {
        rc = ioctl(fd,MEMERASE,&erase) || write_exact(fd,padded,sizeof(padded),offset) ||
             p1_read_checked(fd,check,sizeof(check),offset) || memcmp(check,next,sizeof(next));
        if (rc && erase_again(fd,&erase,offset))
            fprintf(stderr,"P1: GPT record %u is still unreadable after a failed write; keep the unit powered: it may not boot\n",slot);
    }
    close(fd);
    if (!rc) rc = p1_gpt_read(records) || !p1_layout(records,&selected,&current) || current != bank;
    return rc ? -1 : 0;
}

int p1_flash_image(unsigned index, const char *path, int writing)
{
    if (index > 1) return -1;
    unsigned number, size = index ? 0x60000 : 0x600000;
    int ro = p1_mtd(index ? "dtb0" : "kernel0",index ? 0x1640000 : 0xa40000,size,&number);
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
