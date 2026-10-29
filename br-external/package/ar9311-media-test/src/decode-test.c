// SPDX-License-Identifier: MIT
/* Write visible I420 frames for bit-exact comparison with a host decoder. */
#include <errno.h>
#include <fcntl.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
#include "decode.h"

static int write_all(int fd, const void *data, size_t size)
{
	const char *p = data;
	while (size) {
		ssize_t n = write(fd, p, size);
		if (n < 0 && errno == EINTR) continue;
		if (n <= 0) return -1;
		p += n; size -= (size_t)n;
	}
	return 0;
}
static int write_frame(void *opaque, const struct ar9311_frame *f)
{
	int out = *(int *)opaque;
	size_t ysize = (size_t)f->stride * f->coded_height, csize = ysize / 4;
	for (unsigned plane = 0; plane < 3; plane++) {
		unsigned div = plane ? 2 : 1, pitch = f->stride / div;
		size_t offset = plane ? ysize + (plane - 1) * csize : 0;
		const uint8_t *src = f->data + offset +
			(f->top / div) * pitch + f->left / div;
		for (unsigned row = 0; row < f->height / div; row++)
			if (write_all(out, src + row * pitch, f->width / div) < 0)
				return -1;
	}
	return 0;
}

int main(int argc, char **argv)
{
	char *end;
	unsigned long expected;
	int out, ret;
	if (argc != 6 || (strcmp(argv[2], "h264") && strcmp(argv[2], "hevc"))) {
		fprintf(stderr, "Usage: %s /dev/video0 h264|hevc INPUT OUTPUT.yuv FRAMES\n", argv[0]);
		return 2;
	}
	errno = 0;
	expected = strtoul(argv[5], &end, 10);
	if (errno || *end || !expected || expected > 10000) return 2;
	out = open(argv[4], O_WRONLY | O_CREAT | O_EXCL, 0644);
	if (out < 0) { perror("output"); return 1; }
	ret = ar9311_decode(argv[1], argv[2], argv[3], expected, write_frame, &out);
	if (fsync(out) < 0) { perror("fsync output"); ret = -1; }
	if (close(out) < 0) ret = -1;
	return ret ? 1 : 0;
}
