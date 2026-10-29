/* SPDX-License-Identifier: GPL-2.0-or-later */
/* Run the real transaction code against file-backed NAND, enforcing erase
 * alignment and 1->0 programming, with a one-shot write fault. */
#define main nand_program_main
#include "../../../br-external/package/fpvos-update/backends/ar9311/nand.c"
#undef main
#include <assert.h>
#include <stdarg.h>
static int fail_part = -1;
static int failed;
static int read_fault;
ssize_t __real_pwrite(int, const void *, size_t, off_t);
static int erased_blocks;
static int bad_part = -1;
static loff_t bad_offset;
static int mutation;
static const char *staged;
static void mutate_staging(void)
{
    if (!mutation) return;
    int action = mutation; mutation = 0;
    if (action == 1 || action == 2) assert(!unlink(staged));
    if (action != 1) {
        int f = open(staged, O_WRONLY | O_CREAT, 0600);
        assert(f >= 0);
        assert(__real_pwrite(f, "UNVERIFIED", 10, 512) == 10);
        close(f);
    }
}
ssize_t __real_pread(int, void *, size_t, off_t);
ssize_t __wrap_pread(int fd, void *data, size_t n, off_t off)
{
    if (read_fault && fd == parts[3].fd) {
        read_fault = 0; errno = EIO; return -1;
    }
    return __real_pread(fd, data, n, off);
}
ssize_t __wrap_pwrite(int fd, const void *data, size_t n, off_t off)
{
    for (int i = 0; i < 4; i++) if (parts[i].fd == fd) {
        assert(i != 0);
        assert(n == PAGE && off % PAGE == 0);
        assert(off >= 0 && (uint64_t)off + n <= parts[i].size);
        if (i == fail_part && !failed) { failed = 1; errno = EIO; return -1; }
        unsigned char previous[PAGE];
        assert(pread(fd, previous, n, off) == (ssize_t)n);
        for (size_t j = 0; j < n; j++)
            assert((previous[j] & ((const unsigned char *)data)[j]) == ((const unsigned char *)data)[j]);
    }
    return __real_pwrite(fd, data, n, off);
}
int __wrap_ioctl(int fd, unsigned long cmd, ...)
{
    va_list ap; va_start(ap, cmd); void *arg = va_arg(ap, void *); va_end(ap);
    int part = -1;
    for (int i = 0; i < 4; i++) if (fd == parts[i].fd) part = i;
    assert(part >= 0);
    if (cmd == MEMGETBADBLOCK) return part == bad_part && *(loff_t *)arg == bad_offset;
    if (cmd == ECCGETSTATS) { mutate_staging(); memset(arg, 0, sizeof(struct mtd_ecc_stats)); return 0; }
    if (cmd == MEMERASE) {
        erased_blocks++;
        struct erase_info_user *e = arg;
        assert(part != 0 && e->length == BLOCK && e->start % BLOCK == 0);
        assert(e->start + e->length <= parts[part].size);
        unsigned char erased[BLOCK]; memset(erased, 0xff, BLOCK);
        assert(__real_pwrite(fd, erased, BLOCK, e->start) == BLOCK);
        return 0;
    }
    assert(!"unexpected ioctl"); return -1;
}
int main(int argc, char **argv)
{
    assert(argc == 3);
    mkdir(WORK, 0700);
    for (int i = 0; i < 4; i++) {
        char name[32]; snprintf(name, sizeof(name), "part%d", i);
        parts[i].fd = open(name, O_RDWR);
        assert(parts[i].fd >= 0);
    }
    if (!strcmp(argv[1], "control")) {
        uint64_t seq; unsigned mode; int slot;
        assert(control_read(&seq, &mode, &slot) == -1);
        assert(control_write(0) == 0);
        assert(control_read(&seq, &mode, &slot) == 0 && seq == 1 && mode == 0);
        int before = erased_blocks;
        read_fault = 1;
        assert(control_write(1) == -1 && erased_blocks == before);
        assert(control_read(&seq, &mode, &slot) == 0 && seq == 1 && mode == 0);
        fail_part = 3;
        assert(control_write(1) == -1 && failed);
        assert(control_read(&seq, &mode, &slot) == 0 && seq == 1 && mode == 0);
        assert(control_write(1) == 0);
        assert(control_read(&seq, &mode, &slot) == 0 && seq == 2 && mode == 1);
        return 0;
    }
    if (!strcmp(argv[1], "layout")) return layout() ? 1 : 0;
    if (!strcmp(argv[1], "legacy-bank1")) {
        stock_bank = 1;
        assert(install(argv[2]) == -1 && erased_blocks == 0);
        return 0;
    }
    staged = argv[2];
    if (!strncmp(argv[1], "mutate", 6)) mutation = atoi(argv[1] + 6);
    if (!strncmp(argv[1], "bad", 3)) {
        bad_part = atoi(argv[1] + 3); bad_offset = parts[bad_part].size - BLOCK;
        assert(install(argv[2]) == -1 && erased_blocks == 0);
        return 0;
    }
    if (!strcmp(argv[1], "invalid")) {
        assert(install(argv[2]) == -1 && erased_blocks == 0);
        return 0;
    }
    if (!strncmp(argv[1], "restore-stock", 13)) {
        stock_runtime = 1;
        stock_bank = atoi(argv[1] + 13);
        /* Even unusable control blocks in the inactive bank are irrelevant. */
        bad_part = 3; bad_offset = 0;
    }
    if (!strncmp(argv[1], "fail", 4)) fail_part = atoi(argv[1] + 4);
    int result = install(argv[2]);
    assert(fail_part < 0 ? result == 0 : (result == -1 && failed));
    return 0;
}
