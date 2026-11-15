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
static const char *fault;
static void event(const char *name) { FILE *f=fopen("events","a"); assert(f); fprintf(f,"%s\n",name); fclose(f); }
int p1_state_mount(void) { event("mount"); return 0; }
int p1_state_unmount(void) { event("unmount"); return 0; }
int p1_bundle_write(const char *source) {
    event("write");
    assert(access(P1_FLAG,F_OK));
    assert(!access("selected-stock",F_OK));
    if (!strcmp(fault,"write")) {
        int fd=open("volume",O_WRONLY|O_TRUNC); assert(fd>=0);
        assert(write(fd,"torn update",11)==11); close(fd); return -1;
    }
    unlink("volume"); return fpvos_bootstrap_copy(source,"volume",0600);
}
int p1_bundle_read(const char *destination) {
    event("readback");
    if (!strcmp(fault,"readback")) return -1;
    int rc=fpvos_bootstrap_copy("volume",destination,0600);
    if (!rc && !strcmp(fault,"corrupt")) { int fd=open(destination,O_WRONLY); assert(fd>=0); assert(write(fd,"!",1)==1); close(fd); }
    return rc;
}
/* A boot reads the volume where it lies: the test puts a real bundle there. */
int p1_bundle_open(uint64_t *bytes, char node[64]) {
    event("open");
    /* Like UBI: the volume's whole size, not what the last update wrote. */
    struct stat st; int fd=open("volume",O_RDONLY);
    assert(fd>=0 && !fstat(fd,&st)); *bytes=(uint64_t)st.st_size+(!strcmp(fault,"boot-small") ? 0 : 1000000);
    snprintf(node,64,"/dev/ubi1_0"); return fd;
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
/* What the unit boots and what bank B holds, as the mode names them:
 * "stock-b" is a unit whose own stock runs from bank B, "bad-volume" one
 * whose bundle volume cannot be used. Anything else: fpvOS already in B. */
int p1_active_bank(unsigned *bank) {
    event("active-bank");
    if (!strcmp(fault,"gpt")) return -1;
    *bank = strcmp(fault,"stock-a") ? 1 : 0;
    return 0;
}
int p1_bundle_present(void) {
    event("bundle-present");
    if (!strcmp(fault,"bad-volume")) return -1;
    return strcmp(fault,"stock-b") && strcmp(fault,"stock-a");
}
int p1_select_bank(unsigned bank) { bank = !bank;
    event(bank ? "select-stock" : "activate");
    if ((bank && !strcmp(fault,"select-stock")) || (!bank && !strcmp(fault,"activate"))) return -1;
    if (bank) { int fd=open("selected-stock",O_CREAT|O_WRONLY,0600); assert(fd>=0); close(fd); }
    else { assert(!access("selected-stock",F_OK)); unlink("selected-stock"); }
    return 0;
}
int p1_flash_image(unsigned index,const char *path,int writing) {
    (void)path;
    if (!writing) { event(index ? "compare-dtb" : "compare-kernel"); return 0; }
    assert(!access("selected-stock",F_OK));
    event(index ? "dtb" : "kernel");
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
int main(int argc,char **argv) {
    assert(argc==2);fault=argv[1];
    if (!strncmp(fault,"boot",4)) {
        int rc=boot(); return rc==10 ? 10 : rc ? 1 : 0;
    }
    int rc=transaction("upload");
    return rc ? 1 : 0;
}

int __real_lstat(const char *,struct stat *);
int __wrap_lstat(const char *p,struct stat *s) { int rc=__real_lstat(p,s); if (!rc) s->st_uid=0;return rc; }
