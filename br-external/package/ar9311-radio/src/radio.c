// SPDX-License-Identifier: GPL-3.0-only
// Bounded radio bring-up and raw video-port capture, without a vendor daemon.
#include <arlink.h>
#include <errno.h>
#include <inttypes.h>
#include <poll.h>
#include <signal.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>
#include <unistd.h>
#include "sky.h"

static volatile sig_atomic_t stopping;
static void stop(int sig) { (void)sig; stopping = 1; }
static double now(void)
{
	struct timespec ts;
	clock_gettime(CLOCK_MONOTONIC, &ts);
	return ts.tv_sec + ts.tv_nsec / 1e9;
}

static void event(const uint8_t *data, uint32_t len, void *user)
{
	(void)user;
	if (len >= 3)
		printf("link: slot %u state %u -> %u\n", data[0], data[2], data[1]);
}

static int request(uint32_t code, const void *data, uint32_t len)
{
	int rc = arlink_request(code, data, len, NULL, 0, NULL, 5000);
	if (rc)
		fprintf(stderr, "request 0x%08x failed: %d\n", code, rc);
	return rc;
}

static int link_state(void)
{
	uint8_t query[2] = { 0xff, 3 }, status[512] = {0};
	uint32_t got = 0;
	int rc = arlink_request(0x01000000, query, sizeof(query), status, sizeof(status), &got, 5000);
	if (rc || got < 253 || status[0] != 1) {
		fprintf(stderr, "ground status failed: rc=%d size=%u role=%u\n", rc, got, status[0]);
		return -1;
	}
	return status[252];
}

int main(int argc, char **argv)
{
	bb_host_t *host = NULL;
	bb_dev_list_t *list = NULL;
	bb_dev_handle_t *dev = NULL;
	FILE *output = NULL;
	const char *path = NULL;
	unsigned char peer[4];
	int have_peer = 0, seconds = 10, required = 0, fd = -1, result = 1, opt;
	int stream = 0, ctrl = -1, started = 0;
	struct sky sky = {0};
	while ((opt = getopt(argc, argv, "t:o:p:rs")) != -1) {
		char *end;
		long value;
		switch (opt) {
		case 't':
			errno = 0;
			value = strtol(optarg, &end, 10);
			if (errno || *end || value < 1 || value > 86400) goto usage;
			seconds = (int)value;
			break;
		case 'o': path = optarg; break;
		case 'p': {
			unsigned int p[4]; char extra;
			if (sscanf(optarg, "%2x:%2x:%2x:%2x%c", &p[0], &p[1], &p[2], &p[3], &extra) != 4)
				goto usage;
			for (unsigned int i = 0; i < 4; i++) peer[i] = p[i];
			have_peer = 1;
			break;
		}
		case 'r': required = 1; break;
		case 's': stream = 1; break;
		default: goto usage;
		}
	}
	if (optind != argc || (stream && !have_peer)) goto usage;
	setvbuf(stdout, NULL, _IOLBF, 0);
	signal(SIGINT, stop);
	signal(SIGTERM, stop);
	if (path && !(output = fopen(path, "wbx"))) { perror(path); goto out; }
	if (bb_host_connect(&host, NULL, 0)) { fprintf(stderr, "radio connect failed\n"); goto out; }
	if (bb_dev_getlist(host, &list) < 1) { fprintf(stderr, "no radio device\n"); goto out; }
	dev = bb_dev_open(list[0]);
	bb_dev_freelist(list); list = NULL;
	if (!dev) goto out;
	printf("%s\n", arlink_version());
	/* Open8030's loader can leave the ground radio initialized. Its init
	 * then returns -7. This also denotes invalid state, so require a successful
	 * start below and validate the ground status before accepting it. */
	int init = arlink_request(0x0b000002, NULL, 0, NULL, 0, NULL, 5000);
	if (init && init != -7) {
		fprintf(stderr, "radio init failed: %d\n", init);
		goto out;
	}
	/* Bench receiver uplink: fixed 14 dBm (25 mW), before association.
	 * Match Kestrel's three-byte power-auto payload, not the old SDK struct. */
	const uint8_t power_auto[3] = { 0, 14, 14 }, power[2] = { 0, 14 };
	if (request(0x02000009, power_auto, sizeof(power_auto)) ||
	    request(0x02000008, power, sizeof(power))) goto out;
	if (have_peer && request(0x02000003, peer, sizeof(peer))) goto out;
	if (request(0x0b000000, NULL, 0)) goto out;
	started = 1;
	printf("receiver TX power: fixed 14 dBm (25 mW)\n");
	int state = link_state();
	if (state < 0) goto out;
	printf("ground radio ready, link state %d\n", state);
	if (arlink_subscribe(0, event, NULL)) goto out;
	if (stream) {
		bb_sock_opt_t options = { .tx_buf_size = 0x800, .rx_buf_size = 0x800 };
		ctrl = bb_socket_open(dev, 0, 2, 3, &options);
		if (ctrl < 0) { fprintf(stderr, "control socket failed: %d\n", ctrl); goto out; }
		printf("stream request: 1080p60, fixed 25 mW air power\n");
	}
	bb_sock_opt_t options = { .tx_buf_size = 0x800, .rx_buf_size = 0xdc00 };
	fd = bb_socket_open(dev, 0, 3, 3, &options);
	if (fd < 0) { fprintf(stderr, "video socket failed: %d\n", fd); goto out; }
	struct pollfd pollfd = { .fd = arlink_socket_poll_fd(fd), .events = POLLIN };
	if (pollfd.fd < 0) { fprintf(stderr, "arlink socket polling unavailable\n"); goto out; }
	uint8_t buffer[65536];
	uint64_t bytes = 0, reads = 0;
	double start = now(), next = start + 1, next_command = start;
	uint64_t control_bytes = 0;
	while (!stopping && now() - start < seconds) {
		if (ctrl >= 0) {
			uint8_t control[2048];
			int n = arlink_socket_read_now(ctrl, control, sizeof(control));
			if (n < 0) { fprintf(stderr, "control socket disconnected\n"); goto out; }
			if (n) { sky_receive(&sky, control, n); control_bytes += n; }
			if (state == 2 && now() >= next_command) {
				if (sky_send_next(&sky, ctrl) < 0) goto out;
				next_command = now() + 0.25;
			}
		}
		int count = arlink_socket_read_now(fd, buffer, sizeof(buffer));
		if (count < 0) { fprintf(stderr, "video read failed: %d\n", count); goto out; }
		if (count) {
			if (output && fwrite(buffer, 1, count, output) != (size_t)count) { perror("capture write"); goto out; }
			bytes += count; reads++;
		} else {
			int ready = poll(&pollfd, 1, stream ? 20 : 200);
			if ((ready < 0 && errno != EINTR) ||
			    (ready > 0 && (pollfd.revents & (POLLERR | POLLHUP | POLLNVAL)))) {
				fprintf(stderr, "video socket disconnected\n"); goto out;
			}
		}
		if (now() >= next) {
			state = link_state();
			if (state < 0) goto out;
			printf("%.1fs rx=%" PRIu64 " bytes reads=%" PRIu64 "\n", now() - start, bytes, reads);
			next = now() + 1;
		}
	}
	printf("result: rx=%" PRIu64 " bytes reads=%" PRIu64 " elapsed=%.3fs\n", bytes, reads, now() - start);
	result = required && !bytes ? 3 : 0;
	if (stream) {
		printf("control: rx=%" PRIu64 " bytes sent=%u ack=%u rejected=%u invalid=%u\n",
		       control_bytes, sky.sent, sky.acknowledged, sky.rejected, sky.invalid);
		if (sky.sent != 10 || sky.acknowledged != 10 || sky.rejected) result = 1;
	}
out:
	if (ctrl >= 0 && bb_socket_close(ctrl)) result = 1;
	if (fd >= 0 && bb_socket_close(fd)) result = 1;
	if (started) {
		if (request(0x0b000001, NULL, 0)) result = 1;
		if (request(0x0b000003, NULL, 0)) result = 1;
	}
	if (dev) bb_dev_close(dev);
	if (list) bb_dev_freelist(list);
	if (host) bb_host_disconnect(host);
	if (output && fclose(output)) { perror("capture close"); result = 1; }
	return result;
usage:
	fprintf(stderr, "Usage: %s [-t seconds] [-o new-raw-capture-file] [-p XX:XX:XX:XX] [-r] [-s]\n"
		"  -p selects an already-paired air unit in RAM; -r fails if no data arrives.\n"
		"  -s requires -p and requests 1080p60 video at 25 mW air power.\n", argv[0]);
	return 2;
}
