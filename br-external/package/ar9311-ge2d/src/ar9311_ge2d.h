/* SPDX-License-Identifier: GPL-2.0 WITH Linux-syscall-note */
#ifndef AR9311_GE2D_H
#define AR9311_GE2D_H
#include <linux/ioctl.h>
#include <linux/types.h>

#define AR_GE2D_ABI_VERSION 1
#define AR_GE2D_MAX_OVERLAYS 8
#define AR_GE2D_YUV420 1 /* planar Y, U, V; BT.709 limited range */
#define AR_GE2D_ARGB8888 2 /* little-endian B,G,R,A; straight alpha */

struct ar_ge2d_image {
	__s32 fd[3];
	__u32 offset[3];
	__u32 stride[3];
	__u32 width;
	__u32 height;
	__u32 format;
};
struct ar_ge2d_overlay {
	struct ar_ge2d_image image;
	__u32 src_x;
	__u32 src_y;
	__u32 dst_x;
	__u32 dst_y;
	__u32 width;
	__u32 height;
};
struct ar_ge2d_compose {
	__u32 version;
	__u32 flags; /* zero */
	__u32 count;
	__u32 reserved; /* zero */
	struct ar_ge2d_image video;
	struct ar_ge2d_image output;
	struct ar_ge2d_overlay overlays[AR_GE2D_MAX_OVERLAYS];
};
struct ar_ge2d_caps {
	__u32 version;
	__u32 max_width;
	__u32 max_height;
	__u32 max_overlays;
};
/* Synchronous. Caller owns all buffers exclusively until return; source video
 * and HUD must remain immutable, output must not alias any input. Publish the
 * output to an encoder only after success. No raw addresses/commands accepted.
 * On EIO/ETIMEDOUT the engine is disabled and its buffers retained until reboot.
 */
#define AR_GE2D_GET_CAPS _IOR('G', 0x40, struct ar_ge2d_caps)
#define AR_GE2D_COMPOSE _IOW('G', 0x41, struct ar_ge2d_compose)
#endif
