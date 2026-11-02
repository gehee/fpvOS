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
        if (!mkdtemp(work) || !fpvos_bootstrap_ram_directory(work) || fpvos_bootstrap_path(executable, work, "fpvos-update") ||
            fpvos_bootstrap_copy("/proc/self/exe", executable, 0700) || chdir(work)) return 1;
        if (unlink("/usrdata/fpvos-update") || unlink("/usrdata/fpvos-bootstrap.sh")) return 1;
        sync();
        execl(executable, executable, "bootstrap", "--ram", work, (char *)NULL);
    } else if (argc == 3 && !strcmp(argv[1], "--ram")) {
        const char *work = argv[2];
        if (!fpvos_bootstrap_ram_directory(work) || fpvos_bootstrap_path(executable, work, "fpvos-update") || strcmp(self, executable) ||
            fpvos_bootstrap_extract(work) || fpvos_bootstrap_path(root_executable, work, "root/usr/sbin/fpvos-update") ||
            link(executable, root_executable) || fpvos_bootstrap_path(script, work, "prepare.sh") ||
            fpvos_bootstrap_path(busybox, work, "root/bin/busybox")) return 1;
        char version[PATH_MAX];
        if (fpvos_bootstrap_path(version, work, "root/etc/app.version") || fpvos_bootstrap_copy("/etc/app.version", version, 0600) || chdir(work)) return 1;
        unsetenv("FPVOS_BOOTSTRAP_HOOK");
        execl(busybox, busybox, "sh", script, work, (char *)NULL);
    } else {
        fprintf(stderr, "Usage: fpvos-update bootstrap (stock clean hook only)\n");
        return 2;
    }
    perror("bootstrap exec");
    return 1;
}
