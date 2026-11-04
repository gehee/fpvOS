/*
 * libsns_ps5280.so — GT Pro (board 4861) PrimeSensor PS5280 driver.
 *
 * The stock sky app links the CMOS driver statically. There is no public
 * CV610 source, so this .so maps /usrdata/fpv/ar_ldyhs_sky at its preferred
 * load address, resolves its libc PLT, and redirects the seven MPI entry
 * points the sensor calls into the process's libss_mpi / libot_mpi (the
 * same copies kestrel-air already uses). g_sns_ps5280_obj is then the
 * stock 2-lane vtable.
 *
 * kestrel-air is PIE, so 0x10000 is free. Camera failure stays radio-only.
 */
#define _GNU_SOURCE
#include <dlfcn.h>
#include <elf.h>
#include <errno.h>
#include <fcntl.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/mman.h>
#include <sys/stat.h>
#include <unistd.h>

#define STOCK_PATH   "/usrdata/fpv/ar_ldyhs_sky"
#define STOCK_SIZE   2478136u          /* GT 18.21.7 */
#define OBJ_VADDR    0x267be4u         /* g_sns_ps5280_obj, 2-lane */
#define OBJ_EXPECT0  0x000f3b89u       /* register_callback (thumb) */

#define PAGE 0x1000u
#define ALIGN_DOWN(x, a) ((x) & ~((a) - 1u))
#define ALIGN_UP(x, a)   (((x) + ((a) - 1u)) & ~((a) - 1u))

typedef int32_t (*sns_reg_fn)(int32_t, void *, void *);
typedef int32_t (*sns_bus_fn)(int32_t, int8_t);
typedef void    (*sns_mf_fn)(int32_t, uint32_t);

typedef struct {
    sns_reg_fn pfn_register_callback;
    sns_reg_fn pfn_un_register_callback;
    sns_bus_fn pfn_set_bus_info;
    void *rsv_12;
    void *pfn_standby;
    void *pfn_restart;
    sns_mf_fn pfn_mirror_flip;
    void *rsv_28;
    void *pfn_write_reg;
    void *pfn_read_reg;
    void *rsv_40;
    void *rsv_44;
} ot_isp_sns_obj;

ot_isp_sns_obj g_sns_ps5280_obj;

static int32_t fail_reg(int32_t pipe, void *ae, void *awb)
{
    (void)pipe; (void)ae; (void)awb;
    fprintf(stderr, "[ps5280] stock driver not loaded\n");
    return -1;
}

static int32_t fail_bus(int32_t pipe, int8_t bus)
{
    (void)pipe; (void)bus;
    return -1;
}

static void *find_sym(const char *primary, const char *alt)
{
    void *p = dlsym(RTLD_DEFAULT, primary);
    if (!p && alt)
        p = dlsym(RTLD_DEFAULT, alt);
    if (!p)
        fprintf(stderr, "[ps5280] missing %s\n", primary);
    return p;
}

static int hook_thumb(uint32_t from, void *to)
{
    if (!to)
        return -1;
    /* Stock MPI is Thumb-2 (even symbol, push.w / push). ldr.w pc,[pc]
     * at a 4-aligned site loads the following word; LSB of `to` selects
     * Thumb on the real libss/libot copy. */
    if (from & 3) {
        fprintf(stderr, "[ps5280] hook %x not 4-aligned\n", from);
        return -1;
    }
    uintptr_t page = ALIGN_DOWN(from, PAGE);
    if (mprotect((void *)page, PAGE * 2, PROT_READ | PROT_WRITE | PROT_EXEC) != 0) {
        fprintf(stderr, "[ps5280] mprotect %x: %s\n", from, strerror(errno));
        return -1;
    }
    uint32_t *p = (uint32_t *)from;
    p[0] = 0xf000f8df;              /* ldr.w pc, [pc] */
    /* Real MPI is Thumb; dlsym may return an even st_value. */
    p[1] = (uint32_t)(uintptr_t)to | 1u;
    __builtin___clear_cache((char *)p, (char *)(p + 2));
    return 0;
}

static const Elf32_Dyn *dyn_get(const Elf32_Dyn *d, int32_t tag)
{
    for (; d->d_tag; d++)
        if (d->d_tag == tag)
            return d;
    return NULL;
}

static int apply_relocs(const Elf32_Ehdr *eh, const uint8_t *file, size_t flen)
{
    const Elf32_Phdr *ph = (const Elf32_Phdr *)(file + eh->e_phoff);
    const Elf32_Dyn *dyn = NULL;
    for (int i = 0; i < eh->e_phnum; i++) {
        if (ph[i].p_type == PT_DYNAMIC) {
            dyn = (const Elf32_Dyn *)(uintptr_t)ph[i].p_vaddr;
            break;
        }
    }
    if (!dyn)
        return -1;

    const Elf32_Dyn *d_sym = dyn_get(dyn, DT_SYMTAB);
    const Elf32_Dyn *d_str = dyn_get(dyn, DT_STRTAB);
    const Elf32_Dyn *d_rel = dyn_get(dyn, DT_REL);
    const Elf32_Dyn *d_relsz = dyn_get(dyn, DT_RELSZ);
    const Elf32_Dyn *d_jmprel = dyn_get(dyn, DT_JMPREL);
    const Elf32_Dyn *d_pltrelsz = dyn_get(dyn, DT_PLTRELSZ);
    if (!d_sym || !d_str)
        return -1;

    const Elf32_Sym *symtab = (const Elf32_Sym *)(uintptr_t)d_sym->d_un.d_ptr;
    const char *strtab = (const char *)(uintptr_t)d_str->d_un.d_ptr;

    const Elf32_Rel *blocks[2] = { 0 };
    size_t counts[2] = { 0 };
    int nblk = 0;
    if (d_rel && d_relsz) {
        blocks[nblk] = (const Elf32_Rel *)(uintptr_t)d_rel->d_un.d_ptr;
        counts[nblk] = d_relsz->d_un.d_val / sizeof(Elf32_Rel);
        nblk++;
    }
    if (d_jmprel && d_pltrelsz) {
        blocks[nblk] = (const Elf32_Rel *)(uintptr_t)d_jmprel->d_un.d_ptr;
        counts[nblk] = d_pltrelsz->d_un.d_val / sizeof(Elf32_Rel);
        nblk++;
    }

    (void)flen;
    for (int b = 0; b < nblk; b++) {
        for (size_t i = 0; i < counts[b]; i++) {
            const Elf32_Rel *r = &blocks[b][i];
            unsigned type = ELF32_R_TYPE(r->r_info);
            unsigned si = ELF32_R_SYM(r->r_info);
            uint32_t *where = (uint32_t *)(uintptr_t)r->r_offset;
            const char *name = (si && strtab) ? strtab + symtab[si].st_name : "";
            void *val = NULL;

            switch (type) {
            case R_ARM_RELATIVE:
                /* ET_EXEC mapped at p_vaddr: already relocated. */
                break;
            case R_ARM_GLOB_DAT:
            case R_ARM_JUMP_SLOT:
            case R_ARM_ABS32:
                if (!name[0])
                    break;
                val = dlsym(RTLD_DEFAULT, name);
                if (!val && type != R_ARM_ABS32)
                    fprintf(stderr, "[ps5280] reloc %s failed\n", name);
                if (val)
                    *where = (uint32_t)(uintptr_t)val;
                break;
            case R_ARM_COPY:
                val = dlsym(RTLD_DEFAULT, name);
                if (val && symtab[si].st_size)
                    memcpy(where, val, symtab[si].st_size);
                break;
            default:
                break;
            }
        }
    }
    return 0;
}

static int map_stock(const char *path)
{
    int fd = open(path, O_RDONLY);
    if (fd < 0) {
        fprintf(stderr, "[ps5280] open %s: %s\n", path, strerror(errno));
        return -1;
    }
    struct stat st;
    if (fstat(fd, &st) != 0) {
        close(fd);
        return -1;
    }
    uint8_t ehbuf[sizeof(Elf32_Ehdr)];
    if (read(fd, ehbuf, sizeof(ehbuf)) != (ssize_t)sizeof(ehbuf)) {
        close(fd);
        return -1;
    }
    const Elf32_Ehdr *eh = (const Elf32_Ehdr *)ehbuf;
    if (memcmp(eh->e_ident, ELFMAG, SELFMAG) != 0 || eh->e_machine != EM_ARM) {
        fprintf(stderr, "[ps5280] %s is not ARM ELF\n", path);
        close(fd);
        return -1;
    }
    size_t phsz = (size_t)eh->e_phnum * eh->e_phentsize;
    uint8_t *phbuf = malloc(phsz);
    if (!phbuf || lseek(fd, eh->e_phoff, SEEK_SET) < 0 ||
        read(fd, phbuf, phsz) != (ssize_t)phsz) {
        free(phbuf);
        close(fd);
        return -1;
    }
    const Elf32_Phdr *ph = (const Elf32_Phdr *)phbuf;
    for (int i = 0; i < eh->e_phnum; i++) {
        if (ph[i].p_type != PT_LOAD || ph[i].p_memsz == 0)
            continue;
        uintptr_t vaddr = ph[i].p_vaddr;
        uintptr_t page = ALIGN_DOWN(vaddr, PAGE);
        size_t lead = (size_t)(vaddr - page);
        size_t total = ALIGN_UP(lead + ph[i].p_memsz, PAGE);
        void *m = mmap((void *)page, total,
                       PROT_READ | PROT_WRITE | PROT_EXEC,
                       MAP_PRIVATE | MAP_ANONYMOUS | MAP_FIXED, -1, 0);
        if (m == MAP_FAILED) {
            fprintf(stderr, "[ps5280] mmap %lx+%zx: %s\n",
                    (unsigned long)page, total, strerror(errno));
            free(phbuf);
            close(fd);
            return -1;
        }
        if (ph[i].p_filesz) {
            if (lseek(fd, ph[i].p_offset, SEEK_SET) < 0 ||
                read(fd, (uint8_t *)m + lead, ph[i].p_filesz) != (ssize_t)ph[i].p_filesz) {
                fprintf(stderr, "[ps5280] read segment %d failed\n", i);
                free(phbuf);
                close(fd);
                return -1;
            }
        }
    }
    /* Relocs need a view of the ELF header fields; use the mapped image. */
    const Elf32_Ehdr *mapped_eh = (const Elf32_Ehdr *)(uintptr_t)0x10000;
    int rc = apply_relocs(mapped_eh, (const uint8_t *)mapped_eh, (size_t)st.st_size);
    free(phbuf);
    close(fd);
    if (rc != 0) {
        fprintf(stderr, "[ps5280] relocs failed\n");
        return -1;
    }
    if ((unsigned)st.st_size != STOCK_SIZE)
        fprintf(stderr, "[ps5280] %s size %ld (expected %u), trying anyway\n",
                path, (long)st.st_size, STOCK_SIZE);
    return 0;
}

static void __attribute__((constructor)) ps5280_load(void)
{
    g_sns_ps5280_obj.pfn_register_callback = fail_reg;
    g_sns_ps5280_obj.pfn_un_register_callback = fail_reg;
    g_sns_ps5280_obj.pfn_set_bus_info = fail_bus;

    if (map_stock(STOCK_PATH) != 0)
        return;

    const uint32_t *obj = (const uint32_t *)(uintptr_t)OBJ_VADDR;
    if (obj[0] != OBJ_EXPECT0) {
        fprintf(stderr, "[ps5280] vtable %08x != %08x\n", obj[0], OBJ_EXPECT0);
        return;
    }

    struct {
        uint32_t from;
        const char *ot, *ss;
    } hooks[] = {
        { 0x000bbbb4, "ot_mpi_isp_sensor_reg_callback",   "ss_mpi_isp_sensor_reg_callback" },
        { 0x000bbfdc, "ot_mpi_isp_sensor_unreg_callback", "ss_mpi_isp_sensor_unreg_callback" },
        { 0x0008bc04, "ot_mpi_ae_sensor_reg_callback",    "ss_mpi_ae_sensor_reg_callback" },
        { 0x0008bce0, "ot_mpi_ae_sensor_unreg_callback",  "ss_mpi_ae_sensor_unreg_callback" },
        { 0x000e4038, "ot_mpi_awb_sensor_reg_callback",   "ss_mpi_awb_sensor_reg_callback" },
        { 0x000e4114, "ot_mpi_awb_sensor_unreg_callback", "ss_mpi_awb_sensor_unreg_callback" },
        { 0x000b102c, "ot_mpi_isp_get_ctrl_param",        "ss_mpi_isp_get_ctrl_param" },
    };
    for (size_t i = 0; i < sizeof(hooks) / sizeof(hooks[0]); i++) {
        void *to = find_sym(hooks[i].ot, hooks[i].ss);
        if (hook_thumb(hooks[i].from, to) != 0)
            return;
    }

    memcpy(&g_sns_ps5280_obj, obj, sizeof(g_sns_ps5280_obj));
    fprintf(stderr, "[ps5280] using stock CMOS at 0x%x (2-lane)\n", OBJ_VADDR);
}
