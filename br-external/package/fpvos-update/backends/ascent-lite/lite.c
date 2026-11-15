/* SPDX-License-Identifier: GPL-2.0-or-later */
/* Caddx Ascent Lite / Lite+ (Hi3516CV610): fpvos-update in place of the
 * stock updater, under its path and name (/usrdata/fpv/ar_fpvhs_upgrade) and
 * with its options, so the stock rootfs starts it in both systems: the
 * normal one (-c 1) and the clean one, which copies it to /tmp first (-c 0).
 *
 * It answers the vendor's PC tool, the fpvOS Flasher and fpvOS's client in
 * the stock dialect (FIND_DEVICE as stock fills it) and installs an ASW air
 * image as stock does, on the bank the unit did not boot from, then switches
 * the boot bank to it. Unlike stock it reads every block back before the
 * switch, and leaves U-Boot and its environment alone when the image's are the
 * ones on the flash. See lite-updater-re/stock-updater.md for the stock side.
 *
 * FPVOS_LITE_ROOT puts every path under a directory, for host tests: there
 * the MTD partitions are plain files with 128 KiB erase blocks, their bad
 * blocks listed in mtdN.bad, and FPVOS_LITE_CUT_AFTER=N stops the installer
 * dead after N block writes (a power cut).
 */
#define _GNU_SOURCE
#include <errno.h>
#include <fcntl.h>
#include <getopt.h>
#include <libgen.h>
#include <limits.h>
#include <mtd/mtd-user.h>
#include <signal.h>
#include <stdarg.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/ioctl.h>
#include <sys/mman.h>
#include <sys/reboot.h>
#include <sys/stat.h>
#include <sys/types.h>
#include <sys/wait.h>
#include <unistd.h>

#include "board.h"
#include "bootstrap.h"
#include "fpvos-bytes.h"

int fpvos_receiver_main(int, char **);
extern int fpvos_receiver_clean_at_start;

/* ----------------------------------------------------------- paths ---- */

static const char *root(void)
{
	const char *r = getenv("FPVOS_LITE_ROOT");
	return r ? r : "";
}
static int simulated(void)
{
	return root()[0] != 0;
}
static void at(char *out, size_t size, const char *path)
{
	snprintf(out, size, "%s%s", root(), path);
}
static int exists(const char *path)
{
	char p[PATH_MAX];
	at(p, sizeof(p), path);
	return access(p, F_OK) == 0;
}
static int read_text(const char *path, char *out, size_t size)
{
	char p[PATH_MAX];
	at(p, sizeof(p), path);
	FILE *f = fopen(p, "r");
	if (!f)
		return -1;
	size_t n = fread(out, 1, size - 1, f);
	out[n] = 0;
	fclose(f);
	return 0;
}

/* ---------------------------------------------------- what the unit is -- */

/* The options stock's scripts start it with: -t board type (472 Lite+, 482
 * Lite), -b hardware and -e board version (two hex digits each, 0x13 is
 * "1.3"), -r RF board, -c 0 in the clean system. The rest are taken and
 * ignored. Stock's hardware string ends in the RF board when there is one
 * (-r 16 "1.0", -r 17 "1.1" on two Lite+ with -e 16), else in -e. */
static int opt_clean, opt_t, opt_b, opt_e, opt_r;

static const char *device_name(void)
{
	switch (opt_t) {
	case 472: return "Ascent_lite_plus";
	case 482: return "Ascent_lite";
	case 492: return "Ascent_RC";
	default: return "Ascent";
	}
}

/* /etc/app.version's APP_VERSION and BOARD_TYPE (the stock rootfs's). The ASW
 * board id the image must carry goes with the board type. */
static int app_version[3], image_board = -1;
static char firmware_prefix[24] = "Ascent";

static void read_app_version(void)
{
	char text[1024], *p;
	if (read_text("/etc/app.version", text, sizeof(text)))
		return;
	if ((p = strstr(text, "APP_VERSION=")))
		sscanf(p + 12, "%d.%d.%d", &app_version[0], &app_version[1], &app_version[2]);
	if ((p = strstr(text, "BOARD_TYPE="))) {
		p += 11;
		if (!strncmp(p, "Sky482", 6) && (p[6] == '\n' || p[6] == '\r' || !p[6])) {
			image_board = 3;
			snprintf(firmware_prefix, sizeof(firmware_prefix), "Ascent_H_Sky");
		}
	}
}

/* The chip id: stock's register, or a /factory marker file overriding it; the
 * serial number's first field is its index in stock's table. */
static uint32_t chip_id(void)
{
	static const char *const markers[] = {
		"0x3516c613", "0x3516c610", "0x3516c616", "0x24a13", "0x24a10", "0x24a16"};
	for (unsigned i = 0; i < sizeof(markers) / sizeof(*markers); i++) {
		char p[64];
		snprintf(p, sizeof(p), "/factory/chip_id_%s", markers[i]);
		if (exists(p))
			return (uint32_t)strtoul(markers[i], NULL, 16);
	}
	if (simulated()) {
		char text[32];
		return read_text("/chip_id", text, sizeof(text)) ? 0 : (uint32_t)strtoul(text, NULL, 0);
	}
	int fd = open("/dev/mem", O_RDONLY | O_SYNC | O_CLOEXEC);
	if (fd < 0)
		return 0;
	long page = sysconf(_SC_PAGESIZE);
	off_t base = 0x11020ee0 & ~(off_t)(page - 1);
	volatile uint32_t *m = mmap(NULL, page, PROT_READ, MAP_SHARED, fd, base);
	close(fd);
	if (m == MAP_FAILED)
		return 0;
	uint32_t id = m[(0x11020ee0 - base) / 4];
	munmap((void *)m, page);
	return id;
}
static int chip_index(uint32_t id)
{
	static const uint32_t table[] = {0x3516c613, 0x3516c610, 0x3516c616, 0x24a13, 0x24a10, 0x24a16};
	for (unsigned i = 0; i < sizeof(table) / sizeof(*table); i++)
		if (table[i] == id)
			return (int)i + 1;
	return -1;
}

/* /factory/mp_cfg.json's "sn" (stock falls back to /usrdata/mp_cfg.json). */
static void read_sn(char *out, size_t size)
{
	char text[4096], *p, *q;
	out[0] = 0;
	if (read_text("/factory/mp_cfg.json", text, sizeof(text)) &&
	    read_text("/usrdata/mp_cfg.json", text, sizeof(text)))
		return;
	if (!(p = strstr(text, "\"sn\"")) || !(p = strchr(p + 4, ':')) || !(p = strchr(p, '"')) ||
	    !(q = strchr(p + 1, '"')))
		return;
	snprintf(out, size, "%.*s", (int)(q - p - 1), p + 1);
}

/* stock's temp_measure.sh prints tenths of a degree. */
static int cpu_temperature(void)
{
	if (simulated())
		return 0;
	FILE *f = popen("sh /usrdata/fpv/temp_measure.sh 1 2>/dev/null", "r");
	char line[64] = {0};
	if (!f)
		return 0;
	if (!fgets(line, sizeof(line), f))
		line[0] = 0;
	pclose(f);
	return (atoi(line) + 5) / 10;
}

static char serial_number[64], hardware[64];

/* The firmware field keeps stock's name and version for the vendor's PC tool;
 * fpvOS's own version (git describe of the build) goes in the SDK field, which
 * the PC tool does not check. */
#define VERSION_FILE "/usrdata/fpv/air/VERSION"

void fpvos_board_find_device(unsigned char b[300], const char *detail)
{
	char version[32];
	fpvos_put_le32(b, 1024 * 1024);
	if (!read_text(VERSION_FILE, version, sizeof(version))) {
		version[strcspn(version, "\r\n")] = 0;
		snprintf((char *)b + 4, 32, "%s", version);
	}
	snprintf((char *)b + 36, 64, "%s", device_name());
	fpvos_put_le32(b + 100, (uint32_t)cpu_temperature());
	snprintf((char *)b + 104, 64, "%s_%d_%d_%d", firmware_prefix,
		 app_version[0], app_version[1], app_version[2]);
	snprintf((char *)b + 168, 32, "%.31s", serial_number);
	snprintf((char *)b + 200, 32, "%.31s", hardware);
	fpvos_put_le32(b + 232, 0);
	snprintf((char *)b + 236, 64, "%s", detail);
}

/* Any /tmp/pc/<name>: what was sent is read from the file, never from its
 * name. fpvos.verify only checks it; fpvos.fwu (fpvOS's tools) waits for
 * their REBOOT; any other name is a vendor tool's, which never sends one. */
int fpvos_board_destination(const unsigned char path[128], int *install, int *self_reboot)
{
	const unsigned char *end = memchr(path, 0, 128);
	size_t n = end ? (size_t)(end - path) : 0;
	if (n <= 8 || memcmp(path, "/tmp/pc/", 8))
		return 0;
	*install = strcmp((const char *)path, "/tmp/pc/fpvos.verify") != 0;
	*self_reboot = *install && strcmp((const char *)path, "/tmp/pc/fpvos.fwu") != 0;
	return 1;
}

/* fpvOS_usb, which the receiver asks for the normal and bridge modes. */
#define FPVOS_USB "/usrdata/fpv/air/fpvos-usb"

/* Out of bridge mode before the serial gadget changes or goes (a reboot, the
 * switch to RNDIS): stock's shutdown knows nothing of it, and the gadget
 * unbound under the bridge's endpoints can hang the reboot (seen on the P1
 * Air). Does nothing in normal mode. */
static void leave_bridge(void)
{
	if (simulated() || access(FPVOS_USB, X_OK))
		return;
	pid_t p = fork();
	if (!p) {
		execl(FPVOS_USB, "fpvos-usb", "shutdown", (char *)NULL);
		_exit(127);
	}
	if (p > 0)
		while (waitpid(p, NULL, 0) < 0 && errno == EINTR)
			;
}

/* Commands 58 and 59, as stock: the stock scripts switch the gadget to RNDIS
 * live (the serial port goes until the unit comes back to it), or a flag
 * file does at the next boot. */
void fpvos_board_network(int reboot, int clean)
{
	pid_t child = fork();
	if (child)
		return;
	setsid();
	if (reboot) {
		sleep(2);
		leave_bridge();
		char p[PATH_MAX];
		at(p, sizeof(p), "/factory/run_rndis_flag");
		FILE *f = fopen(p, "w");
		if (f) {
			fputs("rndis\n", f);
			fclose(f);
		}
		sync();
		if (!simulated())
			execlp("reboot", "reboot", (char *)NULL);
		_exit(0);
	}
	sleep(1);
	leave_bridge();
	if (!simulated())
		execl("/bin/sh", "sh", "-c", clean
			? "/tmp/disable_config_serial.sh & usleep 500000; /tmp/config_ether.sh clean &"
			: "/usrdata/fpv/disable_config_serial.sh & /usrdata/fpv/config_ether.sh &",
		      (char *)NULL);
	_exit(0);
}

/* ------------------------------------------------------------- MTD ---- */

#define MAX_BLOCK (128 * 1024)
#define MAX_BLOCKS 512

struct mtd {
	int fd, number;
	uint32_t size, erasesize, writesize;
	unsigned char bad[MAX_BLOCKS];
};

static long cut_after = -1;
static void block_written(void)
{
	if (cut_after >= 0 && cut_after-- == 0)
		_exit(99);
}

static int mtd_open(struct mtd *m, int number)
{
	char p[PATH_MAX], dev[32];
	memset(m, 0, sizeof(*m));
	m->number = number;
	snprintf(dev, sizeof(dev), "/dev/mtd%d", number);
	at(p, sizeof(p), dev);
	m->fd = open(p, O_RDWR | O_CLOEXEC);
	if (m->fd < 0)
		return -1;
	if (simulated()) {
		struct stat st;
		if (fstat(m->fd, &st))
			return -1;
		m->size = (uint32_t)st.st_size;
		m->erasesize = MAX_BLOCK;
		m->writesize = 2048;
		snprintf(dev, sizeof(dev), "/dev/mtd%d.bad", number);
		at(p, sizeof(p), dev);
		FILE *f = fopen(p, "r");
		unsigned b;
		while (f && fscanf(f, "%u", &b) == 1)
			if (b < MAX_BLOCKS)
				m->bad[b] = 1;
		if (f)
			fclose(f);
	} else {
		struct mtd_info_user info;
		if (ioctl(m->fd, MEMGETINFO, &info))
			return -1;
		m->size = info.size;
		m->erasesize = info.erasesize;
		m->writesize = info.writesize;
	}
	if (!m->erasesize || m->erasesize > MAX_BLOCK || m->size % m->erasesize ||
	    m->size / m->erasesize > MAX_BLOCKS || !m->writesize || m->erasesize % m->writesize) {
		close(m->fd);
		return -1;
	}
	return 0;
}
static unsigned mtd_blocks(const struct mtd *m)
{
	return m->size / m->erasesize;
}
static int mtd_bad(struct mtd *m, unsigned block)
{
	if (simulated())
		return m->bad[block];
	loff_t o = (loff_t)block * m->erasesize;
	return ioctl(m->fd, MEMGETBADBLOCK, &o) > 0;
}
static void mtd_mark_bad(struct mtd *m, unsigned block)
{
	m->bad[block] = 1;
	if (simulated()) {
		char p[PATH_MAX], dev[32];
		snprintf(dev, sizeof(dev), "/dev/mtd%d.bad", m->number);
		at(p, sizeof(p), dev);
		FILE *f = fopen(p, "a");
		if (f) {
			fprintf(f, "%u\n", block);
			fclose(f);
		}
		return;
	}
	loff_t o = (loff_t)block * m->erasesize;
	ioctl(m->fd, MEMSETBADBLOCK, &o);
}
static int mtd_erase(struct mtd *m, unsigned block)
{
	if (simulated()) {
		static unsigned char ff[MAX_BLOCK];
		memset(ff, 0xff, sizeof(ff));
		int r = pwrite(m->fd, ff, m->erasesize, (off_t)block * m->erasesize) == (ssize_t)m->erasesize ? 0 : -1;
		block_written();
		return r;
	}
	struct erase_info_user e = {.start = block * m->erasesize, .length = m->erasesize};
	return ioctl(m->fd, MEMERASE, &e);
}
static int mtd_write(struct mtd *m, unsigned block, const unsigned char *buf, uint32_t n)
{
	int r = pwrite(m->fd, buf, n, (off_t)block * m->erasesize) == (ssize_t)n ? 0 : -1;
	if (simulated())
		block_written();
	return r;
}
static int mtd_read(struct mtd *m, unsigned block, unsigned char *buf, uint32_t n)
{
	return pread(m->fd, buf, n, (off_t)block * m->erasesize) == (ssize_t)n ? 0 : -1;
}

/* An MTD partition the running system has attached (UBI) or mounted is never
 * written. */
static int mtd_in_use(int number)
{
	char p[PATH_MAX], text[32];
	for (int i = 0; i < 32; i++) {
		snprintf(p, sizeof(p), "/sys/class/ubi/ubi%d/mtd_num", i);
		if (!read_text(p, text, sizeof(text)) && atoi(text) == number)
			return 1;
	}
	char mounts[8192];
	snprintf(p, sizeof(p), "/dev/mtdblock%d ", number);
	return !read_text("/proc/mounts", mounts, sizeof(mounts)) && strstr(mounts, p);
}

/* ----------------------------------------------------------- image ---- */

/* The ASW container (boot/mkascentimg.py builds the same): 0x80 bytes of
 * header, magic "ASW\0", board id at 4, version at 8/12/16, five sections
 * {u8 type, u8 upgrade, u8 dual, u8 pad, u32 flash alloc, u32 file offset} at
 * 0x14, CRC-32 of 0x80..end at 0x70, the size at 0x74. Section i ends where
 * section i + 1 starts; 0 boot, 1 env, 2 kernel, 3 rootfs, 4 app volume. */
#define SECTIONS 5
struct image {
	int fd;
	uint32_t size, version[3];
	struct { uint32_t offset, length; int upgrade; } section[SECTIONS];
};
static const char *const section_names[SECTIONS] = {"U-Boot", "U-Boot environment", "kernel", "rootfs", "app volume"};

static int image_open(struct image *img, const char *path, char *why, size_t why_size)
{
	unsigned char h[0x80];
	struct stat st;
	memset(img, 0, sizeof(*img));
	img->fd = open(path, O_RDONLY | O_CLOEXEC);
	if (img->fd < 0 || fstat(img->fd, &st) || pread(img->fd, h, sizeof(h), 0) != sizeof(h)) {
		snprintf(why, why_size, "cannot read the image");
		return -1;
	}
	if (memcmp(h, "ASW", 4)) {
		snprintf(why, why_size, "not an air image (no ASW header)");
		return -1;
	}
	img->size = fpvos_get_le32(h + 0x74);
	if ((off_t)img->size != st.st_size) {
		snprintf(why, why_size, "image size %u, file %lld", img->size, (long long)st.st_size);
		return -1;
	}
	if (image_board < 0 || h[4] != image_board) {
		snprintf(why, why_size, "image for board %u, this unit %d", h[4], image_board);
		return -1;
	}
	for (int i = 0; i < 3; i++)
		img->version[i] = fpvos_get_le32(h + 8 + 4 * i);
	for (int i = 0; i < SECTIONS; i++) {
		img->section[i].upgrade = h[0x14 + 12 * i + 1] != 0;
		img->section[i].offset = fpvos_get_le32(h + 0x14 + 12 * i + 8);
	}
	for (int i = 0; i < SECTIONS; i++) {
		uint32_t end = i + 1 < SECTIONS ? img->section[i + 1].offset : img->size;
		if (img->section[i].offset < 0x80 || end < img->section[i].offset || end > img->size) {
			snprintf(why, why_size, "section table out of order");
			return -1;
		}
		img->section[i].length = end - img->section[i].offset;
	}
	if (img->section[0].offset != 0x80) {
		snprintf(why, why_size, "section table out of order");
		return -1;
	}
	static unsigned char buf[MAX_BLOCK];
	unsigned crc = ~0U;
	for (uint32_t at = 0x80; at < img->size;) {
		uint32_t n = img->size - at < sizeof(buf) ? img->size - at : sizeof(buf);
		if (pread(img->fd, buf, n, at) != (ssize_t)n) {
			snprintf(why, why_size, "cannot read the image");
			return -1;
		}
		crc = fpvos_crc32_update(crc, buf, n);
		at += n;
	}
	if (~crc != fpvos_get_le32(h + 0x70)) {
		snprintf(why, why_size, "image CRC mismatch");
		return -1;
	}
	return 0;
}

/* ----------------------------------------------------------- install --- */

static char status_path[PATH_MAX];
static void status(unsigned percent, int state, const char *fmt, ...) __attribute__((format(printf, 3, 4)));
static void status(unsigned percent, int state, const char *fmt, ...)
{
	char message[64], tmp[PATH_MAX + 8];
	va_list ap;
	va_start(ap, fmt);
	vsnprintf(message, sizeof(message), fmt, ap);
	va_end(ap);
	fprintf(stderr, "fpvos-update: %u%% %s\n", percent, message);
	snprintf(tmp, sizeof(tmp), "%s.new", status_path);
	FILE *f = fopen(tmp, "w");
	if (!f)
		return;
	fprintf(f, "%u %d %s\n", percent, state, message);
	if (fclose(f) == 0)
		rename(tmp, status_path);
}

static unsigned char block[MAX_BLOCK], back[MAX_BLOCK];
static uint64_t done_bytes, all_bytes;

/* Section INDEX into partition M as stock writes it (erase, write, bad blocks
 * skipped, the last block padded with zeros), each block read back; a block
 * that does not read back is marked bad and the data goes to the next one.
 * TAIL: the good blocks after the data are erased too, so UBI finds them
 * empty (stock leaves them as they were). PROGRESS: counted in the status. */
static int write_section(struct mtd *m, const struct image *img, int index, int tail, int progress)
{
	uint32_t length = img->section[index].length, used = 0;
	if (length > m->size)
		return -1;
	for (unsigned b = 0; b < mtd_blocks(m); b++) {
		if (used >= length && !tail)
			break;
		if (mtd_bad(m, b))
			continue;
		if (used >= length) {
			if (mtd_erase(m, b))
				mtd_mark_bad(m, b);
			continue;
		}
		uint32_t n = length - used < m->erasesize ? length - used : m->erasesize;
		if (pread(img->fd, block, n, img->section[index].offset + used) != (ssize_t)n)
			return -1;
		memset(block + n, 0, m->erasesize - n);
		if (mtd_erase(m, b) || mtd_write(m, b, block, m->erasesize) ||
		    mtd_read(m, b, back, m->erasesize) || memcmp(block, back, m->erasesize)) {
			fprintf(stderr, "fpvos-update: mtd%d block %u does not take the data: marked bad\n",
				m->number, b);
			mtd_erase(m, b);
			mtd_mark_bad(m, b);
			continue;
		}
		used += n;
		if (progress) {
			done_bytes += n;
			status(5 + (unsigned)(done_bytes * 85 / all_bytes), 3, "writing the %s", section_names[index]);
		}
	}
	return used == length ? 0 : -1;
}

/* Whether section INDEX is already what partition M starts with, reading it
 * the way it was written (bad blocks skipped). */
static int section_on_flash(struct mtd *m, const struct image *img, int index)
{
	uint32_t length = img->section[index].length, seen = 0;
	for (unsigned b = 0; b < mtd_blocks(m) && seen < length; b++) {
		if (mtd_bad(m, b))
			continue;
		uint32_t n = length - seen < m->erasesize ? length - seen : m->erasesize;
		if (mtd_read(m, b, back, m->erasesize) ||
		    pread(img->fd, block, n, img->section[index].offset + seen) != (ssize_t)n ||
		    memcmp(block, back, n))
			return 0;
		seen += n;
	}
	return seen == length;
}

/* The boot bank record stock's ar_bsel writes in the first page of every
 * erase block of the sel partition: "BSEL", the bank, its complement, a fixed
 * tag. */
static int select_bank(int bank)
{
	struct mtd m;
	unsigned good = 0;
	if (mtd_open(&m, 2))
		return -1;
	memset(block, 0xff, m.writesize);
	memcpy(block, "BSEL", 4);
	block[4] = (unsigned char)bank;
	block[5] = (unsigned char)(0xff ^ bank);
	memcpy(block + 6, "\xee\x98\x0c\x53", 4);
	for (unsigned b = 0; b < mtd_blocks(&m); b++) {
		if (mtd_bad(&m, b))
			continue;
		if (mtd_erase(&m, b) || mtd_write(&m, b, block, m.writesize) ||
		    mtd_read(&m, b, back, m.writesize) || memcmp(block, back, m.writesize)) {
			mtd_erase(&m, b);
			mtd_mark_bad(&m, b);
			continue;
		}
		good++;
	}
	close(m.fd);
	return good ? 0 : -1;
}

/* Bank b's kernel, rootfs and app volume (stock's /proc/mtd). */
static const int bank_mtd[2][SECTIONS] = {{0, 1, 3, 6, 8}, {0, 1, 4, 7, 9}};

static int install(const char *path)
{
	struct image img;
	char why[96];
	int booted;
	snprintf(status_path, sizeof(status_path), "%s/status", dirname(strdupa(path)));
	status(0, 3, "checking the image");
	if (exists("/run/bootsel0") == exists("/run/bootsel1")) {
		status(0, -1, "install failed: the booted bank is unknown");
		return 1;
	}
	booted = exists("/run/bootsel1");
	if (image_open(&img, path, why, sizeof(why))) {
		status(0, -1, "install failed: %s", why);
		return 1;
	}
	int bank = !booted;
	fprintf(stderr, "fpvos-update: image %u.%u.%u, booted bank %d, writing bank %d\n",
		img.version[0], img.version[1], img.version[2], booted, bank);
	all_bytes = done_bytes = 0;
	for (int i = 2; i < SECTIONS; i++) {
		if (img.section[i].upgrade && mtd_in_use(bank_mtd[bank][i])) {
			status(0, -1, "install failed: mtd%d is in use", bank_mtd[bank][i]);
			return 1;
		}
		if (img.section[i].upgrade)
			all_bytes += img.section[i].length;
	}
	if (!all_bytes || !img.section[2].upgrade || !img.section[3].upgrade || !img.section[4].upgrade) {
		/* A bank is switched to whole or not at all. */
		status(0, -1, "install failed: the image lacks a kernel, rootfs or app volume");
		return 1;
	}
	status(5, 3, "writing bank %d", bank);
	for (int i = 2; i < SECTIONS; i++) {
		struct mtd m;
		if (mtd_open(&m, bank_mtd[bank][i])) {
			status(0, -1, "install failed: cannot open mtd%d", bank_mtd[bank][i]);
			return 1;
		}
		int r = write_section(&m, &img, i, 1, 1);
		close(m.fd);
		if (r) {
			status(0, -1, "install failed: the %s did not fit mtd%d", section_names[i], bank_mtd[bank][i]);
			return 1;
		}
	}
	/* U-Boot and its environment have one copy each: written only when the
	 * image has one that differs from the flash's (fpvOS images keep the
	 * stock 18.21.10 U-Boot, and every stock image has the same
	 * environment). */
	for (int i = 0; i < 2; i++) {
		if (!img.section[i].upgrade || !img.section[i].length)
			continue;
		struct mtd m;
		if (mtd_open(&m, bank_mtd[bank][i])) {
			status(0, -1, "install failed: cannot open mtd%d", bank_mtd[bank][i]);
			return 1;
		}
		int same = section_on_flash(&m, &img, i), r = 0;
		if (same) {
			fprintf(stderr, "fpvos-update: the %s on the flash is the image's: not written\n",
				section_names[i]);
		} else {
			status(91 + i * 3, 3, "writing the %s", section_names[i]);
			r = write_section(&m, &img, i, 0, 0);
		}
		close(m.fd);
		if (r) {
			status(0, -1, "install failed: the %s did not write", section_names[i]);
			return 1;
		}
	}
	status(97, 3, "switching to bank %d", bank);
	if (select_bank(bank)) {
		status(0, -1, "install failed: the boot bank record did not write");
		return 1;
	}
	close(img.fd);
	unlink(path);
	status(100, 4, "installed in bank %d", bank);
	return 0;
}

static int verify(const char *path)
{
	struct image img;
	char why[96];
	if (image_open(&img, path, why, sizeof(why))) {
		fprintf(stderr, "fpvos-update: %s\n", why);
		return 1;
	}
	return 0;
}

/* --------------------------------------------------------- helper ------ */

static int do_reboot(void)
{
	leave_bridge();
	sync();
	if (simulated()) {
		char p[PATH_MAX];
		at(p, sizeof(p), "/rebooted");
		FILE *f = fopen(p, "w");
		if (f)
			fclose(f);
		return 0;
	}
	/* The clean system runs from RAM, its reboot copied to /tmp by stock. */
	if (getenv("FPVOS_LITE_CLEAN") && access("/tmp/reboot", X_OK) == 0)
		execl("/tmp/reboot", "reboot", (char *)NULL);
	execlp("reboot", "reboot", (char *)NULL);
	reboot(RB_AUTOBOOT);
	return 1;
}

/* What the receiver asks its helper (it runs this executable again). */
static int helper(int argc, char **argv)
{
	const char *op = argc > 1 ? argv[1] : "", *file = argc > 2 ? argv[2] : "";
	cut_after = getenv("FPVOS_LITE_CUT_AFTER") ? atol(getenv("FPVOS_LITE_CUT_AFTER")) : -1;
	read_app_version();
	if (!strcmp(op, "clean")) {
		/* Stock's way into its clean system: a flag file and a reboot. */
		char p[PATH_MAX];
		leave_bridge();
		at(p, sizeof(p), "/factory/sirius-clean-system-flag");
		FILE *f = fopen(p, "w");
		if (!f || fputs("usb\n", f) < 0 || fclose(f))
			return 1;
		sync();
		return 10;
	}
	if (!strcmp(op, "reboot"))
		return do_reboot();
	if (!strcmp(op, "install"))
		return install(file);
	if (!strcmp(op, "verify"))
		return verify(file);
	if (!strcmp(op, "normal") || !strcmp(op, "bridge")) {
		if (access(FPVOS_USB, X_OK))
			return 1;
		execl(FPVOS_USB, "fpvos-usb", "mode", op, (char *)NULL);
		return 1;
	}
	return 2;
}

/* ---------------------------------------------------------- entry ------ */

/* The clean system starts the updater with -c 0 -m 1 only: the board's -t
 * -b -e -r come from what the normal system was started with, kept in the app
 * volume (written only when they change), else -t from fpv_board_type. A file
 * from an updater without -r has three numbers. */
#define BOARD_FILE "/usrdata/fpv/air/updater.board"
static void remember_board(void)
{
	char text[64], line[64];
	int t, b, e, r = 0;
	if (!opt_clean) {
		if (!opt_t)
			return;
		snprintf(line, sizeof(line), "%d %d %d %d\n", opt_t, opt_b, opt_e, opt_r);
		if (!read_text(BOARD_FILE, text, sizeof(text)) && !strcmp(text, line))
			return;
		char p[PATH_MAX], tmp[PATH_MAX + 8];
		at(p, sizeof(p), BOARD_FILE);
		snprintf(tmp, sizeof(tmp), "%s.new", p);
		FILE *f = fopen(tmp, "w");
		if (f && fputs(line, f) >= 0 && fclose(f) == 0) {
			rename(tmp, p);
			sync();
		} else if (f) {
			unlink(tmp);
		}
		return;
	}
	if (!opt_t && !read_text(BOARD_FILE, text, sizeof(text)) && sscanf(text, "%d %d %d %d", &t, &b, &e, &r) >= 3) {
		opt_t = t;
		opt_b = b;
		opt_e = e;
		opt_r = r;
	}
	if (!opt_t && (!read_text("/tmp/fpv_board_type", text, sizeof(text)) ||
		       !read_text("/usrdata/fpv/fpv_board_type", text, sizeof(text))))
		opt_t = atoi(text);
}

int fpvos_board_main(int argc, char **argv)
{
	if (getenv("FPVOS_LITE_HELPER"))
		return helper(argc, argv);
	const char *name = strrchr(argv[0], '/');
	name = name ? name + 1 : argv[0];
	if (strcmp(name, "ar_fpvhs_upgrade"))
		return -1;

	opt_clean = 0;
	int c;
	while ((c = getopt(argc, argv, "b:c:d:e:i:m:r:v:t:h")) != -1) {
		switch (c) {
		case 'c': opt_clean = atoi(optarg) == 0; break;
		case 't': opt_t = atoi(optarg); break;
		case 'b': opt_b = atoi(optarg); break;
		case 'e': opt_e = atoi(optarg); break;
		case 'r': opt_r = atoi(optarg); break;
		case 'h': fprintf(stderr, "usage: %s [-c 0|1] [-m 1] [-t 472|482] [-b HW] [-e VER] [-r RF]\n", argv[0]); return 0;
		default: break;
		}
	}
	remember_board();
	read_app_version();
	char sn[24];
	read_sn(sn, sizeof(sn));
	snprintf(serial_number, sizeof(serial_number), "%d_%s", chip_index(chip_id()), sn);
	int last = opt_r ? opt_r : opt_e;
	snprintf(hardware, sizeof(hardware), "FPV-Ascent-Sky-%d-V%d.%d-%d.%d", opt_t,
		 opt_b >> 4, opt_b & 15, last >> 4, last & 15);

	char self[PATH_MAX], tty[PATH_MAX], dir[PATH_MAX];
	ssize_t n = readlink("/proc/self/exe", self, sizeof(self) - 1);
	if (n <= 0)
		return 1;
	self[n] = 0;
	snprintf(tty, sizeof(tty), "%s", getenv("FPVOS_LITE_TTY") ? getenv("FPVOS_LITE_TTY") : "/dev/ttyGS0");
	at(dir, sizeof(dir), "/tmp/fpvos-update");
	mkdir(dir, 0700);
	chmod(dir, 0700);
	setenv("FPVOS_LITE_HELPER", "1", 1);
	if (opt_clean)
		setenv("FPVOS_LITE_CLEAN", "1", 1);
	signal(SIGCHLD, SIG_DFL);
	/* Stock's scripts start this once and never again: it outlives the
	 * serial port, which goes when the gadget switches to RNDIS (58) and a
	 * session that loses its port. */
	for (;;) {
		if (access(tty, F_OK) == 0) {
			pid_t p = fork();
			if (p == 0) {
				char *args[] = {"fpvos-update-receiver", tty, dir, self, NULL};
				fpvos_receiver_clean_at_start = opt_clean;
				_exit(fpvos_receiver_main(4, args));
			}
			while (p > 0 && waitpid(p, NULL, 0) < 0 && errno == EINTR) {
			}
		}
		sleep(1);
	}
}

/* No NAND tool or stock-runtime bootstrap on this board. */
int fpvos_board_image_valid(unsigned index, const unsigned char *data, size_t size, unsigned kind)
{
	(void)index; (void)data; (void)size; (void)kind;
	return 0;
}
int fpvos_nand_main(int argc, char **argv)
{
	(void)argc; (void)argv;
	fprintf(stderr, "no NAND tool on this board\n");
	return 2;
}
int fpvos_bootstrap_main(int argc, char **argv)
{
	(void)argc; (void)argv;
	fprintf(stderr, "no bootstrap on this board\n");
	return 2;
}
