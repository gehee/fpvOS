/* SPDX-License-Identifier: GPL-2.0-or-later */
#ifndef GDC_PROBE_ABI_H
#define GDC_PROBE_ABI_H
#include <linux/ioctl.h>
#include <linux/types.h>
#define GP_BYTES 0x800000
#define GP_Y_BYTES 0x240000
#define GP_U_BYTES (GP_Y_BYTES / 4)
#define GP_SRC_Y 0
#define GP_SRC_U GP_Y_BYTES
#define GP_SRC_V (GP_Y_BYTES + GP_U_BYTES)
#define GP_DST_Y (GP_Y_BYTES + 2 * GP_U_BYTES)
#define GP_DST_U (GP_DST_Y + GP_Y_BYTES)
#define GP_DST_V (GP_DST_U + GP_U_BYTES)
#define GP_LUT (GP_DST_V + GP_U_BYTES)
struct gp_job {
  __u32 sw, sh, dw, dh;
  __u32 src_offset, dst_offset;
  __u32 state, irq;
  __u64 elapsed_ns;
};
#define GP_INIT _IO('G', 0)
#define GP_RUN _IOWR('G', 1, struct gp_job)
#endif
