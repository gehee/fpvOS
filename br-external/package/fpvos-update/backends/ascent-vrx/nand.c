/* SPDX-License-Identifier: GPL-2.0-or-later */
/* Gnd485 NAND backend: only kernel, DTB, and the inactive userapp region.
 * The boot chain, GPT, active vendor rootfs and vendor data are never writable
 * through this program. First implementation refuses existing bad blocks.
 */
#define _GNU_SOURCE
#include <dirent.h>
#include <errno.h>
#include <fcntl.h>
#include <mtd/mtd-user.h>
#include <signal.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/file.h>
#include <sys/ioctl.h>
#include <sys/stat.h>
#include <sys/statvfs.h>
#include <sys/wait.h>
#include <sys/utsname.h>
#include <unistd.h>
#include "layout.h"

#define BLOCK 0x20000U
#define PAGE 2048U
#define DATA_START (2 * BLOCK)
#ifndef WORK
#define WORK "/run/fpvos-update"
#endif
#ifndef ROOT_IMAGES
#define ROOT_IMAGES "/run/fpvos-root"
#endif
#ifndef VERIFY_PROGRAM
#define VERIFY_PROGRAM "/usr/libexec/fpvos-update-verify"
#endif
struct part {
	const char *name;
	uint32_t offset, size;
	int fd;
};
static struct part parts[] = {
    {"boot-protected", 0, 0xb40000, -1},
    {"kernel", 0xb40000, 0x600000, -1},
    {"dtb", 0x1140000, 0x60000, -1},
    {"fpvos", 0x26a0000, 0x1500000, -1},
};
static unsigned char buffer[BLOCK], comparison[BLOCK];
/* Stock exposes the same physical ranges through cmdline partitions. */
static int stock_runtime;
static unsigned stock_bank;
static const char stock_mtd_prefix[] =
    "mtdparts=spi32766.1:256k@0(spl0),256k(spl1),256k(spl2),256k(spl3),"
    "256k(gpt0),256k(gpt1),512K(vendor),6M(factory),512K(bl31),384K(env0),"
    "384K(env1),1M(uboot0),1M(uboot1),6M(kernel),384K(dtb),21M(userapp0),21M(userapp1),"
    "22M(usr_data0),22M(usr_data1),22M(fpv_data)";
static uint32_t le32(const unsigned char *p)
{
	return (uint32_t)p[0] | (uint32_t)p[1] << 8 | (uint32_t)p[2] << 16 | (uint32_t)p[3] << 24;
}
static uint64_t le64(const unsigned char *p)
{
	return le32(p) | ((uint64_t)le32(p + 4) << 32);
}
static void put32(unsigned char *p, uint32_t x)
{
	p[0] = x;
	p[1] = x >> 8;
	p[2] = x >> 16;
	p[3] = x >> 24;
}
static void put64(unsigned char *p, uint64_t x)
{
	put32(p, x);
	put32(p + 4, x >> 32);
}
static uint32_t crc(const unsigned char *p, size_t n)
{
	uint32_t c = ~0U;
	while (n--) {
		c ^= *p++;
		for (int i = 0; i < 8; i++)
			c = (c >> 1) ^ ((0 - (c & 1)) & 0xedb88320U);
	}
	return ~c;
}
static void progress(unsigned percent, int state, const char *text)
{
	FILE *f = fopen(WORK "/status.new", "w");
	if (!f)
		return;
	fprintf(f, "%u %d %s\n", percent, state, text);
	fflush(f);
	fsync(fileno(f));
	fclose(f);
	rename(WORK "/status.new", WORK "/status");
}
static int exact(int fd, void *data, size_t len, off_t at, int writing)
{
	unsigned char *p = data;
	while (len) {
		ssize_t n = writing ? pwrite(fd, p, len, at) : pread(fd, p, len, at);
		if (n < 0 && errno == EINTR)
			continue;
		if (n <= 0)
			return -1;
		p += n;
		len -= n;
		at += n;
	}
	return 0;
}
static int read_text(const char *path, char *out, size_t size)
{
	int fd = open(path, O_RDONLY | O_CLOEXEC);
	if (fd < 0)
		return -1;
	ssize_t n = read(fd, out, size - 1);
	close(fd);
	if (n <= 0)
		return -1;
	out[n] = 0;
	out[strcspn(out, "\n")] = 0;
	return 0;
}
static int open_part(struct part *p, int writing)
{
	DIR *d = opendir("/sys/class/mtd");
	if (!d)
		return -1;
	struct dirent *e;
	char path[256], text[128], node[128] = {0};
	while ((e = readdir(d))) {
		unsigned id;
		char extra;
		if (sscanf(e->d_name, "mtd%u%c", &id, &extra) != 1)
			continue;
		snprintf(path, sizeof(path), "/sys/class/mtd/mtd%u/name", id);
		const char *name = stock_runtime && p == &parts[0] ? "spi32766.1"
			: stock_runtime && p == &parts[3] ? (stock_bank ? "userapp0" : "userapp1") : p->name;
		if (read_text(path, text, sizeof(text)) || strcmp(text, name))
			continue;
		if (node[0]) {
			closedir(d);
			return -1;
		}
		snprintf(path, sizeof(path), "/sys/class/mtd/mtd%u/offset", id);
		int offset_result = read_text(path, text, sizeof(text));
		/* 4.9 lacks the offset attribute. Only the exact checked cmdline map
		 * may supply offsets there; never fall back on an unknown runtime. */
		if ((offset_result && !stock_runtime) ||
		    (!offset_result && strtoull(text, NULL, 0) != p->offset)) {
			closedir(d);
			return -1;
		}
		snprintf(node, sizeof(node), "/dev/mtd%u", id);
	}
	closedir(d);
	if (!node[0])
		return -1;
	p->fd = open(node, (writing ? O_RDWR : O_RDONLY) | O_SYNC | O_CLOEXEC);
	if (p->fd < 0)
		return -1;
	struct mtd_info_user info;
	uint32_t device_size = stock_runtime && p == &parts[0] ? 0x8000000 : p->size;
	if (ioctl(p->fd, MEMGETINFO, &info) || info.type != MTD_NANDFLASH || info.size != device_size ||
	    info.erasesize != BLOCK || info.writesize != PAGE || info.oobsize != 128 ||
	    (writing && !(info.flags & MTD_WRITEABLE)))
		return -1;
	return 0;
}
/* Check only ranges that an operation actually uses. In particular, boot must
 * not depend on unused tail blocks. Writers still refuse bad blocks instead
 * of silently inventing a remapping incompatible with the installed layout. */
static int good_range(struct part *p, uint32_t start, uint32_t size)
{
	if (start > p->size || size > p->size - start) return -1;
	for (loff_t at = start - start % BLOCK; at < (loff_t)start + size; at += BLOCK) {
		if (ioctl(p->fd, MEMGETBADBLOCK, &at)) {
			fprintf(stderr, "%s: bad block/query error at 0x%llx\n", p->name,
				(unsigned long long)at);
			return -1;
		}
	}
	return 0;
}
static int board(void)
{
	char model[128], cmdline[4096], line[256];
	if (read_text("/proc/device-tree/model", model, sizeof(model))) return 0;
	if (!strcmp(model, "Caddx Ascent Gnd485 (AR9311)")) return 1;
	struct utsname uts;
	if (strcmp(model, "Artosyn, Proxima Development Board") || uname(&uts) ||
	    (strcmp(uts.release, "4.9.38") && strncmp(uts.release, "4.9.38-", 7)) ||
	    read_text("/proc/cmdline", cmdline, sizeof(cmdline))) return 0;
	const char *map = strstr(cmdline, stock_mtd_prefix);
	if (!map || (map != cmdline && map[-1] != ' ') ||
	    (map[sizeof(stock_mtd_prefix)-1] != ',' && map[sizeof(stock_mtd_prefix)-1] != ' ' &&
	     map[sizeof(stock_mtd_prefix)-1] != '\0')) return 0;
	FILE *version = fopen("/etc/app.version", "r");
	if (!version) return 0;
	unsigned found = 0;
	while (fgets(line, sizeof(line), version))
		if (!strcmp(line, "BOARD_TYPE=Gnd485\n")) found++;
	fclose(version);
	if (found != 1) return 0;
	stock_runtime = 1;
	return 1;
}

int fpvos_stock_runtime_valid(void)
{
	return board() && stock_runtime;
}

static int writable_ubi_detached(void)
{
	DIR *d = opendir("/sys/class/ubi");
	if (!d) return errno == ENOENT ? 0 : -1;
	struct dirent *e;
	int result = 0;
	while ((e = readdir(d))) {
		unsigned id, mtd; char extra, path[256], text[128];
		if (sscanf(e->d_name, "ubi%u%c", &id, &extra) != 1) continue;
		snprintf(path, sizeof(path), "/sys/class/ubi/ubi%u/mtd_num", id);
		if (read_text(path, text, sizeof(text)) || sscanf(text, "%u%c", &mtd, &extra) != 1) { result = -1; break; }
		snprintf(path, sizeof(path), "/sys/class/mtd/mtd%u/name", mtd);
		if (read_text(path, text, sizeof(text))) { result = -1; break; }
		/* OTA preparation unmounts stock data volumes without detaching
		 * their UBI devices. These named ranges are never write targets. */
		int preserved = stock_runtime
			? (!strcmp(text, "userapp0") || !strcmp(text, "factory") || !strcmp(text, "vendor") ||
			   !strcmp(text, "usr_data0") || !strcmp(text, "usr_data1") || !strcmp(text, "fpv_data"))
			: (!strcmp(text, "vendor-rootfs") || !strcmp(text, "vendor-data"));
		if (stock_runtime && !strcmp(text, stock_bank ? "userapp1" : "userapp0")) preserved = 1;
		/* Never allow either an unknown attachment or the destination bank. */
		if (stock_runtime && !strcmp(text, stock_bank ? "userapp0" : "userapp1")) preserved = 0;
		if (!preserved) {
			fprintf(stderr, "unsafe attached UBI device ubi%u on %s; no writes\n", id, text);
			result = -1; break;
		}
	}
	closedir(d);
	return result;
}
static int layout(void)
{
	unsigned char records[2][AR9311_GPT_BYTES];
	for (unsigned slot = 0; slot < 2; slot++) {
		if (good_range(&parts[0], 0x100000 + slot * 0x40000, sizeof(records[slot])) ||
		    exact(parts[0].fd, records[slot], sizeof(records[slot]),
			  0x100000 + slot * 0x40000, 0))
			return -1;
	}
	if (ar9311_stock_bank(records, &stock_bank)) return -1;
	parts[3].offset = stock_bank ? 0x11a0000 : 0x26a0000;
	return 0;
}
static int verify(const char *package, const char *directory)
{
	pid_t p = fork();
	int status;
	if (p < 0)
		return -1;
	if (!p) {
		execl(VERIFY_PROGRAM, "fpvos-update-verify", package,
		      directory, (char *)NULL);
		_exit(127);
	}
	while (waitpid(p, &status, 0) < 0)
		if (errno != EINTR)
			return -1;
	return WIFEXITED(status) && WEXITSTATUS(status) == 0 ? 0 : -1;
}
static int export_range(struct part *p, uint32_t start, uint32_t size, const char *file)
{
	if (good_range(p, start, size))
		return -1;
	int out = open(file, O_WRONLY | O_CREAT | O_EXCL | O_CLOEXEC, 0600);
	if (out < 0)
		return -1;
	int result = -1;
	struct mtd_ecc_stats before, after;
	if (ioctl(p->fd, ECCGETSTATS, &before))
		goto done;
	for (uint32_t at = 0; at < size;) {
		size_t n = size - at;
		if (n > BLOCK)
			n = BLOCK;
		if (exact(p->fd, buffer, n, start + at, 0) || exact(out, buffer, n, at, 1))
			goto done;
		at += n;
	}
	if (ioctl(p->fd, ECCGETSTATS, &after) || after.failed != before.failed || fsync(out))
		goto done;
	result = 0;
done:
	close(out);
	return result;
}
static int compare_range(struct part *p, uint32_t start, const char *file)
{
	int f = open(file, O_RDONLY | O_NOFOLLOW | O_CLOEXEC);
	struct stat st;
	int result = -1;
	if (f < 0)
		return -1;
	if (fstat(f, &st) || !S_ISREG(st.st_mode) || st.st_size < 0 || start > p->size ||
	    (uint64_t)st.st_size > p->size - start || good_range(p, start, st.st_size))
		goto done;
	struct mtd_ecc_stats before, after;
	if (ioctl(p->fd, ECCGETSTATS, &before))
		goto done;
	for (off_t at = 0; at < st.st_size;) {
		size_t n = st.st_size - at;
		if (n > BLOCK)
			n = BLOCK;
		if (exact(f, buffer, n, at, 0) || exact(p->fd, comparison, n, start + at, 0) ||
		    memcmp(buffer, comparison, n))
			goto done;
		at += n;
	}
	if (ioctl(p->fd, ECCGETSTATS, &after) || after.failed != before.failed)
		goto done;
	result = 0;
done:
	close(f);
	return result;
}
static int write_image(struct part *p, uint32_t start, const char *file, int header_last)
{
	int f = open(file, O_RDONLY | O_NOFOLLOW | O_CLOEXEC);
	struct stat st;
	int result = -1;
	if (f < 0)
		return -1;
	if (fstat(f, &st) || !S_ISREG(st.st_mode) || st.st_size <= 0 || start % BLOCK ||
	    start >= p->size || (uint64_t)st.st_size > p->size - start)
		goto done;
	if (good_range(p, start, p->size - start)) goto done;
	for (uint32_t at = start; at < p->size; at += BLOCK) {
		struct erase_info_user erase = {.start = at, .length = BLOCK};
		if (ioctl(p->fd, MEMERASE, &erase))
			goto done;
	}
	uint32_t blocks = ((uint64_t)st.st_size + BLOCK - 1) / BLOCK;
	for (uint32_t iteration = 0; iteration < blocks; iteration++) {
		uint32_t block = header_last ? (iteration + 1) % blocks : iteration;
		uint32_t pos = block * BLOCK;
		size_t n = st.st_size - pos;
		if (n > BLOCK)
			n = BLOCK;
		memset(buffer, 0xff, sizeof(buffer));
		if (exact(f, buffer, n, pos, 0))
			goto done;
		for (uint32_t page = 0; page < n; page += PAGE) {
			unsigned i;
			for (i = 0; i < PAGE; i++)
				if (buffer[page + i] != 0xff)
					break;
			if (i == PAGE)
				continue;
			if (exact(p->fd, buffer + page, PAGE, start + pos + page, 1))
				goto done;
		}
	}
	result = compare_range(p, start, file);
done:
	close(f);
	return result;
}
static int control_read(uint64_t *sequence, unsigned *mode, int *slot)
{
	if (good_range(&parts[3], 0, DATA_START)) return -2;
	*sequence = 0;
	*mode = 0;
	*slot = -1;
	for (int i = 0; i < 2; i++) {
		unsigned char record[PAGE];
		if (exact(parts[3].fd, record, PAGE, i * BLOCK, 0))
			return -2;
		if (memcmp(record, "FPVOCTL1", 8))
			continue;
		uint32_t saved = le32(record + 20);
		put32(record + 20, 0);
		if (crc(record, PAGE) != saved || le32(record + 16) > 1)
			continue;
		uint64_t seq = le64(record + 8);
		if (!seq)
			continue;
		if (*slot >= 0 && seq == *sequence)
			return -2;
		if (seq > *sequence) {
			*sequence = seq;
			*mode = le32(record + 16);
			*slot = i;
		}
	}
	return *slot < 0 ? -1 : 0;
}
static int control_write(unsigned mode)
{
	uint64_t seq;
	unsigned old;
	int slot;
	int read_result = control_read(&seq, &old, &slot);
	/* Only an intact but uninitialized control area may start a sequence.
	 * Read errors or conflicting records must never trigger an erase. */
	if (read_result < -1)
		return -1;
	if (read_result) {
		seq = 0;
		slot = 1;
	}
	if (seq == UINT64_MAX)
		return -1;
	int next = slot ^ 1;
	unsigned char record[PAGE];
	memset(record, 0xff, sizeof(record));
	memcpy(record, "FPVOCTL1", 8);
	put64(record + 8, seq + 1);
	put32(record + 16, mode);
	put32(record + 20, 0);
	put32(record + 20, crc(record, PAGE));
	struct erase_info_user erase = {.start = next * BLOCK, .length = BLOCK};
	if (ioctl(parts[3].fd, MEMERASE, &erase) ||
	    exact(parts[3].fd, record, PAGE, next * BLOCK, 1) ||
	    exact(parts[3].fd, comparison, PAGE, next * BLOCK, 0) ||
	    memcmp(record, comparison, PAGE))
		return -1;
	return 0;
}
static int header(const char *path, unsigned char h[512])
{
	int f = open(path, O_RDONLY | O_NOFOLLOW | O_CLOEXEC);
	if (f < 0)
		return -1;
	int r = exact(f, h, 512, 0, 0);
	close(f);
	return r;
}
static int boot(void)
{
	uint64_t sequence;
	unsigned mode;
	int slot;
	if (control_read(&sequence, &mode, &slot))
		return 11;
	if (mode) {
		if (control_write(0))
			fprintf(stderr, "clean flag not consumed; next boot may remain clean\n");
		return 10;
	}
	unsigned char h[512];
	if (good_range(&parts[3], DATA_START, 512) ||
	    exact(parts[3].fd, h, 512, DATA_START, 0) || memcmp(h, "FPVOSUP1", 8) || le32(h + 88))
		return 11;
	uint32_t len = le32(h + 16);
	if (len < 512 || len > parts[3].size - DATA_START)
		return 11;
	uint32_t saved = le32(h + 508);
	put32(h + 508, 0);
	if (crc(h, 512) != saved)
		return 11;
	if (mkdir(ROOT_IMAGES, 0700))
		return 11;
	if (export_range(&parts[3], DATA_START, len, WORK "/boot.fwu") ||
	    verify(WORK "/boot.fwu", ROOT_IMAGES) ||
	    compare_range(&parts[1], 0, ROOT_IMAGES "/kernel.img") ||
	    compare_range(&parts[2], 0, ROOT_IMAGES "/ascent-gnd485.dtb"))
		return 11;

	unlink(ROOT_IMAGES "/kernel.img");
	unlink(ROOT_IMAGES "/ascent-gnd485.dtb");
	return 0;
}
/* Own a private snapshot before verification. A receiver restart may unlink or
 * replace staging, and another process can still hold a writable staging fd.
 * Opening that fd once alone would not protect against in-place modification.
 * Only this transaction uses the 0400 copy inside its private directory. */
static int snapshot_package(const char *source, const char *copy)
{
	int in = open(source, O_RDONLY | O_NOFOLLOW | O_CLOEXEC | O_NONBLOCK);
	if (in < 0) return -1;
	struct stat st;
	int out = -1, result = -1;
	struct statvfs space;
	if (fstat(in, &st) || !S_ISREG(st.st_mode) || st.st_size < 512 ||
	    (uint64_t)st.st_size > parts[3].size - DATA_START ||
	    statvfs(WORK, &space) ||
	    space.f_bavail * (uint64_t)space.f_frsize < (uint64_t)st.st_size + 32U * 1024 * 1024)
		goto done;
	out = open(copy, O_WRONLY | O_CREAT | O_EXCL | O_NOFOLLOW | O_CLOEXEC, 0600);
	if (out < 0) goto done;
	for (off_t at = 0; at < st.st_size;) {
		size_t n = st.st_size - at;
		if (n > BLOCK) n = BLOCK;
		if (exact(in, buffer, n, at, 0) || exact(out, buffer, n, at, 1)) goto done;
		at += n;
	}
	if (fsync(out) || fchmod(out, 0400)) goto done;
	result = 0;
done:
	if (out >= 0) close(out);
	close(in);
	if (result) unlink(copy);
	return result;
}
static int install(const char *source)
{
	char dir[] = WORK "/install.XXXXXX";
	if (!mkdtemp(dir))
		return -1;
	char package[256], kernel[256], dtb[256], backups[3][256];
	int changed[3] = {0}, result = -1;
	snprintf(package, sizeof(package), "%s/package.fwu", dir);
	snprintf(kernel, sizeof(kernel), "%s/kernel.img", dir);
	snprintf(dtb, sizeof(dtb), "%s/ascent-gnd485.dtb", dir);
	for (unsigned i = 0; i < 3; i++)
		snprintf(backups[i], sizeof(backups[i]), "%s/before-%u", dir, i);
	if (snapshot_package(source, package) || verify(package, dir))
		goto done;
	unsigned char h[512];
	if (header(package, h))
		goto done;
	unsigned kind = le32(h + 88);
	if (kind > 1)
		goto done;
	/* Legacy fpvOS trees hard-code the opposite bank mapping. Do not install
	 * one on stock bank 1 and strand the device in an incompatible recovery.
	 * The verifier has already checked the complete DTB structure and hash. */
	if (!kind && stock_bank) {
		static const char marker[] = "fpvos,ar9311-partitions";
		struct stat st;
		int f = open(dtb, O_RDONLY | O_NOFOLLOW | O_CLOEXEC);
		unsigned char *data = NULL;
		int compatible = f >= 0 && !fstat(f, &st) && st.st_size > 0 &&
			st.st_size <= parts[2].size && (data = malloc(st.st_size)) &&
			!exact(f, data, st.st_size, 0, 0) && memmem(data, st.st_size, marker, sizeof(marker));
		free(data);
		if (f >= 0) close(f);
		if (!compatible) {
			fprintf(stderr, "stock userapp1 requires a bank-aware fpvOS device tree; no writes\n");
			goto done;
		}
	}
	/* Check every region we will erase before touching any NAND. Restore
	 * packages do not read, erase or program the inactive rootfs/control area. */
	if (good_range(&parts[1], 0, parts[1].size) ||
	    good_range(&parts[2], 0, parts[2].size) ||
	    (!kind && good_range(&parts[3], 0, parts[3].size))) goto done;
	struct statvfs space;
	if (statvfs(WORK, &space) || space.f_bavail * (uint64_t)space.f_frsize < 32U * 1024 * 1024)
		goto done;
	progress(5, 3, "backing up affected NAND regions in RAM");
	if (export_range(&parts[1], 0, parts[1].size, backups[0]) ||
	    export_range(&parts[2], 0, parts[2].size, backups[1]) ||
	    (!kind && export_range(&parts[3], DATA_START, parts[3].size - DATA_START, backups[2])))
		goto done;
	if (!kind) {
		progress(25, 3, "writing fpvOS root bundle");
		changed[2] = 1;
		if (write_image(&parts[3], DATA_START, package, 1))
			goto restore;
	}
	progress(60, 3, "writing device tree");
	changed[1] = 1;
	if (write_image(&parts[2], 0, dtb, 0))
		goto restore;
	progress(75, 3, "writing kernel");
	changed[0] = 1;
	if (write_image(&parts[1], 0, kernel, 0))
		goto restore;
	if (!kind && control_write(0))
		goto restore;
	progress(100, 4,
		 kind ? "vendor kernel restored; reboot required"
		      : "fpvOS installed; reboot required");
	result = 0;
	goto done;
restore:
	progress(0, -1, "write failed; restoring saved regions");
	for (unsigned i = 0; i < 3; i++)
		if (changed[i]) {
			unsigned part = i == 2 ? 3 : i + 1;
			uint32_t start = i == 2 ? DATA_START : 0;
			if (write_image(&parts[part], start, backups[i], i == 2)) {
				progress(0, -2,
					 "restoration failed; KEEP POWER ON; use USB RAM recovery");
				return -2;
			}
		}
	progress(0, -1, "update failed; previous affected regions restored");
done:
	/* Retain evidence only after a write attempt; rejected uploads must not
	 * accumulate private snapshots and extracted images in scarce tmpfs. */
	if (!result || !(changed[0] || changed[1] || changed[2])) {
		for (unsigned i = 0; i < 3; i++)
			unlink(backups[i]);
		unlink(package);
		unlink(kernel);
		unlink(dtb);
		char root[256];
		snprintf(root, sizeof(root), "%s/rootfs.cpio.uboot", dir);
		unlink(root);
		rmdir(dir);
	}
	return result;
}
int main(int argc, char **argv)
{
	if (argc < 2 || argc > 3 || !board() || geteuid()) {
		fprintf(stderr, "Gnd485 root-only NAND backend\n");
		return 2;
	}
	int is_install = !strcmp(argv[1], "install");
	int is_boot = !strcmp(argv[1], "boot");
	int is_clean = !strcmp(argv[1], "clean");
	int is_preflight = !strcmp(argv[1], "preflight");
	if ((!is_install && !is_boot && !is_clean && !is_preflight) || (is_install != (argc == 3)) ||
	    (stock_runtime && (is_boot || is_clean)))
		return 2;
	umask(077);
	mkdir(WORK, 0700);
	int lock = open(WORK "/install.lock", O_RDWR | O_CREAT | O_NOFOLLOW | O_CLOEXEC, 0600);
	if (lock < 0 || flock(lock, LOCK_EX | LOCK_NB)) {
		fprintf(stderr, "NAND operation already active\n");
		return 1;
	}
	/* Discover the selected stock bank before opening the inactive destination.
	 * GPT is only ever read through the protected descriptor. */
	if (open_part(&parts[0], 0) || layout()) {
		fprintf(stderr, "invalid GPT geometry/CRC/generation/bank selection; no writes\n");
		return 1;
	}
	for (unsigned i = 1; i < 4; i++)
		if (open_part(&parts[i], !is_preflight && (i == 3 || (is_install && i != 0)))) {
			fprintf(stderr,
				"NAND geometry/name/offset/bad-block preflight failed: %s\n",
				parts[i].name);
			return 1;
		}
	if (writable_ubi_detached()) {
		fprintf(stderr, "unsafe UBI attachment; no writes\n");
		return 1;
	}
	int result;
	if (is_preflight) {
		/* Recovery readiness checks identity, layout, geometry and UBI
		 * ownership, not the health of a still-unknown operation's ranges.
		 * Even damaged control/header blocks must not prevent a vendor
		 * restore, which never accesses the fpvOS bank. Boot/clean check
		 * their reads and install checks all erase ranges before writing. */
		printf("Gnd485 %s NAND layout verified; stock=userapp%u fpvOS=userapp%u; no writes\n",
		       stock_runtime ? "stock" : "fpvOS", stock_bank, stock_bank ^ 1);
		result = 0;
	} else if (is_install) {
		signal(SIGHUP, SIG_IGN);
		signal(SIGINT, SIG_IGN);
		signal(SIGTERM, SIG_IGN);
		signal(SIGPIPE, SIG_IGN);
		result = install(argv[2]);
	} else if (is_clean)
		result = control_write(1);
	else
		result = boot();
	for (unsigned i = 0; i < 4; i++)
		close(parts[i].fd);
	close(lock);
	if (result < 0) {
		fprintf(stderr, "NAND operation failed\n");
		return 1;
	}
	return result;
}
