/* SPDX-License-Identifier: GPL-2.0-or-later */
#define _GNU_SOURCE
#include "p1.h"
#include "board.h"
#include "bootstrap.h"
#include "ar9311-banks.h"
#include "layout.h"
#include <dirent.h>
#include <mtd/mtd-user.h>
#include <sys/ioctl.h>
#include <errno.h>
#include <fcntl.h>
#include <signal.h>
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

/* What each bank holds (ar9311-banks.h), which bank the unit boots, and
 * whether stock is what runs. Asked before anything is selected or written. */
static int banks(int *stock_runtime, unsigned *active, struct ar9311_bank held[2])
{
    *stock_runtime = p1_stock();
    if (*stock_runtime < 0 || p1_active_bank(active)) return -1;
    for (unsigned i = 0; i < 2; i++) {
        held[i].bundle = p1_bundle_present(i);
        held[i].kernel = p1_kernel_kind(i);
    }
    return 0;
}

static const char *holding(const struct ar9311_bank *b)
{
    return ar9311_bank_fpvos(b) ? "its fpvOS" : ar9311_bank_stock(b) ? "its stock" : "what it holds";
}

/* The bank an install writes: the booted fpvOS bank in place, else the bank
 * booted stock does not run from (ar9311_install_bank). The other bank keeps
 * what it holds and is selected while the target is written, so a power cut
 * boots it. */
static int target_bank(unsigned *target)
{
    unsigned active; int stock_runtime; struct ar9311_bank held[2];
    if (banks(&stock_runtime,&active,held)) return -1;
    switch (ar9311_install_bank(stock_runtime,active,held,target)) {
    case AR9311_CHOSEN: break;
    case AR9311_UNUSABLE:
        fprintf(stderr,"P1: bank %u's bundle volume cannot be used; nothing was changed%s\n",*target,
                *target == active && !stock_runtime ? " (it holds the booted fpvOS: boot into update mode)" : "");
        return -1;
    default:
        fprintf(stderr,"P1: booted bank %u holds neither fpvOS nor an intact stock system; "
                "which bank keeps stock cannot be told, so nothing was changed\n",active);
        return -1;
    }
    fprintf(stderr,"P1: booted bank %u; installing on bank %u, bank %u keeps %s\n",active,*target,
            *target ^ 1,holding(&held[*target ^ 1]));
    return 0;
}

/* The bank that holds stock (ar9311_stock_bank). */
static int stock_bank(unsigned *bank)
{
    unsigned active; int stock_runtime; struct ar9311_bank held[2];
    if (banks(&stock_runtime,&active,held)) return -1;
    if (ar9311_stock_bank(stock_runtime,active,held,bank) != AR9311_CHOSEN) {
        fprintf(stderr,"P1: neither bank holds an intact stock system; there is no stock bank to select\n");
        return -1;
    }
    return 0;
}

static int transaction(const char *source)
{
    char directory[] = P1_WORK "/transaction.XXXXXX", package[512], images[512], readback[512], path[1024];
    char before[65], after[65]; int rc = -1;
    if (!mkdtemp(directory)) return -1;
    snprintf(package,sizeof(package),"%s/package.fwu",directory);
    snprintf(images,sizeof(images),"%s/images",directory);
    snprintf(readback,sizeof(readback),"%s/readback.fwu",directory);
    if (fpvos_bootstrap_copy_limit(source,package,0400,fpvos_board.bundle_limits[0]) || verify(package,images) || p1_hash(package,before)) goto done;
    /* Select the bank that is not written before modifying the target. Power
     * loss during installation then boots what it holds (stock); only verified
     * images select the target. No change to environment/U-Boot selection or
     * factory contents. */
    unsigned bank;
    if (target_bank(&bank) || remove_stock_hook() || p1_select_bank(bank ^ 1)) goto done;
    for (unsigned i = 0; i < 2; i++) {
        snprintf(path,sizeof(path),"%s/%s",images,fpvos_board.names[i]);
        if (p1_flash_image(bank,i,path,1)) goto done;
    }
    remove_images(images);
    if (p1_bundle_write(bank,package) || p1_bundle_read(bank,readback) || p1_hash(readback,after) || strcmp(before,after)) goto done;
    int flag = clean_flag(0);
    if (flag < 0 || p1_select_bank(bank)) goto done;
    printf("Verified kernel, DTB and UBI root; fpvOS bank %u selected\n",bank);
    rc = 0;
 done:
    remove_images(images); unlink(package); unlink(readback); rmdir(directory);
    return rc;
}

static int boot(void)
{
    int rc = clean_flag(0);
    if (rc) return rc;
    /* The root comes from the bank SPL booted, and must match its kernel and DTB. */
    unsigned bank;
    if (p1_active_bank(&bank)) return -1;
    const char *package = P1_WORK "/boot.fwu", *images = "/run/fpvos-root";
    if (p1_bundle_read(bank,package) || verify(package,images)) return -1;
    for (unsigned i = 0; i < 2; i++) {
        char path[512]; snprintf(path,sizeof(path),"%s/%s",images,fpvos_board.names[i]);
        if (p1_flash_image(bank,i,path,0)) return -1;
        unlink(path);
    }
    return 0;
}

int fpvos_stock_runtime_valid(void) { return p1_stock() == 1; }

/* What writes the GPT or a bank runs to its end: a reboot from SSH (SIGTERM
 * to all) must not stop it between an erase and the write after it. As the
 * Ascent VRX's install. */
static void hold_signals(void)
{
    signal(SIGHUP,SIG_IGN); signal(SIGINT,SIG_IGN); signal(SIGTERM,SIG_IGN); signal(SIGPIPE,SIG_IGN);
}

/* "nand gpt": both boot-state GPT records as they are, read with no check
 * first (fpvos-diag; the preflight refuses exactly when this is wanted). */
static int print_gpt(void)
{
    DIR *d = opendir("/sys/class/mtd");
    struct dirent *e;
    char path[256], text[64], extra;
    unsigned n, number = 0;
    int found = 0;
    while (d && (e = readdir(d))) {
        if (sscanf(e->d_name,"mtd%u%c",&n,&extra) != 1) continue;
        snprintf(path,sizeof(path),"/sys/class/mtd/mtd%u/name",n);
        FILE *f = fopen(path,"r");
        if (!f) continue;
        int match = fgets(text,sizeof(text),f) && !strcmp(text,"boot-state\n");
        fclose(f);
        if (match) { number = n; found++; }
    }
    if (d) closedir(d);
    if (found != 1) { printf("boot-state: %d MTD partitions by that name\n",found); return 1; }
    snprintf(path,sizeof(path),"/dev/mtd%u",number);
    int fd = open(path,O_RDONLY|O_CLOEXEC);
    if (fd < 0) { printf("boot-state: cannot open %s\n",path); return 1; }
    static unsigned char records[2][AR9311_GPT_BYTES];
    printf("boot-state is %s\n",path);
    for (unsigned slot = 0; slot < 2; slot++) {
        loff_t offset = slot*0x40000;
        int bad = ioctl(fd,MEMGETBADBLOCK,&offset);
        ssize_t got = pread(fd,records[slot],AR9311_GPT_BYTES,offset);
        const unsigned char *g = records[slot], *h = g+512;
        char why[48];
        int valid = got == AR9311_GPT_BYTES && ar9311_gpt_valid(g,slot);
        if (!valid) p1_gpt_problem(g,slot,why,sizeof(why));
        printf("record %u @0x%x: %s%s%s%s\n",slot,slot*0x40000,valid ? "valid" : "INVALID",
               valid ? "" : " (",valid ? "" : (got == AR9311_GPT_BYTES ? why : "read failed"),valid ? "" : ")");
        if (bad) printf("  in a bad block (%d)\n",bad);
        if (got != AR9311_GPT_BYTES) { memset(records[slot],0xff,AR9311_GPT_BYTES); continue; }
        if (memcmp(h,"EFI PART",8)) continue;
        printf("  generation %u  lba my 0x%llx alt 0x%llx usable 0x%llx-0x%llx entries 0x%llx x%u\n",
               (unsigned)fpvos_get_le32(h+20),(unsigned long long)fpvos_get_le64(h+24),(unsigned long long)fpvos_get_le64(h+32),
               (unsigned long long)fpvos_get_le64(h+40),(unsigned long long)fpvos_get_le64(h+48),
               (unsigned long long)fpvos_get_le64(h+72),(unsigned)fpvos_get_le32(h+80));
        for (unsigned i = 0; i < 128; i++) {
            const unsigned char *x = g+1024+128*i;
            int zero = 1, erased = 1;
            for (unsigned j = 0; j < 128; j++) { zero &= !x[j]; erased &= x[j] == 0xff; }
            if (zero || erased) continue;
            char name[37] = {0};
            for (unsigned j = 0; j < 36; j++) name[j] = x[57+2*j] ? '?' : (char)x[56+2*j];
            printf("  %3u %-12s 0x%08llx-0x%08llx flags 0x%llx\n",i,name,
                   (unsigned long long)fpvos_get_le64(x+32)*512,(unsigned long long)(fpvos_get_le64(x+40)+1)*512,
                   (unsigned long long)fpvos_get_le64(x+48));
        }
    }
    close(fd);
    char why[160];
    unsigned record, bank;
    if (p1_layout_why(records,&record,&bank,why,sizeof(why)))
        printf("layout: accepted, record %u, booting bank %u\n",record,bank);
    else
        printf("layout: refused: %s\n",why);
    return 0;
}

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
    if (!strcmp(argv[1],"gpt") && argc == 2) { rc = print_gpt(); goto done; }
    if (p1_preflight()) goto done;
    if (!strcmp(argv[1],"preflight") && argc == 2) {
        puts("P1 NAND layout verified; stock bank and factory contents preserved"); rc = 0;
    } else if (!strcmp(argv[1],"install") && argc == 3) {
        if (!regular(P1_WORK "/clean")) goto done;
        hold_signals();
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
        unsigned bank;
        hold_signals();
        rc = stock_bank(&bank) || remove_stock_hook() || p1_select_bank(bank);
    }
 done:
    if (rc && rc != 10) fprintf(stderr,"P1 %s failed\n",argv[1]);
    close(lock);
    return rc == 10 ? 10 : rc ? 1 : 0;
}
