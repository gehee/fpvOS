/* SPDX-License-Identifier: GPL-2.0-or-later */
#define _GNU_SOURCE
#define main p1_nand_main
#include <assert.h>
#include "../../../br-external/package/fpvos-update/backends/p1-air/nand.c"
#undef main
#include <stdarg.h>

const struct fpvos_update_board fpvos_board = {
    .names={"kernel.img","betafpv-p1-air.dtb","rootfs.cpio.gz"},.counts={3,0}
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
int p1_select_bank(unsigned bank) {
    event(bank ? "select-stock" : "activate");
    if ((bank && !strcmp(fault,"select-stock")) || (!bank && !strcmp(fault,"activate"))) return -1;
    if (bank) { int fd=open("selected-stock",O_CREAT|O_WRONLY,0600); assert(fd>=0); close(fd); }
    else { assert(!access("selected-stock",F_OK)); unlink("selected-stock"); }
    return 0;
}
int p1_flash_image(unsigned index,const char *path,int writing) {
    (void)path;assert(writing);assert(!access("selected-stock",F_OK));
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
    if (!strcmp(program,"gzip")) _exit(!strcmp(fault,"gzip"));
    execl("/usr/bin/sha256sum","sha256sum",a,(char *)NULL);_exit(127);
}
int main(int argc,char **argv) {
    assert(argc==2);fault=argv[1];
    int rc=transaction("upload");
    return rc ? 1 : 0;
}

int __real_lstat(const char *,struct stat *);
int __wrap_lstat(const char *p,struct stat *s) { int rc=__real_lstat(p,s); if (!rc) s->st_uid=0;return rc; }
