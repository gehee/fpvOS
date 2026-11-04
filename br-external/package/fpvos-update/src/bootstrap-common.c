/* SPDX-License-Identifier: GPL-2.0-or-later */
/* The stock shell hook only enters here. All payloads come from this executable,
 * never from a host-supplied archive or extraction pathname. */
#define _GNU_SOURCE
#include "bootstrap.h"
#include <errno.h>
#include <fcntl.h>
#include <limits.h>
#include <linux/magic.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <sys/vfs.h>
#include <unistd.h>

int fpvos_stock_runtime_valid(void);

int fpvos_bootstrap_path(char out[PATH_MAX], const char *work, const char *relative)
{
    return snprintf(out, PATH_MAX, "%s/%s", work, relative) >= PATH_MAX ? -1 : 0;
}

static int write_all(int fd, const unsigned char *data, size_t length)
{
    while (length) {
        ssize_t n = write(fd, data, length);
        if (n < 0 && errno == EINTR) continue;
        if (n <= 0) return -1;
        data += n;
        length -= n;
    }
    return 0;
}

int fpvos_bootstrap_copy(const char *source, const char *destination, unsigned mode)
{
    int in = open(source, O_RDONLY | O_CLOEXEC);
    if (in < 0) return -1;
    struct stat st;
    if (fstat(in, &st) || !S_ISREG(st.st_mode) || st.st_size <= 0 || st.st_size > 16 * 1024 * 1024) {
        close(in);
        return -1;
    }
    int out = open(destination, O_WRONLY | O_CREAT | O_EXCL | O_NOFOLLOW | O_CLOEXEC, mode);
    int result = out < 0 ? -1 : 0;
    unsigned char buffer[16384];
    for (off_t left = st.st_size; !result && left;) {
        ssize_t n = read(in, buffer, left < (off_t)sizeof(buffer) ? (size_t)left : sizeof(buffer));
        if (n < 0 && errno == EINTR) continue;
        if (n <= 0 || write_all(out, buffer, n)) { result = -1; break; }
        left -= n;
    }
    if (out >= 0 && close(out)) result = -1;
    close(in);
    return result;
}

/* Kept separate for unprivileged extraction tests; not exposed as a CLI command.
 * Production callers validate a fresh, root-owned tmpfs directory first. */
int fpvos_bootstrap_extract(const char *work)
{
    static const char *directories[] = {"root", "root/bin", "root/etc", "root/usr",
        "root/usr/sbin", "root/usr/libexec", "root/usr/share", "root/usr/share/fpvos-update", "root/dev", "root/proc", "root/sys",
        "root/run", "root/run/fpvos-update", "root/tmp"};
    char destination[PATH_MAX];
    for (size_t i = 0; i < sizeof(directories) / sizeof(*directories); i++) {
        if (fpvos_bootstrap_path(destination, work, directories[i]) || mkdir(destination, 0700)) return -1;
    }
    for (size_t i = 0; i < fpvos_bootstrap_file_count; i++) {
        const struct fpvos_bootstrap_file *file = &fpvos_bootstrap_files[i];
        if (fpvos_bootstrap_path(destination, work, file->path)) return -1;
        int fd = open(destination, O_WRONLY | O_CREAT | O_EXCL | O_NOFOLLOW | O_CLOEXEC, file->mode);
        if (fd < 0) return -1;
        int result = write_all(fd, file->data, file->length);
        if (close(fd)) result = -1;
        if (result) return -1;
    }
    for (size_t i = 0; i < fpvos_bootstrap_link_count; i++) {
        const struct fpvos_bootstrap_link *item = &fpvos_bootstrap_links[i];
        if (fpvos_bootstrap_path(destination, work, item->path) || symlink(item->target, destination)) return -1;
    }
    return 0;
}

int fpvos_bootstrap_ram_directory(const char *work)
{
    struct stat st;
    struct statfs fs;
    char canonical[PATH_MAX];
    const char *prefix = "/tmp/fpvos-bootstrap.";
    return !strncmp(work, prefix, strlen(prefix)) && work[strlen(prefix)] &&
        !strchr(work + strlen(prefix), '/') && realpath(work, canonical) && !strcmp(work, canonical) &&
        !lstat(work, &st) && S_ISDIR(st.st_mode) && st.st_uid == 0 && !(st.st_mode & 077) &&
        !statfs(work, &fs) && fs.f_type == TMPFS_MAGIC;
}
