/* SPDX-License-Identifier: GPL-2.0-or-later */
/* Exercise real board/MTD discovery with fixture files. No target access. */
#define _GNU_SOURCE
#include <assert.h>
#include <dirent.h>
#include <fcntl.h>
#include <mtd/mtd-user.h>
#include <stdarg.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <sys/ioctl.h>
#include <sys/utsname.h>
#include <unistd.h>
static int devices[4096], numbers[4096];
int __real_open(const char *, int, ...);
DIR *__real_opendir(const char *);
FILE *__real_fopen(const char *, const char *);
static const char *fixture(const char *path, char buffer[1024])
{
    if (!strncmp(path, "/proc/", 6) || !strncmp(path, "/sys/", 5) ||
        !strncmp(path, "/dev/", 5) || !strcmp(path, "/etc/app.version")) {
        snprintf(buffer, 1024, ".%s", path);
        return buffer;
    }
    return path;
}
int __wrap_open(const char *path, int flags, ...)
{
    mode_t mode = 0;
    if (flags & O_CREAT) { va_list args; va_start(args, flags); mode = va_arg(args, int); va_end(args); }
    int mtd = !strncmp(path, "/dev/mtd", 8);
    /* All preflight device descriptors must be opened read-only. */
    if (mtd && !getenv("TEST_BOOT")) assert((flags & O_ACCMODE) == O_RDONLY);
    char buffer[1024];
    int fd = __real_open(fixture(path, buffer), flags, mode);
    if (getenv("TEST_TRACE")) fprintf(stderr, "open %s => %d\n", path, fd);
    if (fd >= 0) { assert(fd < 4096); devices[fd] = mtd; if (mtd) numbers[fd] = atoi(path + 8); }
    return fd;
}
int __wrap___open_2(const char *path, int flags) { return __wrap_open(path, flags); }
DIR *__wrap_opendir(const char *path)
{
    char buffer[1024]; return __real_opendir(fixture(path, buffer));
}
FILE *__wrap_fopen(const char *path, const char *mode)
{
    char buffer[1024]; return __real_fopen(fixture(path, buffer), mode);
}
uid_t __wrap_geteuid(void) { return 0; }
int __wrap_uname(struct utsname *uts)
{
    memset(uts, 0, sizeof(*uts));
    snprintf(uts->release, sizeof(uts->release), "%s", getenv("TEST_RELEASE") ? getenv("TEST_RELEASE") : "4.9.38");
    return 0;
}
int __wrap_ioctl(int fd, unsigned long command, ...)
{
    va_list args; va_start(args, command); void *arg = va_arg(args, void *); va_end(args);
    assert(fd >= 0 && fd < 4096 && devices[fd]);
    if (command == MEMGETINFO) {
        struct stat st; assert(!fstat(fd, &st));
        struct mtd_info_user *info = arg; memset(info, 0, sizeof(*info));
        info->flags = MTD_WRITEABLE; info->type = MTD_NANDFLASH; info->size = st.st_size;
        info->erasesize = 0x20000; info->writesize = 2048; info->oobsize = 128;
        if (getenv("TEST_TRACE")) fprintf(stderr, "geometry %d size=%x type=%u\n", fd, info->size, info->type);
        return 0;
    }
    if (command == MEMGETBADBLOCK) {
        if (getenv("TEST_BADBLOCK")) return 1;
        return getenv("TEST_BAD_MTD") && getenv("TEST_BAD_OFFSET") &&
            numbers[fd] == atoi(getenv("TEST_BAD_MTD")) &&
            *(loff_t *)arg == strtoll(getenv("TEST_BAD_OFFSET"), NULL, 0);
    }
    if (command == ECCGETSTATS) { memset(arg, 0, sizeof(struct mtd_ecc_stats)); return 0; }
    assert(!"preflight attempted a write or unexpected ioctl"); return -1;
}
