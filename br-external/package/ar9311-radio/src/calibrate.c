// SPDX-License-Identifier: GPL-3.0-only
// Merge the host factory power offsets, never arbitrary JSON settings; or,
// without usable factory data, publish the board defaults at a capped power.
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

/* Only the offsets are taken from the factory file. Other keys a unit's file
 * may carry are named and ignored, never merged. */
static json_t *member(json_t *obj, const char *key, const char *where)
{
	json_t *found = json_is_object(obj) ? json_object_get(obj, key) : NULL;
	const char *other;
	json_t *value;
	if (found)
		json_object_foreach(obj, other, value)
			if (strcmp(other, key))
				fprintf(stderr, "radio-calibrate: ignoring factory key %s%s\n", where, other);
	return found;
}

/* The board configuration must have a calibration row for this level. */
static int has_level(json_t *calibration, long long dbm)
{
	char name[16];
	const char *key, *mode;
	json_t *table, *rows;
	snprintf(name, sizeof name, "%llddbm", dbm);
	json_object_foreach(calibration, key, table)
		json_object_foreach(table, mode, rows)
			if (json_is_object(rows) && json_object_get(rows, name)) return 1;
	return 0;
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

/* Board defaults with zero offsets (the stock template's) and pwr_init capped
 * at MAX_DBM: what the radio runs on when the unit's factory data is unusable. */
static int uncalibrated(const char *base_path, const char *output, const char *max_text)
{
	char *end;
	long long max = strtoll(max_text, &end, 10);
	struct stat a, dst;
	if (!*max_text || *end || max < 9 || max > 36 || stat(base_path, &a) ||
	    (!stat(output, &dst) && dst.st_dev == a.st_dev && dst.st_ino == a.st_ino)) {
		fprintf(stderr, "radio-calibrate: invalid power cap, missing base or output aliases it\n");
		return 1;
	}
	json_t *base = load(base_path), *offsets = json_pack("[iiii]", 0, 0, 0, 0);
	int rc = 1;
	if (!base || !offsets) goto out;
	json_t *bb = json_object_get(base, "baseband");
	json_t *power = json_object_get(json_object_get(bb, "basic"), "power");
	json_t *calibration = json_object_get(bb, "power_calibration");
	json_t *init = json_object_get(power, "pwr_init");
	if (!json_is_object(power) || !json_is_object(calibration) || !json_is_integer(init)) {
		fprintf(stderr, "radio-calibrate: unsupported base configuration\n");
		goto out;
	}
	long long level = json_integer_value(init) < max ? json_integer_value(init) : max;
	if (!has_level(calibration, level)) {
		fprintf(stderr, "radio-calibrate: no board calibration row for %lld dBm\n", level);
		goto out;
	}
	if (json_object_set_new(power, "pwr_init", json_integer(level)) ||
	    json_object_set(power, "pwr_offset", offsets) || save(base, output)) {
		fprintf(stderr, "radio-calibrate: cannot publish runtime configuration\n");
		goto out;
	}
	printf("radio-calibrate: WITHOUT factory calibration: board defaults at %lld dBm, offsets 0\n", level);
	rc = 0;
out:
	json_decref(base);
	json_decref(offsets);
	return rc;
}

int main(int argc, char **argv)
{
	if (argc == 5 && !strcmp(argv[1], "--uncalibrated")) return uncalibrated(argv[2], argv[3], argv[4]);
	if (argc != 4) {
		fprintf(stderr, "Usage: radio-calibrate BASE.json FACTORY.json OUTPUT.json\n"
			"       radio-calibrate --uncalibrated BASE.json OUTPUT.json MAX_DBM\n");
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
	json_t *offsets = member(member(member(member(factory, "baseband", ""), "basic", "baseband."),
		"power", "baseband.basic."), "pwr_offset", "baseband.basic.power.");
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
	fprintf(stderr, "radio-calibrate: no valid factory power offsets, or unsupported base\n");
out:
	json_decref(base);
	json_decref(factory);
	return rc;
}
