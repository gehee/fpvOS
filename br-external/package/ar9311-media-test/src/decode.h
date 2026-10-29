// SPDX-License-Identifier: MIT
#ifndef AR9311_DECODE_H
#define AR9311_DECODE_H
#include <stdint.h>
#include <stddef.h>
struct ar9311_frame {
	const uint8_t *data; /* MMAP callback only; NULL for DMA-BUF presentation. */
	unsigned stride, coded_height;
	unsigned left, top, width, height, index, buffer_index;
};
/* Complete I420 data, valid only for the duration of this callback. */
typedef int (*ar9311_frame_fn)(void *opaque, const struct ar9311_frame *frame);
int ar9311_decode(const char *device, const char *codec, const char *path,
		  unsigned expected, ar9311_frame_fn consume, void *opaque);
struct ar9311_dma_buffer { int fd; size_t size; };
struct ar9311_dma_sink {
	/* The sink owns these buffers until decode returns and scanout stops. */
	int (*allocate)(void *opaque, const struct ar9311_frame *format, unsigned count,
			struct ar9311_dma_buffer *buffers);
	/* Return the previous scanout buffer in release_index only after the
	 * page flip completes. -1 retains all dequeued buffers for now.
	 */
	int (*present)(void *opaque, const struct ar9311_frame *frame, int *release_index);
};
int ar9311_decode_dmabuf(const char *device, const char *codec, const char *path,
	unsigned expected, const struct ar9311_dma_sink *sink, void *opaque);
#endif
