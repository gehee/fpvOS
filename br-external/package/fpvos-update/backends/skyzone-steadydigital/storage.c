/* SPDX-License-Identifier: GPL-2.0-or-later */
/* SteadyDigital stock A/B layout, UBI storage. Factory and stock bank A are preserved. */
#define _GNU_SOURCE
#include "p1.h"
#include "layout.h"
#include "board.h"
#include <dirent.h>
#include <errno.h>
#include <fcntl.h>
#include <mtd/mtd-user.h>
#include <mtd/ubi-user.h>
#include <stdio.h>
#include <stdlib.h>
#include <sys/ioctl.h>
#include <sys/mount.h>
#include <sys/stat.h>
#include <sys/utsname.h>
#include <sys/wait.h>
#include <unistd.h>

static int stock;
/* The boot chain rewrites stock's bootargs per slot: the stock kernel gets the
 * whole GPT as mtdparts (gpt0 = mtd5 ... userapp1 = mtd18) and ubi.mtd of the
 * slot it booted (17 = userapp0). dtb0's own flat map is never used. Stock is
 * accepted only while it runs from bank A, so bank B is never the live root. */
static const char stock_map[] = "mtdparts=spi32766.1:256k@0(spl0),256k(spl1),256k(spl2),256k(spl3),"
    "256k(gpt0),256k(gpt1),512K(vendor),6M(factory),384K(env0),384K(env1),768K(uboot0),768K(uboot1),"
    "6M(kernel0),6M(kernel1),384K(dtb0),384K(dtb1),45M(userapp0),45M(userapp1),6M(usr_data),6M(usr_log)";

int p1_read(const char *path, char *text, size_t size)
{
    int fd = open(path, O_RDONLY | O_NOFOLLOW | O_CLOEXEC);
    if (fd < 0) return -1;
    ssize_t n = read(fd, text, size-1);
    close(fd);
    if (n <= 0 || (size_t)n >= size-1) return -1;
    text[n] = 0;
    while (n > 0 && text[n-1] == '\n') text[--n] = 0;
    return 0;
}

int p1_exact(int fd, void *buffer, size_t size, off_t offset)
{
    unsigned char *p = buffer;
    while (size) {
        ssize_t n = pread(fd, p, size, offset);
        if (n < 0 && errno == EINTR) continue;
        if (n <= 0) return -1;
        p += n; size -= n; offset += n;
    }
    return 0;
}

/* mtdchar returns the data even where ECC could not correct it, so a plain
 * read cannot tell. Compare the partition's ECC failure count around each
 * read that decides or verifies a write: the SPL stops at a GPT page it
 * cannot read, and loads kernel/DTB as they are. */
int p1_read_checked(int fd, void *buffer, size_t size, off_t offset)
{
    struct mtd_ecc_stats before, after;
    if (ioctl(fd, ECCGETSTATS, &before) || p1_exact(fd, buffer, size, offset) ||
        ioctl(fd, ECCGETSTATS, &after)) return -1;
    return after.failed == before.failed ? 0 : -1;
}

int p1_copy_n(int in, int out, size_t size)
{
    unsigned char buffer[16384];
    while (size) {
        ssize_t n = read(in, buffer, size < sizeof(buffer) ? size : sizeof(buffer));
        if (n < 0 && errno == EINTR) continue;
        if (n <= 0) return -1;
        size_t done = 0;
        while (done < (size_t)n) {
            ssize_t w = write(out, buffer+done, n-done);
            if (w < 0 && errno == EINTR) continue;
            if (w <= 0) return -1;
            done += w;
        }
        size -= n;
    }
    return 0;
}

int p1_hash(const char *path, char hash[65])
{
    int fds[2], status;
    if (pipe2(fds, O_CLOEXEC)) return -1;
    pid_t pid = fork();
    if (!pid) {
        if (dup2(fds[1], 1) < 0) _exit(127);
        close(fds[0]); close(fds[1]);
        execlp("sha256sum", "sha256sum", path, (char *)NULL);
        _exit(127);
    }
    close(fds[1]);
    if (pid < 0) { close(fds[0]); return -1; }
    size_t size = 0;
    while (size < 64) {
        ssize_t n = read(fds[0], hash+size, 64-size);
        if (n < 0 && errno == EINTR) continue;
        if (n <= 0) break;
        size += n;
    }
    char discard[256];
    while (read(fds[0], discard, sizeof(discard)) > 0) {}
    close(fds[0]);
    while (waitpid(pid, &status, 0) < 0) if (errno != EINTR) return -1;
    hash[64] = 0;
    return size == 64 && strspn(hash,"0123456789abcdef") == 64 &&
           WIFEXITED(status) && !WEXITSTATUS(status) ? 0 : -1;
}

static int token(const char *line, const char *word)
{
    size_t n = strlen(word);
    const char *p = strstr(line, word);
    return p && (p == line || p[-1] == ' ') && (!p[n] || p[n] == ' ');
}

int p1_stock(void)
{
    char model[128], cmdline[4096], version[1024];
    struct utsname u;
    if (p1_read("/proc/device-tree/model", model, sizeof(model)) || uname(&u)) return -1;
    if (!strcmp(model,"Skyzone SteadyDigital (AR9311)") && !strncmp(u.release,"6.18.",5)) return 0;
    if (strcmp(model,"Artosyn, Proxima Development Board") || strcmp(u.release,"4.9.38") ||
        p1_read("/proc/cmdline",cmdline,sizeof(cmdline)) || !token(cmdline,stock_map) ||
        !token(cmdline,"ubi.mtd=17,2048") || !token(cmdline,"root=/dev/ubiblock0_0")) return -1;
    if (p1_read("/usr/usrdata/sdk_version.json",version,sizeof(version)) &&
        p1_read("/etc/fpvos-stock-version",version,sizeof(version))) return -1;
    return strstr(version,"A1_GND") ? 1 : -1;
}

int p1_mtd(const char *name, unsigned offset, unsigned size, unsigned *number)
{
    DIR *d = opendir("/sys/class/mtd");
    if (!d) return -1;
    int found = 0;
    struct dirent *e;
    char path[256], text[128], extra;
    unsigned n;
    while ((e = readdir(d))) {
        if (sscanf(e->d_name,"mtd%u%c",&n,&extra) != 1) continue;
        snprintf(path,sizeof(path),"/sys/class/mtd/mtd%u/name",n);
        if (p1_read(path,text,sizeof(text)) || strcmp(text,name)) continue;
        if (found++) { closedir(d); return -1; }
        *number = n;
        snprintf(path,sizeof(path),"/sys/class/mtd/mtd%u/offset",n);
        if (p1_read(path,text,sizeof(text))) {
            if (!stock) { closedir(d); return -1; }
        } else if (strtoul(text,NULL,0) != offset) { closedir(d); return -1; }
    }
    closedir(d);
    if (!found) return -1;
    snprintf(path,sizeof(path),"/dev/mtd%u",*number);
    int fd = open(path,O_RDONLY|O_CLOEXEC|O_NOFOLLOW);
    struct mtd_info_user info;
    if (fd < 0) return -1;
    if (ioctl(fd,MEMGETINFO,&info) || info.type != MTD_NANDFLASH || info.size != size ||
        info.erasesize != 0x20000 || info.writesize != 2048 || info.oobsize != 128) {
        close(fd); return -1;
    }
    return fd;
}

/* The one GPT record, at the start of gpt0 ("boot-state" under fpvOS). */
int p1_gpt_read(unsigned char gpt[SD_GPT_BYTES])
{
    unsigned n;
    int fd = p1_mtd(stock ? "gpt0" : "boot-state",0x100000,stock ? 0x40000 : 0x80000,&n);
    if (fd < 0) return -1;
    loff_t offset = 0;
    int bad = ioctl(fd,MEMGETBADBLOCK,&offset);
    int rc = bad || p1_read_checked(fd,gpt,SD_GPT_BYTES,0);
    close(fd);
    if (rc) {
        if (!bad) fprintf(stderr,"SteadyDigital: the GPT has an uncorrectable ECC error; the unit cannot boot past it\n");
        return -1;
    }
    return sd_layout(gpt,NULL) ? 0 : -1;
}

/* The bank the unit boots: 0 is A, 1 is B. */
int p1_active_bank(unsigned *bank)
{
    unsigned char gpt[SD_GPT_BYTES];
    if (p1_gpt_read(gpt)) return -1;
    return sd_layout(gpt,bank) ? 0 : -1;
}

int p1_preflight(void)
{
    stock = p1_stock();
    if (stock < 0) { fprintf(stderr,"Unrecognized SteadyDigital runtime\n"); return -1; }
    unsigned char gpt[SD_GPT_BYTES];
    if (p1_gpt_read(gpt)) { fprintf(stderr,"Unrecognized SteadyDigital partition layout/selection\n"); return -1; }
    return 0;
}

static int ubi_for(unsigned mtd_number, int attach)
{
    DIR *d = opendir("/sys/class/ubi");
    if (!d) return -1;
    int found = -1;
    struct dirent *e;
    unsigned n;
    char extra,path[256],text[128];
    while ((e = readdir(d))) {
        if (sscanf(e->d_name,"ubi%u%c",&n,&extra) != 1) continue;
        snprintf(path,sizeof(path),"/sys/class/ubi/ubi%u/mtd_num",n);
        if (p1_read(path,text,sizeof(text))) { closedir(d); return -1; }
        if (strtoul(text,NULL,10) != mtd_number) continue;
        if (found >= 0) { closedir(d); return -1; }
        found = (int)n;
    }
    closedir(d);
    if (found >= 0 || !attach) return found;
    int fd = open("/dev/ubi_ctrl",O_RDWR|O_CLOEXEC);
    if (fd < 0) return -1;
    struct ubi_attach_req request = {.ubi_num=UBI_DEV_NUM_AUTO,.mtd_num=mtd_number,.vid_hdr_offset=2048};
    int rc = ioctl(fd,UBI_IOCATT,&request);
    close(fd);
    return rc ? -1 : request.ubi_num;
}

static int volume(int data, int writing, char node[64])
{
    unsigned number;
    int fd = p1_mtd(data ? "usr_data" : "userapp1",data ? 0x7100000 : 0x4400000,
                 data ? 0x600000 : 0x2d00000,&number);
    if (fd < 0) return -1;
    close(fd);
    int ubi = ubi_for(number,1);
    if (ubi < 0) return -1;
    char path[256],text[128];
    snprintf(path,sizeof(path),"/sys/class/ubi/ubi%d/ro_mode",ubi);
    if (p1_read(path,text,sizeof(text)) || strcmp(text,"0")) return -1;
    /* Stock names the volumes: MTD usr_data holds "usr_data", userapp1
     * (bank B) holds "userapp". */
    snprintf(path,sizeof(path),"/sys/class/ubi/ubi%d_0/name",ubi);
    if (p1_read(path,text,sizeof(text)) || strcmp(text,data ? "usr_data" : "userapp")) return -1;
    snprintf(path,sizeof(path),"/sys/class/ubi/ubi%d_0/type",ubi);
    if (p1_read(path,text,sizeof(text)) || strcmp(text,"dynamic")) return -1;
    snprintf(node,64,"/dev/ubi%d_0",ubi);
    if (!data) {
        snprintf(path,sizeof(path),"/sys/class/ubi/ubi%d_0/reserved_ebs",ubi);
        /* Room for the largest bundle (stock reserves 347 LEBs). */
        if (p1_read(path,text,sizeof(text)) ||
            strtoul(text,NULL,10) < (fpvos_board.bundle_limits[0]+126975)/126976) return -1;
        snprintf(path,sizeof(path),"/sys/class/ubi/ubi%d_0/usable_eb_size",ubi);
        if (p1_read(path,text,sizeof(text)) || strcmp(text,"126976")) return -1;
        /* Kernel UBI update also refuses a volume in use, including ubiblock. */
        char block[64];
        snprintf(block,sizeof(block),"/sys/class/block/ubiblock%d_0",ubi);
        if (access(block,F_OK) == 0) return -1;
    }
    /* Stock uses asynchronous mdev hotplug after UBI_IOCATT. Wait only
     * for its character node; all layout/volume checks above still apply. */
    for (unsigned attempt = 0; attempt < 50; attempt++) {
        int result = open(node,(writing ? O_RDWR : O_RDONLY)|O_CLOEXEC|O_NOFOLLOW);
        if (result >= 0 || errno != ENOENT) return result;
        usleep(100000);
    }
    perror(node);
    return -1;
}

int p1_bundle_read(const char *destination)
{
    char node[64];
    int in = volume(0,0,node);
    if (in < 0) return -1;
    unsigned char header[512];
    if (p1_exact(in,header,sizeof(header),0) || memcmp(header,"FPVOSUP1",8)) { close(in); return -1; }
    unsigned bytes = fpvos_get_le32(header+16);
    if (bytes < 512 || bytes > fpvos_board.bundle_limits[0]) { close(in); return -1; }
    int out = open(destination,O_CREAT|O_EXCL|O_WRONLY|O_CLOEXEC|O_NOFOLLOW,0600);
    int rc = out < 0 ? -1 : p1_copy_n(in,out,bytes);
    close(in);
    if (out >= 0) close(out);
    return rc;
}

/* What bank B's bundle volume holds, asked before anything is selected or
 * written: 1 an fpvOS bundle, 0 anything else (stock's own userapp), -1 the
 * volume is not the expected one or cannot be written. */
int p1_bundle_present(void)
{
    char node[64];
    int fd = volume(0,1,node);
    if (fd < 0) return -1;
    unsigned char header[512];
    int present = !p1_exact(fd,header,sizeof(header),0) && !memcmp(header,"FPVOSUP1",8);
    close(fd);
    return present;
}

int p1_bundle_write(const char *source)
{
    int in = open(source,O_RDONLY|O_CLOEXEC|O_NOFOLLOW);
    struct stat st;
    if (in < 0) return -1;
    if (fstat(in,&st) || !S_ISREG(st.st_mode) || st.st_size < 512 ||
        st.st_size > fpvos_board.bundle_limits[0]) { close(in); return -1; }
    char node[64];
    int out = volume(0,1,node);
    if (out < 0) { close(in); return -1; }
    __s64 bytes = st.st_size;
    int rc = ioctl(out,UBI_IOCVOLUP,&bytes) || p1_copy_n(in,out,(size_t)bytes) || fsync(out);
    close(out); close(in);
    return rc ? -1 : 0;
}

int p1_state_mount(void)
{
    char node[64];
    int fd = volume(1,0,node);
    if (fd < 0) return -1;
    close(fd);
    if (mkdir(P1_STATE,0700) && errno != EEXIST) return -1;
    struct stat st;
    if (lstat(P1_STATE,&st) || !S_ISDIR(st.st_mode) || st.st_uid || (st.st_mode&077)) return -1;
    /* Never accept an existing mount at our private mountpoint. */
    FILE *f = fopen("/proc/mounts","r");
    if (!f) return -1;
    char line[2048], point[512];
    while (fgets(line,sizeof(line),f))
        if (sscanf(line,"%*s %511s",point)==1 && !strcmp(point,P1_STATE)) { fclose(f); return -1; }
    fclose(f);
    return mount(node,P1_STATE,"ubifs",MS_NODEV|MS_NOSUID|MS_NOEXEC,NULL);
}

int p1_state_unmount(void) { return umount(P1_STATE); }

int p1_atomic(const char *path, const void *data, size_t size, unsigned mode)
{
    char parent[512], temporary[600];
    if (strlen(path) >= sizeof(parent)) return -1;
    strcpy(parent,path);
    char *slash = strrchr(parent,'/');
    if (!slash) return -1;
    *slash = 0;
    int directory = open(parent,O_RDONLY|O_DIRECTORY|O_NOFOLLOW|O_CLOEXEC);
    if (directory < 0) return -1;
    snprintf(temporary,sizeof(temporary),"%s.tmp.XXXXXX",path);
    int fd = mkstemp(temporary), rc = fd < 0;
    if (fd >= 0) {
        const unsigned char *p = data;
        while (size && !rc) {
            ssize_t n = write(fd,p,size);
            if (n < 0 && errno == EINTR) continue;
            if (n <= 0) rc = -1;
            else { p += n; size -= n; }
        }
        if (!rc) rc = fchmod(fd,mode) || fsync(fd);
        if (close(fd)) rc = -1;
        if (!rc) rc = rename(temporary,path) || fsync(directory);
        if (rc) unlink(temporary);
    }
    close(directory);
    return rc ? -1 : 0;
}
