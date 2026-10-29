// SPDX-License-Identifier: GPL-3.0-only
// C adaptation of gehee/kestrel-gnd artosyn/ar8030_sky.cpp and the startup
// sequence in ar8030_source.cpp, revision 521d0d66eb792a8cf8d009325a7884398235625c.
#include "sky.h"
#include "ar8030_handshake.h"
#include <arlink.h>
#include <stdio.h>
#include <string.h>
#include <sys/time.h>

static uint32_t crc32c(const uint8_t *p, size_t n)
{
	uint32_t c = 0;
	while (n--) {
		c ^= *p++;
		for (int i = 0; i < 8; i++)
			c = (c >> 1) ^ ((c & 1) ? 0x82f63b78u : 0);
	}
	return c;
}

static void put32(uint8_t *p, uint32_t v)
{
	for (int i = 0; i < 4; i++) p[i] = v >> (8 * i);
}

static uint32_t get32(const uint8_t *p)
{
	return (uint32_t)p[0] | (uint32_t)p[1] << 8 |
	       (uint32_t)p[2] << 16 | (uint32_t)p[3] << 24;
}

int sky_send_next(struct sky *sky, int fd)
{
	if (sky->sent >= ar_handshake_n) return 0;
	const struct ar_hs_frame *tmpl = &ar_handshake[sky->sent];
	uint8_t frame[128];
	if (tmpl->len < 12 || tmpl->len > sizeof(frame)) return -1;
	memcpy(frame, tmpl->data, tmpl->len);
	uint8_t *body = frame + 7;
	frame[3] = sky->sent + 1;
	frame[2] = frame[3] + frame[4] + frame[5];
	if (frame[6] == 0x22) { body[0] = 25; body[1] = 0; }
	if (frame[6] == 0x10) {
		struct timeval tv;
		if (gettimeofday(&tv, NULL)) return -1;
		put32(body + 1, (uint32_t)tv.tv_sec);
		put32(body + 5, (uint32_t)tv.tv_usec);
		body[21] = 60;
		body[45] = 25; body[46] = 0;
	}
	put32(frame + tmpl->len - 4, crc32c(frame, tmpl->len - 4));
	int n = bb_socket_write(fd, frame, tmpl->len, 500);
	if (n != (int)tmpl->len) {
		fprintf(stderr, "air command 0x%02x write failed: %d\n", frame[6], n);
		return -1;
	}
	printf("air command seq=%u cmd=0x%02x sent\n", frame[3], frame[6]);
	sky->sent++;
	return 1;
}

void sky_receive(struct sky *sky, const uint8_t *data, size_t len)
{
	/* A bounded stream parser: reads may split or combine control frames. */
	for (size_t i = 0; i < len; i++) {
		if (sky->used == sizeof(sky->buffer)) {
			sky->used = 0;
			sky->invalid++;
		}
		sky->buffer[sky->used++] = data[i];
		while (sky->used >= 6) {
			uint8_t *p = sky->buffer;
			size_t discard = 1;
			unsigned lf = p[4] | (unsigned)p[5] << 8;
			size_t n = (lf >> 4) + 11;
			if (p[0] == 0xfe && p[1] == 0xa5 && n >= 12 &&
			    (uint8_t)(p[3] + p[4] + p[5]) == p[2]) {
				if (sky->used < n) break;
				if (crc32c(p, n - 4) == get32(p + n - 4)) {
					discard = n;
					if ((lf & 15) == 8 && p[3] >= 1 && p[3] <= sky->sent &&
					    p[6] == ar_handshake[p[3] - 1].data[6]) {
						unsigned status = (lf >> 4) >= 2 ? p[7] : 0;
						printf("air ack seq=%u cmd=0x%02x status=%u\n", p[3], p[6], status);
						if (status) sky->rejected++;
						else if (!(sky->ack_mask & (1u << (p[3] - 1)))) {
							sky->ack_mask |= 1u << (p[3] - 1);
							sky->acknowledged++;
						}
					}
				} else sky->invalid++;
			}
			memmove(p, p + discard, sky->used - discard);
			sky->used -= discard;
		}
	}
}
