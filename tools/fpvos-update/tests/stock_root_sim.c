/* SPDX-License-Identifier: GPL-2.0-or-later */
/* The Gnd485 stock-root assembly on a file standing in for the stock bank:
 * stock_root_sim BANK OUT [BAD_BLOCK_INDEX]. */
#include <fcntl.h>
#include <sys/stat.h>
#include "../../../br-external/package/fpvos-update/backends/ascent-vrx/stock-root.h"
static long bad_index = -1;
static int bad(int fd, off_t at)
{
	(void)fd;
	return at / STOCK_ROOT_PEB == bad_index;
}
int main(int argc, char **argv)
{
	if (argc < 3)
		return 2;
	if (argc > 3)
		bad_index = atol(argv[3]);
	int fd = open(argv[1], O_RDONLY);
	struct stat st;
	FILE *out = fopen(argv[2], "w");
	if (fd < 0 || fstat(fd, &st) || !out)
		return 2;
	int r = ar9311_stock_root(fd, (uint32_t)st.st_size, bad, out);
	fclose(out);
	return r ? 1 : 0;
}
