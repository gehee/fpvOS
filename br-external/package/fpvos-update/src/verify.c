/* SPDX-License-Identifier: GPL-2.0-or-later */
#define _GNU_SOURCE
#include <errno.h>
#include <fcntl.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <sys/wait.h>
#include <unistd.h>

#include "board.h"
static uint32_t le32(const unsigned char *p)
{
	return (uint32_t)p[0] | (uint32_t)p[1] << 8 | (uint32_t)p[2] << 16 | (uint32_t)p[3] << 24;
}
static uint32_t crc(uint32_t c, const unsigned char *p, size_t n)
{
	while (n--) {
		c ^= *p++;
		for (int i = 0; i < 8; i++)
			c = (c >> 1) ^ ((0 - (c & 1)) & 0xedb88320U);
	}
	return c;
}
static int zeros(const unsigned char *p, size_t n)
{
	while (n--)
		if (*p++)
			return 0;
	return 1;
}
static int hash_matches(const char *path, const unsigned char *expected)
{
	int fds[2], status;
	char hash[65] = {0};
	if (pipe(fds))
		return 0;
	pid_t p = fork();
	if (p < 0) {
		close(fds[0]);
		close(fds[1]);
		return 0;
	}
	if (!p) {
		dup2(fds[1], 1);
		close(fds[0]);
		close(fds[1]);
		execlp("sha256sum", "sha256sum", path, (char *)NULL);
		_exit(127);
	}
	close(fds[1]);
	size_t n = 0;
	while (n < 64) {
		ssize_t r = read(fds[0], hash + n, 64 - n);
		if (r < 0 && errno == EINTR)
			continue;
		if (r <= 0)
			break;
		n += r;
	}
	/* Drain the filename so the producer cannot receive SIGPIPE. */
	char discard[256];
	while (read(fds[0], discard, sizeof(discard)) > 0) {
	}
	close(fds[0]);
	while (waitpid(p, &status, 0) < 0)
		if (errno != EINTR)
			return 0;
	return n == 64 && WIFEXITED(status) && !WEXITSTATUS(status) && !memcmp(hash, expected, 64);
}
int main(int argc, char **argv)
{
	if (argc != 3) {
		fprintf(stderr, "usage: %s PACKAGE PRIVATE_OUTPUT_DIRECTORY\n", argv[0]);
		return 2;
	}
	int result = 1, fd = -1;
	FILE *in = NULL;
	unsigned char h[512], *buf = NULL;
	struct stat st;
	char path[1024];
	if (lstat(argv[2], &st) || !S_ISDIR(st.st_mode) || st.st_uid != geteuid() ||
	    (st.st_mode & 077))
		goto done;
	fd = open(argv[1], O_RDONLY | O_NOFOLLOW | O_CLOEXEC);
	if (fd < 0 || fstat(fd, &st) || !S_ISREG(st.st_mode) || st.st_size < 512)
		goto done;
	in = fdopen(fd, "rb");
	if (!in)
		goto done;
	fd = -1;
	if (fread(h, 1, 512, in) != 512 || memcmp(h, "FPVOSUP1", 8) || le32(h + 8) != 1 ||
	    le32(h + 12) != fpvos_board.board_id || le32(h + 16) != (uint64_t)st.st_size)
		goto done;
	unsigned kind = le32(h + 88), count = le32(h + 20);
	if (kind > 1 || !fpvos_board.counts[kind] || count != fpvos_board.counts[kind] ||
	    (uint64_t)st.st_size > fpvos_board.bundle_limits[kind] ||
	    !zeros(h + 96 + 104 * count, 104 * (3 - count)))
		goto done;
	uint32_t expected = le32(h + 508);
	memset(h + 508, 0, 4);
	if (~crc(~0U, h, 512) != expected || !memchr(h + 24, 0, 64) || !zeros(h + 92, 4) ||
	    !zeros(h + 408, 100))
		goto done;
	uint64_t sum = 512;
	for (unsigned i = 0; i < count; i++) {
		unsigned char *entry = h + 96 + 104 * i;
		size_t name_len = strlen(fpvos_board.names[i]);
		uint32_t n = le32(entry + 32);
		if (memcmp(entry, fpvos_board.names[i], name_len) || !zeros(entry + name_len, 32 - name_len) ||
		    !zeros(entry + 100, 4) || !n || n > fpvos_board.limits[i])
			goto done;
		for (unsigned j = 36; j < 100; j++)
			if (!((entry[j] >= '0' && entry[j] <= '9') ||
			      (entry[j] >= 'a' && entry[j] <= 'f')))
				goto done;
		sum += n;
	}
	if (sum != (uint64_t)st.st_size)
		goto done;
	for (unsigned i = 0; i < count; i++) {
		unsigned char *entry = h + 96 + 104 * i;
		uint32_t n = le32(entry + 32);
		buf = malloc(n);
		if (!buf || fread(buf, 1, n, in) != n || !fpvos_board_image_valid(i, buf, n, kind))
			goto done;
		if (snprintf(path, sizeof(path), "%s/%s", argv[2], fpvos_board.names[i]) >= (int)sizeof(path))
			goto done;
		fd = open(path, O_WRONLY | O_CREAT | O_EXCL | O_NOFOLLOW | O_CLOEXEC, 0600);
		if (fd < 0)
			goto done;
		size_t pos = 0;
		while (pos < n) {
			ssize_t k = write(fd, buf + pos, n - pos);
			if (k < 0 && errno == EINTR)
				continue;
			if (k <= 0)
				goto done;
			pos += k;
		}
		if (fsync(fd))
			goto done;
		if (close(fd)) {
			fd = -1;
			goto done;
		}
		fd = -1;
		free(buf);
		buf = NULL;
		if (!hash_matches(path, entry + 36))
			goto done;
	}
	result = 0;
	puts("fpvOS package integrity verified; unsigned, no version-order policy");
done:
	free(buf);
	if (in)
		fclose(in);
	if (fd >= 0)
		close(fd);
	if (result)
		fprintf(stderr, "invalid/incompatible package or I/O failure\n");
	return result;
}
