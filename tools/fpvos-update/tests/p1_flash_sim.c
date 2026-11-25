/* SPDX-License-Identifier: GPL-2.0-or-later */
/* Exercise real GPT/MTD transactions, including torn writes and bad blocks. */
#include "../../../br-external/package/fpvos-update/backends/p1-air/flash.c"
#include <assert.h>
#include <stdarg.h>
static int fault;
static unsigned writes, pwrites, ecc_failed;
/* Match mtdchar rather than regular-file fsync semantics. */
int __wrap_fsync(int fd) { (void)fd; errno=EINVAL; return -1; }
int __real_open(const char *,int,...);
ssize_t __real_pwrite(int,const void *,size_t,off_t);
int __wrap_open(const char *path,int flags,...) {
    mode_t mode=0;
    if (flags&O_CREAT) { va_list ap;va_start(ap,flags);mode=va_arg(ap,int);va_end(ap); }
    /* mtd0 boot-state; 1/2 bank 0 kernel/DTB; 3/4 bank 1 kernel/DTB. */
    static const char *const node[] = {"boot-state","kernel0","dtb0","kernel1","dtb1"};
    unsigned n;
    if (sscanf(path,"/dev/mtd%u",&n) == 1) { assert(n < 5); path=node[n]; }
    else assert(strncmp(path,"/dev/mtd",8));
    return __real_open(path,flags,mode);
}
int p1_stock(void) { return 0; }
int p1_mtd(const char *name,unsigned offset,unsigned size,unsigned *number) {
    if (!strcmp(name,"boot-state")) { assert(offset==0x100000 && size==0x80000);*number=0; }
    else {
        unsigned bank = name[strlen(name)-1]=='1';
        if (!strcmp(name,p1_kernel_part(bank))) { assert(offset==p1_kernel_offset(bank) && size==0x600000);*number=1+2*bank; }
        else if (!strcmp(name,p1_dtb_part(bank))) { assert(offset==p1_dtb_offset(bank) && size==0x60000);*number=2+2*bank; }
        else assert(0);
    }
    return open(name,O_RDONLY);
}
int p1_gpt_read(unsigned char g[2][AR9311_GPT_BYTES]) {
    int fd=open("boot-state",O_RDONLY);assert(fd>=0);
    int rc=p1_read_checked(fd,g[0],AR9311_GPT_BYTES,0)||p1_read_checked(fd,g[1],AR9311_GPT_BYTES,0x40000);
    close(fd);return rc || !p1_layout_valid(g) ? -1 : 0;
}
ssize_t __wrap_pwrite(int fd,const void *data,size_t n,off_t off) {
    assert(n%2048==0 && off%2048==0);
    unsigned char old[0x20000];assert(n<=sizeof(old));assert(pread(fd,old,n,off)==(ssize_t)n);
    for (size_t i=0;i<n;i++) assert((old[i]&((const unsigned char *)data)[i])==((const unsigned char *)data)[i]);
    pwrites++;
    if (fault==1 && ++writes==1) { assert(__real_pwrite(fd,data,512,off)==512);errno=EIO;return -1; }
    ssize_t rc=__real_pwrite(fd,data,n,off);
    if (fault==3) { unsigned char zero=((const unsigned char *)data)[0]^1;assert(__real_pwrite(fd,&zero,1,off)==1); }
    return rc;
}
/* ECC failures read back data like mtdchar: only the failure count shows them.
 * 5: the new GPT record's first readback; 6: every GPT read after its write,
 * the erased one too; 7: the first kernel readback. */
ssize_t __real_pread(int,void *,size_t,off_t);
ssize_t __wrap_pread(int fd,void *data,size_t n,off_t off) {
    static int once;
    if ((fault==5 && pwrites && off==0 && n==AR9311_GPT_BYTES && !once++) ||
        (fault==6 && pwrites && off==0 && n>=AR9311_GPT_BYTES) ||
        (fault==7 && pwrites && off==0 && n==0x20000 && !once++) ||
        (fault==9 && n==128)) ecc_failed++;
    return __real_pread(fd,data,n,off);
}
int __wrap_ioctl(int fd,unsigned long request,...) {
    va_list ap;va_start(ap,request);void *arg=va_arg(ap,void *);va_end(ap);
    if (request==MEMGETBADBLOCK) return (fault==2 && *(loff_t *)arg==0x20000) || (fault==8 && *(loff_t *)arg==0);
    if (request==ECCGETSTATS) {
        struct mtd_ecc_stats *s=arg;memset(s,0,sizeof(*s));s->failed=ecc_failed;return 0;
    }
    assert(request==MEMERASE);
    struct erase_info_user *e=arg;assert(e->length==0x20000 && e->start%0x20000==0);
    if (fault==4) {errno=EIO;return -1;}
    unsigned char b[0x20000];memset(b,0xff,sizeof(b));assert(__real_pwrite(fd,b,sizeof(b),e->start)==sizeof(b));return 0;
}
/* select BANK FAULT | write|compare IMAGE FAULT [BANK]: the kernel image of BANK (0)
 * | kind BANK FAULT: prints what BANK's kernel partition holds (p1_kernel_kind).
 * 8: the partition's first block is bad; 9: the header reads with an ECC error. */
int main(int argc,char **argv) {
    assert(argc==4 || argc==5);fault=atoi(argv[3]);
    if (!strcmp(argv[1],"kind")) { printf("%d\n",p1_kernel_kind(atoi(argv[2]))); return 0; }
    unsigned bank = argc==5 ? (unsigned)atoi(argv[4]) : 0;
    int rc=!strcmp(argv[1],"select") ? p1_select_bank(atoi(argv[2])) :
           p1_flash_image(bank,0,argv[2],strcmp(argv[1],"compare")!=0);
    return rc ? 1 : 0;
}
