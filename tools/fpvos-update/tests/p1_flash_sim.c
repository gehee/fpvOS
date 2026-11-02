/* SPDX-License-Identifier: GPL-2.0-or-later */
/* Exercise real GPT/MTD transactions, including torn writes and bad blocks. */
#include "../../../br-external/package/fpvos-update/backends/p1-air/flash.c"
#include <assert.h>
#include <stdarg.h>
static int fault;
static unsigned writes;
/* Match mtdchar rather than regular-file fsync semantics. */
int __wrap_fsync(int fd) { (void)fd; errno=EINVAL; return -1; }
int __real_open(const char *,int,...);
ssize_t __real_pwrite(int,const void *,size_t,off_t);
int __wrap_open(const char *path,int flags,...) {
    mode_t mode=0;
    if (flags&O_CREAT) { va_list ap;va_start(ap,flags);mode=va_arg(ap,int);va_end(ap); }
    if (!strcmp(path,"/dev/mtd0")) path="boot-state";
    else if (!strcmp(path,"/dev/mtd1")) path="kernel0";
    else if (!strcmp(path,"/dev/mtd2")) path="dtb0";
    else assert(strncmp(path,"/dev/mtd",8));
    return __real_open(path,flags,mode);
}
int p1_stock(void) { return 0; }
int p1_mtd(const char *name,unsigned offset,unsigned size,unsigned *number) {
    if (!strcmp(name,"boot-state")) { assert(offset==0x100000 && size==0x80000);*number=0; }
    else if (!strcmp(name,"kernel0")) { assert(offset==0xa40000 && size==0x600000);*number=1; }
    else if (!strcmp(name,"dtb0")) { assert(offset==0x1640000 && size==0x60000);*number=2; }
    else assert(0);
    return open(name,O_RDONLY);
}
int p1_gpt_read(unsigned char g[2][AR9311_GPT_BYTES]) {
    int fd=open("boot-state",O_RDONLY);assert(fd>=0);
    int rc=p1_exact(fd,g[0],AR9311_GPT_BYTES,0)||p1_exact(fd,g[1],AR9311_GPT_BYTES,0x40000);
    close(fd);return rc || !p1_layout_valid(g) ? -1 : 0;
}
ssize_t __wrap_pwrite(int fd,const void *data,size_t n,off_t off) {
    assert(n%2048==0 && off%2048==0);
    unsigned char old[0x20000];assert(n<=sizeof(old));assert(pread(fd,old,n,off)==(ssize_t)n);
    for (size_t i=0;i<n;i++) assert((old[i]&((const unsigned char *)data)[i])==((const unsigned char *)data)[i]);
    if (fault==1 && ++writes==1) { assert(__real_pwrite(fd,data,512,off)==512);errno=EIO;return -1; }
    ssize_t rc=__real_pwrite(fd,data,n,off);
    if (fault==3) { unsigned char zero=((const unsigned char *)data)[0]^1;assert(__real_pwrite(fd,&zero,1,off)==1); }
    return rc;
}
int __wrap_ioctl(int fd,unsigned long request,...) {
    va_list ap;va_start(ap,request);void *arg=va_arg(ap,void *);va_end(ap);
    if (request==MEMGETBADBLOCK) return fault==2 && *(loff_t *)arg==0x20000;
    assert(request==MEMERASE);
    struct erase_info_user *e=arg;assert(e->length==0x20000 && e->start%0x20000==0);
    if (fault==4) {errno=EIO;return -1;}
    unsigned char b[0x20000];memset(b,0xff,sizeof(b));assert(__real_pwrite(fd,b,sizeof(b),e->start)==sizeof(b));return 0;
}
int main(int argc,char **argv) {
    assert(argc==4);fault=atoi(argv[3]);
    int rc=!strcmp(argv[1],"select") ? p1_select_bank(atoi(argv[2])) :
           p1_flash_image(0,argv[2],strcmp(argv[1],"compare")!=0);
    return rc ? 1 : 0;
}
