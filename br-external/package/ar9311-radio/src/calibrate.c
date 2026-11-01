// SPDX-License-Identifier: GPL-3.0-only
// Merge the host factory power-offset schema, never arbitrary JSON settings.
#define _POSIX_C_SOURCE 200809L
#include <jansson.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <unistd.h>

#define MAX_INPUT (64 * 1024)

static json_t *load(const char *path)
{
	char *buf = malloc(MAX_INPUT + 1);
	FILE *f = fopen(path, "rb");
	json_t *root = NULL;
	json_error_t error;
	if (!buf || !f) goto out;
	size_t n = fread(buf, 1, MAX_INPUT + 1, f);
	if (ferror(f) || n > MAX_INPUT) goto out;
	root = json_loadb(buf, n, JSON_REJECT_DUPLICATES, &error);
	if (!json_is_object(root)) { json_decref(root); root = NULL; }
out:
	if (f) fclose(f);
	free(buf);
	if (!root) fprintf(stderr, "radio-calibrate: unreadable or invalid JSON: %s\n", path);
	return root;
}

static json_t *only(json_t *obj, const char *key)
{
	return json_is_object(obj) && json_object_size(obj) == 1 ? json_object_get(obj, key) : NULL;
}

static int save(json_t *root, const char *path)
{
	char *temp = malloc(strlen(path) + sizeof ".XXXXXX");
	if (!temp) return -1;
	sprintf(temp, "%s.XXXXXX", path);
	int fd = mkstemp(temp), rc = -1;
	if (fd < 0) goto out;
	/* Write in the destination directory, then publish only a complete file. */
	int failed = json_dumpfd(root, fd, JSON_COMPACT | JSON_SORT_KEYS) || fsync(fd);
	if (close(fd)) failed = 1;
	if (!failed && !rename(temp, path)) rc = 0;
	if (rc) unlink(temp);
out:
	free(temp);
	return rc;
}

int main(int argc, char **argv)
{
	if (argc != 4) {
		fprintf(stderr, "Usage: radio-calibrate BASE.json FACTORY.json OUTPUT.json\n");
		return 2;
	}
	/* Do not allow an accidental in-place update of either authoritative input. */
	struct stat a, b, dst;
	if (stat(argv[1], &a) || stat(argv[2], &b) ||
	    (!stat(argv[3], &dst) && ((dst.st_dev == a.st_dev && dst.st_ino == a.st_ino) ||
		(dst.st_dev == b.st_dev && dst.st_ino == b.st_ino)))) {
		fprintf(stderr, "radio-calibrate: missing input or output aliases an input\n");
		return 1;
	}
	json_t *base = load(argv[1]), *factory = load(argv[2]);
	int rc = 1;
	if (!base || !factory) goto out;
	json_t *offsets = only(only(only(only(factory, "baseband"), "basic"), "power"), "pwr_offset");
	if (!json_is_array(offsets) || json_array_size(offsets) != 4) goto invalid;
	for (size_t i = 0; i < 4; ++i) {
		json_t *v = json_array_get(offsets, i);
		/* Match Open8030's accepted JSON offset range, without coercion/clamping. */
		if (!json_is_integer(v) || json_integer_value(v) < -6 || json_integer_value(v) > 6)
			goto invalid;
	}
	json_t *bb = json_object_get(base, "baseband");
	json_t *power = json_object_get(json_object_get(bb, "basic"), "power");
	if (!json_is_object(power) || !json_is_object(json_object_get(bb, "power_calibration")))
		goto invalid;
	if (json_object_set(power, "pwr_offset", offsets) || save(base, argv[3])) {
		fprintf(stderr, "radio-calibrate: cannot publish runtime configuration\n");
		goto out;
	}
	puts("radio-calibrate: factory power offsets validated and applied");
	rc = 0;
	goto out;
invalid:
	fprintf(stderr, "radio-calibrate: unsupported factory schema or invalid power offsets/base\n");
out:
	json_decref(base);
	json_decref(factory);
	return rc;
}
