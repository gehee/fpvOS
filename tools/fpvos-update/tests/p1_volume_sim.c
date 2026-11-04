/* SPDX-License-Identifier: GPL-2.0-or-later */
/* Find the stock UBI volumes in a sysfs/dev tree under the working directory. */
#include "../../../br-external/package/fpvos-update/backends/p1-air/storage.c"
#include <assert.h>
#include <stdarg.h>
int __real_open(const char *,int,...);
DIR *__real_opendir(const char *);
int __real_access(const char *,int);
static const char *local(const char *path) {
    assert(!strncmp(path,"/sys/",5) || !strncmp(path,"/dev/",5));
    return path+1;
}
int __wrap_open(const char *path,int flags,...) { return __real_open(local(path),flags); }
/* glibc's fortified open() calls this when the flags are not a constant. */
int __wrap___open_2(const char *path,int flags) { return __wrap_open(path,flags); }
DIR *__wrap_opendir(const char *path) { return __real_opendir(local(path)); }
int __wrap_access(const char *path,int mode) { return __real_access(local(path),mode); }
/* MTD geometry of the P1 SPI-NAND; the partition size is the file's. */
int __wrap_ioctl(int fd,unsigned long request,...) {
    va_list ap;va_start(ap,request);struct mtd_info_user *info=va_arg(ap,void *);va_end(ap);
    assert(request==MEMGETINFO);
    struct stat st;assert(!fstat(fd,&st));
    *info=(struct mtd_info_user){.type=MTD_NANDFLASH,.size=st.st_size,.erasesize=0x20000,.writesize=2048,.oobsize=128};
    return 0;
}
int main(int argc,char **argv) {
    assert(argc==2);
    char node[64];
    int fd=volume(!strcmp(argv[1],"data"),0,node);
    if (fd<0) return 1;
    puts(node);
    return 0;
}
