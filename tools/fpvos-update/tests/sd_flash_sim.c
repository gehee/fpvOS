/* SPDX-License-Identifier: GPL-2.0-or-later */
/* SteadyDigital's flash.c on file-backed MTD: the one-record in-place GPT
 * rewrite (its slot flip), kernel/DTB writes and p1_kernel_kind, with torn
 * writes, erase failures, readback mismatches and ECC failures; see
 * test_steadydigital.py. */
#include "../../../br-external/package/fpvos-update/backends/skyzone-steadydigital/flash.c"
#include <assert.h>
#include <stdarg.h>
#include <string.h>
static int fault;
static unsigned writes, erases, pwrites, ecc_failed;
int __wrap_fsync(int fd) { (void)fd; errno=EINVAL; return -1; }
int __real_open(const char *,int,...);
ssize_t __real_pwrite(int,const void *,size_t,off_t);
ssize_t __real_pread(int,void *,size_t,off_t);
/* mtd0 boot-state (stock: gpt0, the same first 256 KiB); 1/2 bank 0
 * kernel/DTB; 3/4 bank 1 kernel/DTB. */
static const char *const node[] = {"boot-state","kernel0","dtb0","kernel1","dtb1"};
int __wrap_open(const char *path,int flags,...) {
    mode_t mode=0;
    if (flags&O_CREAT) { va_list ap;va_start(ap,flags);mode=va_arg(ap,int);va_end(ap); }
    unsigned n;
    if (sscanf(path,"/dev/mtd%u",&n) == 1) { assert(n < 5); path=node[n]; }
    else assert(strncmp(path,"/dev/mtd",8));
    return __real_open(path,flags,mode);
}
int p1_stock(void) { const char *s=getenv("SD_STOCK"); return s && *s=='1'; }
int p1_mtd(const char *name,unsigned offset,unsigned size,unsigned *number) {
    if (!strcmp(name,"boot-state")) { assert(!p1_stock() && offset==0x100000 && size==0x80000); *number=0; }
    else if (!strcmp(name,"gpt0")) { assert(p1_stock() && offset==0x100000 && size==0x40000); *number=0; name="boot-state"; }
    else {
        unsigned bank = name[strlen(name)-1]=='1';
        if (!strcmp(name,p1_kernel_part(bank))) { assert(offset==p1_kernel_offset(bank) && size==0x600000);*number=1+2*bank; }
        else if (!strcmp(name,p1_dtb_part(bank))) { assert(offset==p1_dtb_offset(bank) && size==0x60000);*number=2+2*bank; }
        else assert(0);
    }
    return open(name,O_RDONLY);
}
/* As storage.c's: the record at the start of the first block, read checked. */
int p1_gpt_read(unsigned char gpt[SD_GPT_BYTES]) {
    unsigned n;
    int fd=p1_mtd(p1_stock() ? "gpt0" : "boot-state",0x100000,p1_stock() ? 0x40000 : 0x80000,&n);
    assert(fd>=0);
    loff_t offset=0;
    int bad=ioctl(fd,MEMGETBADBLOCK,&offset);
    int rc=bad || p1_read_checked(fd,gpt,SD_GPT_BYTES,0);
    close(fd);
    return rc || !sd_layout(gpt,NULL) ? -1 : 0;
}
/* NAND: a write only clears bits, in whole pages.
 * 1: the first write tears after 512 bytes; 3: the first write reads back
 * with a wrong byte; 8: the first write tears and the erase after it fails. */
ssize_t __wrap_pwrite(int fd,const void *data,size_t n,off_t off) {
    assert(n%2048==0 && off%2048==0);
    static unsigned char old[0x20000];assert(n<=sizeof(old));assert(__real_pread(fd,old,n,off)==(ssize_t)n);
    for (size_t i=0;i<n;i++) assert((old[i]&((const unsigned char *)data)[i])==((const unsigned char *)data)[i]);
    pwrites++;
    if ((fault==1 || fault==8) && ++writes==1) { assert(__real_pwrite(fd,data,512,off)==512);errno=EIO;return -1; }
    ssize_t rc=__real_pwrite(fd,data,n,off);
    if (fault==3 && ++writes==1) { unsigned char wrong=((const unsigned char *)data)[600]^0x10;assert(__real_pwrite(fd,&wrong,1,off+600)==1); }
    return rc;
}
/* ECC failures read the data back like mtdchar: only the failure count shows
 * them. 5: the new record's first readback; 6: every GPT read after the
 * first write; 9: every 128-byte (kernel header) read. */
ssize_t __wrap_pread(int fd,void *data,size_t n,off_t off) {
    static int once;
    if ((fault==5 && pwrites && off==0 && n==SD_GPT_BYTES && !once++) ||
        (fault==6 && pwrites && off==0 && n>=SD_GPT_BYTES) ||
        (fault==9 && n==128)) ecc_failed++;
    return __real_pread(fd,data,n,off);
}
/* 2: every partition's first block is bad; 4: every erase fails; 8: the
 * second erase fails. */
int __wrap_ioctl(int fd,unsigned long request,...) {
    va_list ap;va_start(ap,request);void *arg=va_arg(ap,void *);va_end(ap);
    if (request==MEMGETBADBLOCK) return fault==2 && *(loff_t *)arg==0;
    if (request==ECCGETSTATS) {
        struct mtd_ecc_stats *s=arg;memset(s,0,sizeof(*s));s->failed=ecc_failed;return 0;
    }
    assert(request==MEMERASE);
    struct erase_info_user *e=arg;assert(e->length==0x20000 && e->start%0x20000==0);
    erases++;
    if (fault==4 || (fault==8 && erases==2)) {errno=EIO;return -1;}
    unsigned char b[0x20000];memset(b,0xff,sizeof(b));assert(__real_pwrite(fd,b,sizeof(b),e->start)==sizeof(b));return 0;
}
/* select BANK FAULT | write|compare IMAGE FAULT BANK INDEX | kind BANK FAULT.
 * Prints the number of page writes (select), or the kernel kind. */
int main(int argc,char **argv) {
    assert(argc==4 || argc==6);fault=atoi(argv[3]);
    if (!strcmp(argv[1],"kind")) { printf("%d\n",p1_kernel_kind(atoi(argv[2]))); return 0; }
    if (!strcmp(argv[1],"select")) { int rc=p1_select_bank(atoi(argv[2])); printf("%u\n",pwrites); return rc ? 1 : 0; }
    assert(argc==6);
    int rc=p1_flash_image(atoi(argv[4]),atoi(argv[5]),argv[2],strcmp(argv[1],"compare")!=0);
    return rc ? 1 : 0;
}
