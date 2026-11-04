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
 *
 * g_sns_ps5280_obj and the MPI entry points are dynamic symbols of whatever
 * sky binary is on the unit. The address is not stable: 0x26ec3c in G_Sky
 * 17.5.15, 0x267bfc in 19.2.4. The init sequence stays inside that binary.
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

static const Elf32_Sym *g_sym;
static const char *g_str;
static uint32_t g_nsym;

static const Elf32_Sym *stock_sym(const char *name)
{
    if (!g_sym || !name)
        return NULL;
    for (uint32_t i = 0; i < g_nsym; i++) {
        if (!g_sym[i].st_name)
            continue;
        if (strcmp(g_str + g_sym[i].st_name, name) == 0)
            return &g_sym[i];
    }
    return NULL;
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
    const Elf32_Dyn *d_hash = dyn_get(dyn, DT_HASH);
    if (!d_hash)
        return -1;
    g_sym = symtab;
    g_str = strtab;
    g_nsym = ((const uint32_t *)(uintptr_t)d_hash->d_un.d_ptr)[1];

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
            /* Our own g_sns_ps5280_obj is the export. Copying it over the
             * stock object would wipe the driver we are about to use. */
            if (name[0] && strncmp(name, "g_sns_", 6) == 0)
                continue;

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
    return 0;
}

static void __attribute__((constructor)) ps5280_load(void)
{
    g_sns_ps5280_obj.pfn_register_callback = fail_reg;
    g_sns_ps5280_obj.pfn_un_register_callback = fail_reg;
    g_sns_ps5280_obj.pfn_set_bus_info = fail_bus;

    if (map_stock(STOCK_PATH) != 0)
        return;

    const Elf32_Sym *objs = stock_sym("g_sns_ps5280_obj");
    if (!objs || objs->st_size < sizeof(g_sns_ps5280_obj)) {
        fprintf(stderr, "[ps5280] sky binary has no g_sns_ps5280_obj\n");
        return;
    }
    const uint32_t *obj = (const uint32_t *)(uintptr_t)objs->st_value;
    if ((obj[0] & 1u) == 0) {
        fprintf(stderr, "[ps5280] vtable at %x is not a thumb object\n", objs->st_value);
        return;
    }

    /* Hook the stock implementation (the ot_ symbol, tens of bytes), not the
     * 4-byte ss_ stub: an 8-byte patch would run into the next function. */
    static const char *hooks[] = {
        "ot_mpi_isp_sensor_reg_callback",
        "ot_mpi_isp_sensor_unreg_callback",
        "ot_mpi_ae_sensor_reg_callback",
        "ot_mpi_ae_sensor_unreg_callback",
        "ot_mpi_awb_sensor_reg_callback",
        "ot_mpi_awb_sensor_unreg_callback",
        "ot_mpi_isp_get_ctrl_param",
    };
    for (size_t i = 0; i < sizeof(hooks) / sizeof(hooks[0]); i++) {
        const Elf32_Sym *s = stock_sym(hooks[i]);
        char proc[80];
        if (!s || s->st_size < 8) {
            fprintf(stderr, "[ps5280] no stock %s\n", hooks[i]);
            return;
        }
        /* ot_mpi_... in the sky binary, ss_mpi_... in the process. */
        snprintf(proc, sizeof(proc), "ss_%s", hooks[i] + 3);
        void *to = find_sym(proc, hooks[i]);
        if (hook_thumb(s->st_value & ~1u, to) != 0)
            return;
    }

    memcpy(&g_sns_ps5280_obj, obj, sizeof(g_sns_ps5280_obj));
    fprintf(stderr, "[ps5280] using stock CMOS at 0x%x (2-lane)\n", objs->st_value);
}
