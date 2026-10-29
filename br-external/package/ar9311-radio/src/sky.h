/* SPDX-License-Identifier: GPL-3.0-only */
#ifndef FPVOS_RADIO_SKY_H
#define FPVOS_RADIO_SKY_H
#include <stddef.h>
#include <stdint.h>
struct sky {
	uint8_t buffer[8192];
	size_t used;
	unsigned sent, acknowledged, rejected, invalid;
	uint16_t ack_mask;
};
/* Send one of the ten VRX Pro startup commands, at most every 250 ms.
 * Rebuild with 1080p60 FPV video, current timestamp and fixed 25 mW air power.
 * Returns 1 while commands remain, 0 when done, -1 on failure. */
int sky_send_next(struct sky *sky, int fd);
void sky_receive(struct sky *sky, const uint8_t *data, size_t len);
#endif
