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

static int path(char out[PATH_MAX], const char *work, const char *relative)
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

static int copy_file(const char *source, const char *destination, unsigned mode)
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
        "root/usr/sbin", "root/usr/libexec", "root/dev", "root/proc", "root/sys",
        "root/run", "root/run/fpvos-update", "root/tmp"};
    char destination[PATH_MAX];
    for (size_t i = 0; i < sizeof(directories) / sizeof(*directories); i++) {
        if (path(destination, work, directories[i]) || mkdir(destination, 0700)) return -1;
    }
    for (size_t i = 0; i < fpvos_bootstrap_file_count; i++) {
        const struct fpvos_bootstrap_file *file = &fpvos_bootstrap_files[i];
        if (path(destination, work, file->path)) return -1;
        int fd = open(destination, O_WRONLY | O_CREAT | O_EXCL | O_NOFOLLOW | O_CLOEXEC, file->mode);
        if (fd < 0) return -1;
        int result = write_all(fd, file->data, file->length);
        if (close(fd)) result = -1;
        if (result) return -1;
    }
    for (size_t i = 0; i < fpvos_bootstrap_link_count; i++) {
        const struct fpvos_bootstrap_link *item = &fpvos_bootstrap_links[i];
        if (path(destination, work, item->path) || symlink(item->target, destination)) return -1;
    }
    return 0;
}

static int ram_directory(const char *work)
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

int fpvos_bootstrap_main(int argc, char **argv)
{
    char self[PATH_MAX], executable[PATH_MAX], root_executable[PATH_MAX], script[PATH_MAX], busybox[PATH_MAX];
    ssize_t n = readlink("/proc/self/exe", self, sizeof(self) - 1);
    if (n <= 0 || n >= (ssize_t)sizeof(self) - 1) return 1;
    self[n] = 0;
    if (geteuid() || !fpvos_stock_runtime_valid()) {
        fprintf(stderr, "Bootstrap requires root on the supported stock Gnd485 runtime\n");
        return 1;
    }
    umask(077);
    if (argc == 1) {
        struct statfs fs;
        const char *hook = getenv("FPVOS_BOOTSTRAP_HOOK");
        if (!hook || strcmp(hook, "stock-clean") || strcmp(self, "/usrdata/fpvos-update") ||
            access("/factory/sirius-clean-system-flag", F_OK) == 0 ||
            statfs("/tmp", &fs) || fs.f_type != TMPFS_MAGIC) {
            fprintf(stderr, "Bootstrap must be entered by the consumed stock clean hook with tmpfs /tmp\n");
            return 1;
        }
        char work[] = "/tmp/fpvos-bootstrap.XXXXXX";
        if (!mkdtemp(work) || !ram_directory(work) || path(executable, work, "fpvos-update") ||
            copy_file("/proc/self/exe", executable, 0700) || chdir(work)) return 1;
        if (unlink("/usrdata/fpvos-update") || unlink("/usrdata/fpvos-bootstrap.sh")) return 1;
        sync();
        execl(executable, executable, "bootstrap", "--ram", work, (char *)NULL);
    } else if (argc == 3 && !strcmp(argv[1], "--ram")) {
        const char *work = argv[2];
        if (!ram_directory(work) || path(executable, work, "fpvos-update") || strcmp(self, executable) ||
            fpvos_bootstrap_extract(work) || path(root_executable, work, "root/usr/sbin/fpvos-update") ||
            link(executable, root_executable) || path(script, work, "prepare.sh") ||
            path(busybox, work, "root/bin/busybox")) return 1;
        char version[PATH_MAX];
        if (path(version, work, "root/etc/app.version") || copy_file("/etc/app.version", version, 0600) || chdir(work)) return 1;
        unsetenv("FPVOS_BOOTSTRAP_HOOK");
        execl(busybox, busybox, "sh", script, work, (char *)NULL);
    } else {
        fprintf(stderr, "Usage: fpvos-update bootstrap (stock clean hook only)\n");
        return 2;
    }
    perror("bootstrap exec");
    return 1;
}
