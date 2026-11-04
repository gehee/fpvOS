/* SPDX-License-Identifier: GPL-2.0-or-later */
#define _GNU_SOURCE
#include "bootstrap.h"
#include "p1.h"
#include <errno.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <unistd.h>

int fpvos_bootstrap_main(int argc, char **argv)
{
    char self[PATH_MAX], executable[PATH_MAX], target[PATH_MAX], script[PATH_MAX], busybox[PATH_MAX];
    ssize_t n = readlink("/proc/self/exe",self,sizeof(self)-1);
    if (n <= 0 || n >= (ssize_t)sizeof(self)-1 || geteuid() || p1_stock() != 1) return 1;
    self[n] = 0;
    umask(077);
    if (argc == 1) {
        const char *hook = getenv("FPVOS_BOOTSTRAP_HOOK");
        if (!hook || strcmp(hook,"stock-clean") ||
            strcmp(self,"/usrdata/fpvos-update") ||
            access("/usrdata/sirius-clean-system-flag",F_OK) == 0) return 1;
        char work[] = "/tmp/fpvos-bootstrap.XXXXXX";
        if (!mkdtemp(work) || !fpvos_bootstrap_ram_directory(work) ||
            fpvos_bootstrap_path(executable,work,"fpvos-update") ||
            fpvos_bootstrap_copy("/proc/self/exe",executable,0700) || chdir(work)) return 1;
        if (unlink("/usrdata/fpvos-update") || unlink("/usrdata/fpvos-bootstrap.sh")) return 1;
        sync();
        execl(executable,executable,"bootstrap","--ram",work,"update",(char *)NULL);
    } else if (argc == 4 && !strcmp(argv[1],"--ram") &&
               !strcmp(argv[3],"update")) {
        const char *work = argv[2];
        if (!fpvos_bootstrap_ram_directory(work) || fpvos_bootstrap_path(executable,work,"fpvos-update") ||
            strcmp(self,executable) || fpvos_bootstrap_extract(work) ||
            fpvos_bootstrap_path(target,work,"root/usr/sbin/fpvos-update") || link(executable,target) ||
            fpvos_bootstrap_path(script,work,"prepare.sh") || fpvos_bootstrap_path(busybox,work,"root/bin/busybox")) return 1;
        if (fpvos_bootstrap_path(target,work,"root/etc/fpvos-stock-version") ||
            fpvos_bootstrap_copy("/usr/usrdata/sdk_version.json",target,0600)) return 1;
        unsetenv("FPVOS_BOOTSTRAP_HOOK");
        execl(busybox,busybox,"sh",script,work,argv[3],(char *)NULL);
    } else return 2;
    perror("P1 bootstrap exec");
    return 1;
}
