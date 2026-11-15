/* SPDX-License-Identifier: GPL-3.0-only */
#define _POSIX_C_SOURCE 200809L
#include "awb.h"
#include "control.h"
#include <errno.h>
#include <signal.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>

static volatile sig_atomic_t stopping;
static void stop(int sig) { (void)sig; stopping = 1; }

static uint32_t le32(const uint8_t *p)
{
	return (uint32_t)p[0] | (uint32_t)p[1] << 8 |
	       (uint32_t)p[2] << 16 | (uint32_t)p[3] << 24;
}

static unsigned int gain(const char *arg)
{
	char *end;
	unsigned long v;
	errno = 0;
	v = strtoul(arg, &end, 10);
	if (errno || !*arg || *end || v < 128 || v > 1024) return 0;
	return v;
}

int main(int argc, char **argv)
{
	struct awb_state state = {0};
	uint8_t stats[AWB_STATS_SIZE];
	uint32_t previous = 0;
	unsigned int failures = 0, updates = 0;
	int have_previous = 0;
	struct sigaction action = {.sa_handler = stop};
	int control_fd = -1, locked = 0;
	if (argc != 4 && argc != 6) goto usage;
	if (argc == 6) {
		char *end; long fd = strtol(argv[5], &end, 10);
		if (strcmp(argv[4], "--control-fd") || !*argv[5] || *end || fd < 0 || fd > INT_MAX) goto usage;
		control_fd = (int)fd;
	}
	state.red = state.anchor_red = gain(argv[2]);
	state.blue = state.anchor_blue = gain(argv[3]);
	if (!state.red || !state.blue) goto usage;
	if (!strcmp(argv[1], "grbg")) {
		state.r = 1; state.g1 = 0; state.g2 = 3; state.b = 2;
	} else if (!strcmp(argv[1], "rggb")) {
		state.r = 0; state.g1 = 1; state.g2 = 2; state.b = 3;
	} else if (!strcmp(argv[1], "bggr")) {
		state.r = 3; state.g1 = 1; state.g2 = 2; state.b = 0;
	} else if (!strcmp(argv[1], "gbrg")) {
		state.r = 2; state.g1 = 0; state.g2 = 3; state.b = 1;
	} else goto usage;
	sigemptyset(&action.sa_mask);
	sigaction(SIGINT, &action, NULL);
	sigaction(SIGTERM, &action, NULL);
	while (!stopping) {
		struct timespec delay = {.tv_nsec = 100000000};
		FILE *file;
		size_t len = 0;
		unsigned int red = state.red, blue = state.blue, zones;
		nanosleep(&delay, NULL);
		if (stopping) break;
		file = fopen("/sys/kernel/debug/ar-isp/stats_raw", "rb");
		if (file) { len = fread(stats, 1, sizeof(stats), file); fclose(file); }
		if (len != sizeof(stats) || le32(stats) != le32(stats + sizeof(stats) - 4) ||
		    (have_previous && le32(stats) == previous)) {
			if (++failures >= 50) {
				fprintf(stderr, "ar9311-awbd: no fresh coherent ISP statistics\n");
				return 1;
			}
			continue;
		}
		failures = 0;
		have_previous = 1;
		previous = le32(stats);
		struct camera_request request;
		int changed = camera_receive(control_fd, &request);
		if (changed < 0) break;
		if (changed && !camera_wb_valid(&request)) {
			camera_reply(control_fd, 0, request.value, 0, 0);
			changed = 0;
		}
		if (changed) {
			locked = request.value == -1;
			if (request.gains) { state.red = request.red; state.blue = request.blue; }
		}
		zones = locked ? 0 : awb_update(&state, stats + 4);
		if (changed || red != state.red || blue != state.blue) {
			int failed;
			file = fopen("/sys/kernel/debug/ar-isp/white_balance", "w");
			if (!file) { perror("ar9311-awbd: white balance"); return 1; }
			failed = fprintf(file, "%u\n", state.red * 65536 + state.blue) < 0;
			if (fclose(file)) failed = 1;
			if (failed) { perror("ar9311-awbd: write white balance"); return 1; }
		}
		if (changed) {
			fprintf(stderr, "WB applied=%d red=%u blue=%u\n", locked ? -1 : 0, state.red, state.blue);
			camera_reply(control_fd, 1, locked ? -1 : 0, state.red, state.blue);
		}
		if (!(updates++ % 50))
			fprintf(stderr, "AWB zones=%u red=%u blue=%u\n", zones, state.red, state.blue);
	}
	return 0;
usage:
	fprintf(stderr, "Usage: ar9311-awbd STATS_ORDER RED BLUE [--control-fd FD] (Q8 gains 128..1024)\n");
	return 2;
}
