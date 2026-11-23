/* SPDX-License-Identifier: GPL-2.0-or-later */
/* The SteadyDigital install transaction (backends/skyzone-steadydigital/nand.c)
 * with its storage replaced by files and events; see test_steadydigital.py. */
#define _GNU_SOURCE
#define main p1_nand_main
#include <assert.h>
#include "nand.c"
#undef main
#include <stdarg.h>

const struct fpvos_update_board fpvos_board = {
    .names={"kernel.img","skyzone-steadydigital.dtb","rootfs.squashfs"},.limits={6291456,65536,25165824},
    .counts={3,0},.bundle_limits={33554432,512}
};
const struct fpvos_bootstrap_file fpvos_bootstrap_files[] = {
    {"root/usr/share/fpvos-update/boot.sh",(const unsigned char *)"boot",4,0600},
    {"root/usr/share/fpvos-update/clean.sh",(const unsigned char *)"clean",5,0600}
};
const size_t fpvos_bootstrap_file_count = 2;
/* argv: FAULT [BANKS]. BANKS is the booted bank and what each bank's volume
 * holds, e.g. "1sf": booted bank 1, bank 0 stock, bank 1 fpvOS ('s' stock,
 * 'f' fpvOS, 'b' an unusable volume). Each bank's volume is volume<N>. */
static const char *fault, *scenario;
static int wrote;
static void event(const char *name) { FILE *f=fopen("events","a"); assert(f); fprintf(f,"%s\n",name); fclose(f); }
static void eventf(const char *name,unsigned bank) { char line[64]; snprintf(line,sizeof(line),"%s@%u",name,bank); event(line); }
/* The bank selected while the target is written; nothing may be written to it. */
static int selected(void) { FILE *f=fopen("selected-stock","r"); if (!f) return -1; int b=fgetc(f)-'0'; fclose(f); return b; }
static void volume_name(unsigned bank,char path[16]) { snprintf(path,16,"volume%u",bank); }
int p1_state_mount(void) { event("mount"); return 0; }
int p1_state_unmount(void) { event("unmount"); return 0; }
int p1_bundle_write(unsigned bank,const char *source) {
    event("write"); eventf("write",bank);
    assert(access(P1_FLAG,F_OK));
    assert(selected() >= 0 && (unsigned)selected() != bank);
    char path[16]; volume_name(bank,path);
    wrote = 1;
    if (!strcmp(fault,"write")) {
        int fd=open(path,O_WRONLY|O_TRUNC); assert(fd>=0);
        assert(write(fd,"torn update",11)==11); close(fd); return -1;
    }
    unlink(path); return fpvos_bootstrap_copy(source,path,0600);
}
int p1_bundle_read(unsigned bank,const char *destination) {
    event("readback"); eventf("readback",bank);
    if (!strcmp(fault,"readback")) return -1;
    char path[16]; volume_name(bank,path);
    int rc=fpvos_bootstrap_copy(path,destination,0600);
    if (!rc && !strcmp(fault,"corrupt")) { int fd=open(destination,O_WRONLY); assert(fd>=0); assert(write(fd,"!",1)==1); close(fd); }
    return rc;
}
/* A boot reads the volume where it lies: the test puts a real bundle there. */
int p1_bundle_open(unsigned bank,uint64_t *bytes, char node[64]) {
    event("open"); eventf("open",bank);
    char path[16]; volume_name(bank,path);
    /* Like UBI: the volume's whole size, not what the last update wrote. */
    struct stat st; int fd=open(path,O_RDONLY);
    assert(fd>=0 && !fstat(fd,&st)); *bytes=(uint64_t)st.st_size+(!strcmp(fault,"boot-small") ? 0 : 1000000);
    snprintf(node,64,"/dev/ubi%u_0",bank); return fd;
}
int p1_root_attach(int fd, const char *node, uint64_t offset, uint64_t size, char device[64]) {
    (void)fd;(void)node;
    FILE *f=fopen("attached","w"); assert(f); fprintf(f,"%llu %llu\n",(unsigned long long)offset,(unsigned long long)size); fclose(f);
    event("attach");
    if (!strcmp(fault,"boot-attach")) return -1;
    snprintf(device,64,"/dev/loop7"); return 0;
}
int fpvos_board_image_valid(unsigned index, const unsigned char *data, size_t size, unsigned kind) {
    (void)data;(void)size;(void)kind; event(index==1 ? "dtb-valid" : "image-valid"); return 1;
}
int p1_active_bank(unsigned *bank) {
    event("active-bank");
    if (!strcmp(fault,"gpt")) return -1;
    *bank = scenario[0]-'0';
    return 0;
}
int p1_bundle_present(unsigned bank) {
    event("bundle-present"); eventf("bundle-present",bank);
    char held = scenario[1+bank];
    return held == 'b' ? -1 : held == 'f';
}
int p1_select_bank(unsigned bank) {
    if (!wrote) {
        /* Before any write: the bank kept as it is, booted if power is cut. */
        event("select-stock"); eventf("select-stock",bank);
        if (!strcmp(fault,"select-stock")) return -1;
        FILE *f=fopen("selected-stock","w"); assert(f); fprintf(f,"%u",bank); fclose(f);
    } else {
        event("activate"); eventf("activate",bank);
        if (!strcmp(fault,"activate")) return -1;
        assert(selected() >= 0 && (unsigned)selected() != bank);
        unlink("selected-stock");
    }
    return 0;
}
int p1_flash_image(unsigned bank,unsigned index,const char *path,int writing) {
    (void)path;
    if (!writing) { event(index ? "compare-dtb" : "compare-kernel"); eventf(index ? "compare-dtb" : "compare-kernel",bank); return 0; }
    assert(selected() >= 0 && (unsigned)selected() != bank);
    event(index ? "dtb" : "kernel"); eventf(index ? "dtb" : "kernel",bank);
    wrote = 1;
    return !strcmp(fault,index ? "dtb" : "kernel") ? -1 : 0;
}
int __wrap_execlp(const char *program,const char *arg,...) {
    (void)arg;
    va_list ap;va_start(ap,arg);const char *a=va_arg(ap,const char *);const char *b=va_arg(ap,const char *);va_end(ap);
    if (!strcmp(program,"/usr/libexec/fpvos-update-verify")) {
        event("verify");
        if (!strcmp(fault,"verify")) _exit(1);
        /* Mutate the upload after snapshot verification. The volume must still
         * receive the private snapshot, never the replaced upload. */
        if (!strcmp(fault,"mutate")) { int fd=open("upload",O_WRONLY|O_TRUNC); assert(fd>=0); assert(write(fd,"changed",7)==7);close(fd); }
        for (int i=0;i<3;i++) { char path[1024];snprintf(path,sizeof(path),"%s/%s",b,fpvos_board.names[i]);int fd=open(path,O_CREAT|O_WRONLY,0600);assert(fd>=0);close(fd); }
        _exit(0);
    }
    if (!strcmp(program,"gzip")) { event("gzip"); _exit(!strcmp(fault,"gzip")); }
    execl("/usr/bin/sha256sum","sha256sum",a,(char *)NULL);_exit(127);
}
/* FAULT [BANKS]: an install; "boot..." runs a boot, "stock" the stock command. */
int main(int argc,char **argv) {
    assert(argc==2 || argc==3);fault=argv[1];scenario=argc==3 ? argv[2] : "1sf";
    assert(strlen(scenario)==3 && (scenario[0]=='0' || scenario[0]=='1'));
    if (!strncmp(fault,"boot",4)) {
        int rc=boot(); return rc==10 ? 10 : rc ? 1 : 0;
    }
    if (!strcmp(fault,"stock")) {
        unsigned bank;
        if (stock_bank(&bank)) return 1;
        printf("stock bank %u\n",bank);
        return 0;
    }
    int rc=transaction("upload");
    return rc ? 1 : 0;
}

int __real_lstat(const char *,struct stat *);
int __wrap_lstat(const char *p,struct stat *s) { int rc=__real_lstat(p,s); if (!rc) s->st_uid=0;return rc; }
