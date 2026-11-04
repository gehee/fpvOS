/* SPDX-License-Identifier: GPL-2.0-or-later */
#define _GNU_SOURCE
#include "p1.h"
#include "board.h"
#include "bootstrap.h"
#include <errno.h>
#include <fcntl.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/file.h>
#include <sys/stat.h>
#include <sys/statfs.h>
#include <sys/wait.h>
#include <linux/magic.h>
#include <unistd.h>

static int execute(const char *program, const char *a, const char *b)
{
    pid_t pid = fork(); int status;
    if (!pid) { execlp(program,program,a,b,(char *)NULL); _exit(127); }
    if (pid < 0) return -1;
    while (waitpid(pid,&status,0) < 0) if (errno != EINTR) return -1;
    return WIFEXITED(status) && !WEXITSTATUS(status) ? 0 : -1;
}

static int regular(const char *path)
{
    struct stat st;
    return !lstat(path,&st) && S_ISREG(st.st_mode) && !st.st_uid;
}

static void remove_images(const char *directory)
{
    for (unsigned i = 0; i < fpvos_board.counts[0]; i++) {
        char path[1024]; snprintf(path,sizeof(path),"%s/%s",directory,fpvos_board.names[i]); unlink(path);
    }
    rmdir(directory);
}

static int verify(const char *package, const char *directory)
{
    if (mkdir(directory,0700) || execute("/usr/libexec/fpvos-update-verify",package,directory)) return -1;
    char path[1024]; snprintf(path,sizeof(path),"%s/rootfs.cpio.gz",directory);
    return execute("gzip","-t",path);
}

static int clean_flag(int action)
{
    if (p1_state_mount()) return -1;
    const char *path = P1_STATE "/fpvos-update-clean";
    char value[16]; int rc = 0;
    if (action == 1) rc = p1_atomic(path,"1\n",2,0600);
    else if (access(path,F_OK) == 0) {
        if (!regular(path) || p1_read(path,value,sizeof(value)) || strcmp(value,"1")) rc = -1;
        else if (unlink(path)) rc = -1;
        else rc = 10;
    } else if (errno != ENOENT) rc = -1;
    sync();
    if (p1_state_unmount()) rc = -1;
    return rc;
}

static int remove_stock_hook(void)
{
    if (p1_state_mount()) return -1;
    int rc = 0; char value[256];
    if (access(P1_FLAG,F_OK) == 0) {
        if (!regular(P1_FLAG) || p1_read(P1_FLAG,value,sizeof(value)) ||
            (strcmp(value,"web:/usrdata/fpvos-boot/boot.sh") && strcmp(value,"web:/usrdata/fpvos-boot/clean.sh"))) rc = -1;
        else rc = unlink(P1_FLAG);
    } else if (errno != ENOENT) rc = -1;
    sync();
    if (p1_state_unmount()) rc = -1;
    return rc;
}

static int transaction(const char *source)
{
    char directory[] = P1_WORK "/transaction.XXXXXX", package[512], images[512], readback[512], path[1024];
    char before[65], after[65]; int rc = -1;
    if (!mkdtemp(directory)) return -1;
    snprintf(package,sizeof(package),"%s/package.fwu",directory);
    snprintf(images,sizeof(images),"%s/images",directory);
    snprintf(readback,sizeof(readback),"%s/readback.fwu",directory);
    if (fpvos_bootstrap_copy(source,package,0400) || verify(package,images) || p1_hash(package,before)) goto done;
    /* Select the untouched stock bank before modifying bank 0. Power loss
     * during installation then boots stock; only verified images reactivate
     * fpvOS. No change to environment/U-Boot selection or factory contents. */
    if (remove_stock_hook() || p1_select_bank(1)) goto done;
    for (unsigned i = 0; i < 2; i++) {
        snprintf(path,sizeof(path),"%s/%s",images,fpvos_board.names[i]);
        if (p1_flash_image(i,path,1)) goto done;
    }
    remove_images(images);
    if (p1_bundle_write(package) || p1_bundle_read(readback) || p1_hash(readback,after) || strcmp(before,after)) goto done;
    int flag = clean_flag(0);
    if (flag < 0 || p1_select_bank(0)) goto done;
    puts("Verified kernel, DTB and UBI root; direct fpvOS bank selected");
    rc = 0;
 done:
    remove_images(images); unlink(package); unlink(readback); rmdir(directory);
    return rc;
}

static int boot(void)
{
    int rc = clean_flag(0);
    if (rc) return rc;
    const char *package = P1_WORK "/boot.fwu", *images = "/run/fpvos-root";
    if (p1_bundle_read(package) || verify(package,images)) return -1;
    for (unsigned i = 0; i < 2; i++) {
        char path[512]; snprintf(path,sizeof(path),"%s/%s",images,fpvos_board.names[i]);
        if (p1_flash_image(i,path,0)) return -1;
        unlink(path);
    }
    return 0;
}

int fpvos_stock_runtime_valid(void) { return p1_stock() == 1; }

int main(int argc, char **argv)
{
    if (argc < 2 || geteuid()) return 2;
    umask(077);
    if (mkdir(P1_WORK,0700) && errno != EEXIST) return 1;
    struct stat st; struct statfs fs;
    if (lstat(P1_WORK,&st) || !S_ISDIR(st.st_mode) || st.st_uid || (st.st_mode&077) ||
        statfs(P1_WORK,&fs) || fs.f_type != TMPFS_MAGIC) return 1;
    int lock = open(P1_WORK "/storage.lock",O_CREAT|O_RDWR|O_NOFOLLOW|O_CLOEXEC,0600);
    if (lock < 0 || flock(lock,LOCK_EX|LOCK_NB)) return 1;
    int rc = -1;
    if (p1_preflight()) goto done;
    if (!strcmp(argv[1],"preflight") && argc == 2) {
        puts("P1 NAND layout verified; bank 1 and factory contents preserved"); rc = 0;
    } else if (!strcmp(argv[1],"install") && argc == 3) {
        if (!regular(P1_WORK "/clean")) goto done;
        const char *starting = "0 3 verifying and installing\n";
        if (p1_atomic(P1_WORK "/status",starting,strlen(starting),0600)) goto done;
        rc = transaction(argv[2]);
        const char *finished = rc ? "0 -1 installation failed; inspect bank selection\n" :
                                    "100 4 verified direct NAND installation\n";
        if (p1_atomic(P1_WORK "/status",finished,strlen(finished),0600)) rc = -1;
    } else if (!strcmp(argv[1],"boot") && argc == 2 && p1_stock() == 0) {
        rc = boot();
    } else if (!strcmp(argv[1],"clean") && argc == 2 && p1_stock() == 0) {
        rc = clean_flag(1);
    } else if (!strcmp(argv[1],"stock") && argc == 2) {
        rc = remove_stock_hook() || p1_select_bank(1);
    }
 done:
    if (rc && rc != 10) fprintf(stderr,"P1 %s failed\n",argv[1]);
    close(lock);
    return rc == 10 ? 10 : rc ? 1 : 0;
}
