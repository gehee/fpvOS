/* SPDX-License-Identifier: GPL-2.0-or-later */
#define _GNU_SOURCE
#include "p1.h"
#include "board.h"
#include "bootstrap.h"
#include "fpvos-bundle.h"
#include "root.h"
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

/* Where a boot leaves the root for the recovery init: rootfs.squashfs, a link
 * to the block device over the root in the bundle volume, and
 * installed-sha256. A host test points it into its own directory. */
#ifndef P1_ROOT
#define P1_ROOT "/run/fpvos-root"
#endif

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

/* The bundle's header, each image's SHA-256 and the root's squashfs
 * superblock (fpvos-update-verify). */
static int verify(const char *package, const char *directory)
{
    return mkdir(directory,0700) || execute("/usr/libexec/fpvos-update-verify",package,directory) ? -1 : 0;
}

/* What the last install put in the bundle volume: the bundle's SHA-256 and its
 * header's CRC, "<sha256> <crc32 hex>". A boot reads the header, not the
 * whole bundle, and reports this hash as what is installed. */
#define P1_INSTALLED P1_STATE "/fpvos-installed"

/* The clean flag with the state volume already mounted: action 1 sets it, 0
 * consumes it (10: it was set). */
static int clean_flag_mounted(int action)
{
    const char *path = P1_STATE "/fpvos-update-clean";
    char value[16]; int rc = 0;
    if (action == 1) rc = p1_atomic(path,"1\n",2,0600);
    else if (access(path,F_OK) == 0) {
        if (!regular(path) || p1_read(path,value,sizeof(value)) || strcmp(value,"1")) rc = -1;
        else if (unlink(path)) rc = -1;
        else rc = 10;
    } else if (errno != ENOENT) rc = -1;
    return rc;
}

static int clean_flag(int action)
{
    if (p1_state_mount()) return -1;
    int rc = clean_flag_mounted(action);
    sync();
    if (p1_state_unmount()) rc = -1;
    return rc;
}

static int installed_write(const char *sha, unsigned crc)
{
    char text[80];
    snprintf(text,sizeof(text),"%s %08x\n",sha,crc);
    if (p1_state_mount()) return -1;
    int rc = p1_atomic(P1_INSTALLED,text,strlen(text),0600);
    sync();
    if (p1_state_unmount()) rc = -1;
    return rc;
}

static int installed_read_mounted(char sha[65], unsigned *crc)
{
    char text[128];
    if (!regular(P1_INSTALLED) || p1_read(P1_INSTALLED,text,sizeof(text)) || strlen(text) != 73 ||
        strspn(text,"0123456789abcdef") != 64 || text[64] != ' ' ||
        strspn(text+65,"0123456789abcdef") != 8) return -1;
    memcpy(sha,text,64); sha[64] = 0;
    *crc = (unsigned)strtoul(text+65,NULL,16);
    return 0;
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

/* The staged bundle, up to the board's bundle limit: the shared bootstrap
 * copier stops at 16 MiB and this board's bundle (Kestrel runtime included)
 * is larger. */
static int copy_package(const char *source, const char *destination)
{
    int in = open(source,O_RDONLY|O_CLOEXEC|O_NOFOLLOW), rc = -1;
    struct stat st;
    if (in < 0) return -1;
    if (!fstat(in,&st) && S_ISREG(st.st_mode) && st.st_size >= 512 &&
        (unsigned long long)st.st_size <= fpvos_board.bundle_limits[0]) {
        int out = open(destination,O_WRONLY|O_CREAT|O_EXCL|O_NOFOLLOW|O_CLOEXEC,0400);
        if (out >= 0) {
            rc = p1_copy_n(in,out,(size_t)st.st_size);
            if (close(out)) rc = -1;
        }
    }
    close(in);
    return rc ? -1 : 0;
}

/* Bank B is ours to write only when it is not what the unit runs: either
 * bank A is the active one, or bank B already holds fpvOS. An active bank B
 * without an fpvOS bundle is the unit's own stock (a vendor update moved it
 * there), and bank A then holds an older copy nobody has checked. Its bundle
 * volume is checked here too, so a volume that cannot take the bundle is
 * found before the bank selection is touched. */
static int bank_b_free(void)
{
    unsigned bank;
    if (p1_active_bank(&bank)) return -1;
    int fpvos = p1_bundle_present();
    if (fpvos < 0) {
        fprintf(stderr,"SteadyDigital: bank B's bundle volume cannot be used; nothing was changed\n");
        return -1;
    }
    if (bank == 1 && !fpvos) {
        fprintf(stderr,"SteadyDigital: bank B is the active bank and does not hold fpvOS: "
                       "it is the unit's stock firmware; nothing was changed\n");
        return -1;
    }
    return 0;
}

static int transaction(const char *source)
{
    char directory[] = P1_WORK "/transaction.XXXXXX", package[512], images[512], readback[512], path[1024];
    char before[65], after[65]; unsigned char header[512]; int rc = -1;
    if (!mkdtemp(directory)) return -1;
    snprintf(package,sizeof(package),"%s/package.fwu",directory);
    snprintf(images,sizeof(images),"%s/images",directory);
    snprintf(readback,sizeof(readback),"%s/readback.fwu",directory);
    int fd = -1;
    if (copy_package(source,package) || verify(package,images) || p1_hash(package,before) ||
        (fd = open(package,O_RDONLY|O_CLOEXEC|O_NOFOLLOW)) < 0) goto done;
    int got = p1_exact(fd,header,sizeof(header),0);
    close(fd);
    if (got) goto done;
    if (bank_b_free()) goto done;
    /* Select the untouched stock bank A (0) before modifying bank B (1). Power
     * loss during installation then boots stock; only verified images reactivate
     * fpvOS. No change to environment/U-Boot selection or factory contents. */
    if (remove_stock_hook() || p1_select_bank(0)) goto done;
    for (unsigned i = 0; i < 2; i++) {
        snprintf(path,sizeof(path),"%s/%s",images,fpvos_board.names[i]);
        if (p1_flash_image(i,path,1)) goto done;
    }
    remove_images(images);
    if (p1_bundle_write(package) || p1_bundle_read(readback) || p1_hash(readback,after) || strcmp(before,after) ||
        installed_write(before,fpvos_get_le32(header+508))) goto done;
    int flag = clean_flag(0);
    if (flag < 0 || p1_select_bank(1)) goto done;
    puts("Verified kernel, DTB and UBI root; fpvOS bank B selected");
    rc = 0;
 done:
    remove_images(images); unlink(package); unlink(readback); rmdir(directory);
    return rc;
}

static int save(const char *path, const void *data, size_t size)
{
    int fd = open(path,O_WRONLY|O_CREAT|O_EXCL|O_NOFOLLOW|O_CLOEXEC,0600), rc = fd < 0;
    if (fd >= 0) {
        const unsigned char *p = data;
        while (size && !rc) {
            ssize_t n = write(fd,p,size);
            if (n < 0 && errno == EINTR) continue;
            if (n <= 0) rc = 1; else { p += n; size -= n; }
        }
        if (close(fd)) rc = 1;
    }
    return rc ? -1 : 0;
}

/* The root is mounted where it lies in the bundle volume, so a boot reads
 * only what proves the bundle is the installed one and fits this kernel: the
 * header (CRC as recorded at install), the DTB (hash, and the same as dtb1),
 * the kernel's first 4 KiB (its image headers, with the data CRC, the same as
 * kernel1's) and the root's superblock. The whole bundle was hashed and read
 * back from flash when it was installed; reading it again cost ~3.5 s of
 * every boot, and unpacking the root into RAM another ~3 s and 20 MB. */
static int boot(void)
{
    char sha[65], hash[65], node[64], device[64], path[1024];
    unsigned crc;
    if (p1_state_mount()) return -1;
    int rc = clean_flag_mounted(0);
    if (!rc && installed_read_mounted(sha,&crc)) {
        fprintf(stderr,"SteadyDigital: no install record\n");
        rc = -1;
    }
    sync();
    if (p1_state_unmount()) rc = -1;
    if (rc) return rc;

    uint64_t capacity;
    unsigned char header[512], head[4096], superblock[SD_ROOT_SUPERBLOCK], *dtb = NULL;
    int fd = p1_bundle_open(&capacity,node);
    if (fd < 0) return -1;
    rc = -1;
    /* A dynamic volume keeps no length of its last update: the header says
     * how long the bundle is, and it must fit. */
    if (p1_exact(fd,header,sizeof(header),0) || fpvos_get_le32(header+16) > capacity ||
        !fpvos_bundle_header_valid(header,fpvos_get_le32(header+16)) ||
        fpvos_get_le32(header+88) || fpvos_get_le32(header+508) != crc) {
        fprintf(stderr,"SteadyDigital: the bundle volume does not hold the installed bundle\n");
        goto done;
    }
    uint32_t kernel = fpvos_get_le32(FPVOS_BUNDLE_ENTRY(header,0)+32),
             tree = fpvos_get_le32(FPVOS_BUNDLE_ENTRY(header,1)+32),
             root = fpvos_get_le32(FPVOS_BUNDLE_ENTRY(header,2)+32);
    size_t first = kernel < sizeof(head) ? kernel : sizeof(head);
    if (mkdir(P1_ROOT,0700) || !(dtb = malloc(tree))) goto done;
    snprintf(path,sizeof(path),"%s/kernel-head",P1_ROOT);
    if (p1_exact(fd,head,first,512) || save(path,head,first) || p1_flash_image(0,path,0)) goto done;
    unlink(path);
    snprintf(path,sizeof(path),"%s/%s",P1_ROOT,fpvos_board.names[1]);
    if (p1_exact(fd,dtb,tree,512+(off_t)kernel) || !fpvos_board_image_valid(1,dtb,tree,0) ||
        save(path,dtb,tree) || p1_hash(path,hash) || memcmp(hash,FPVOS_BUNDLE_ENTRY(header,1)+36,64) ||
        p1_flash_image(1,path,0)) goto done;
    unlink(path);
    off_t offset = 512+(off_t)kernel+tree;
    if (p1_exact(fd,superblock,sizeof(superblock),offset) || !sd_root_valid(superblock,sizeof(superblock),root) ||
        p1_root_attach(fd,node,(uint64_t)offset,root,device)) goto done;
    snprintf(path,sizeof(path),"%s/%s",P1_ROOT,fpvos_board.names[2]);
    if (symlink(device,path)) goto done;
    snprintf(path,sizeof(path),"%s/installed-sha256",P1_ROOT);
    sha[64] = '\n';
    if (save(path,sha,65)) goto done;
    rc = 0;
 done:
    free(dtb);
    close(fd);
    return rc;
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
        puts("SteadyDigital NAND layout verified; bank A (stock) and factory contents preserved"); rc = 0;
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
        rc = remove_stock_hook() || p1_select_bank(0);
    }
 done:
    if (rc && rc != 10) fprintf(stderr,"SteadyDigital %s failed\n",argv[1]);
    close(lock);
    return rc == 10 ? 10 : rc ? 1 : 0;
}
