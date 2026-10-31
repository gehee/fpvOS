// SPDX-License-Identifier: MIT
/* Stateful V4L2 decoding of one bounded Annex-B clip. The callback sees
 * complete, validated I420 frames; its view expires when it returns.
 */
#define _POSIX_C_SOURCE 200809L
#include <errno.h>
#include <fcntl.h>
#include <linux/videodev2.h>
#include <poll.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/ioctl.h>
#include <sys/mman.h>
#include <sys/stat.h>
#include <time.h>
#include <unistd.h>
#include "decode.h"

#define MAX_BUFFERS 32
struct mapping { void *ptr; size_t size; };
static int xioctl(int fd, unsigned long op, void *arg)
{
	int r;
	do { r = ioctl(fd, op, arg); } while (r < 0 && errno == EINTR);
	return r;
}
static int64_t milliseconds(void)
{
	struct timespec t;
	clock_gettime(CLOCK_MONOTONIC, &t);
	return (int64_t)t.tv_sec * 1000 + t.tv_nsec / 1000000;
}
static int buffers(int fd, enum v4l2_buf_type type, unsigned count,
		   struct mapping *maps)
{
	struct v4l2_requestbuffers r = { .type = type, .memory = V4L2_MEMORY_MMAP,
		.count = count };
	if (xioctl(fd, VIDIOC_REQBUFS, &r) < 0) return -1;
	if (!r.count || r.count > MAX_BUFFERS) { errno = EOVERFLOW; return -1; }
	for (unsigned i = 0; i < r.count; i++) {
		struct v4l2_plane p = {0};
		struct v4l2_buffer b = { .type = type, .memory = V4L2_MEMORY_MMAP,
			.index = i, .length = 1, .m.planes = &p };
		if (xioctl(fd, VIDIOC_QUERYBUF, &b) < 0) return -1;
		maps[i].size = p.length;
		maps[i].ptr = mmap(NULL, p.length, PROT_READ | PROT_WRITE,
				   MAP_SHARED, fd, p.m.mem_offset);
		if (maps[i].ptr == MAP_FAILED) { maps[i].ptr = NULL; return -1; }
	}
	return (int)r.count;
}
static int queue(int fd, enum v4l2_buf_type type, unsigned index,
		 size_t length, size_t used, int dmabuf)
{
	struct v4l2_plane p = { .length = length, .bytesused = used };
	struct v4l2_buffer b = { .type = type, .memory = V4L2_MEMORY_MMAP,
		.index = index, .length = 1, .m.planes = &p };
	if (dmabuf >= 0) { b.memory = V4L2_MEMORY_DMABUF; p.m.fd = dmabuf; }
	return xioctl(fd, VIDIOC_QBUF, &b);
}
static int decode(const char *device, const char *codec, const char *path,
	unsigned expected, ar9311_frame_fn consume, const struct ar9311_dma_sink *sink,
	void *opaque)
{
	int fd = -1, input = -1, ret = -1, ncap = 0;
	int output_on = 0, capture_on = 0;
	unsigned frames = 0;
	struct ar9311_dma_buffer shared[MAX_BUFFERS];
	unsigned char held[MAX_BUFFERS] = {0};
	struct mapping output[MAX_BUFFERS] = {0}, capture[MAX_BUFFERS] = {0};
	enum v4l2_buf_type ot = V4L2_BUF_TYPE_VIDEO_OUTPUT_MPLANE;
	enum v4l2_buf_type ct = V4L2_BUF_TYPE_VIDEO_CAPTURE_MPLANE;
	struct v4l2_format fmt = { .type = V4L2_BUF_TYPE_VIDEO_OUTPUT_MPLANE };
	struct v4l2_capability cap = {0};
	struct stat st;
	struct v4l2_event_subscription sub = { .type = V4L2_EVENT_SOURCE_CHANGE };
	struct v4l2_selection sel = { .type = V4L2_BUF_TYPE_VIDEO_CAPTURE,
		.target = V4L2_SEL_TGT_COMPOSE_DEFAULT };
	struct v4l2_decoder_cmd stop = { .cmd = V4L2_DEC_CMD_STOP };
	int64_t deadline;
	if ((!consume && (!sink || !sink->allocate || !sink->present)) || !expected || expected > 10000 ||
	    (strcmp(codec, "h264") && strcmp(codec, "hevc"))) {
		errno = EINVAL;
		return -1;
	}
#define CHECK(expr, what) do { if ((expr) < 0) { perror(what); goto done; } } while (0)
	CHECK(input = open(path, O_RDONLY), "input");
	CHECK(fstat(input, &st), "input stat");
	if (st.st_size <= 0 || st.st_size > 1024 * 1024) {
		fprintf(stderr, "Use a short clip of at most 1 MiB\n"); goto done;
	}
	CHECK(fd = open(device, O_RDWR | O_NONBLOCK), "decoder");
	CHECK(xioctl(fd, VIDIOC_QUERYCAP, &cap), "QUERYCAP");
	fprintf(stderr, "decoder=%s card=%s\n", cap.driver, cap.card);
	CHECK(xioctl(fd, VIDIOC_SUBSCRIBE_EVENT, &sub), "SUBSCRIBE_EVENT");
	fmt.fmt.pix_mp.pixelformat = !strcmp(codec, "hevc") ? V4L2_PIX_FMT_HEVC : V4L2_PIX_FMT_H264;
	fmt.fmt.pix_mp.width = 640; fmt.fmt.pix_mp.height = 360;
	fmt.fmt.pix_mp.colorspace = V4L2_COLORSPACE_REC709;
	fmt.fmt.pix_mp.plane_fmt[0].sizeimage = st.st_size;
	CHECK(xioctl(fd, VIDIOC_S_FMT, &fmt), "S_FMT output");
	CHECK(buffers(fd, ot, 1, output), "OUTPUT buffers");
	if ((uint64_t)st.st_size > output[0].size) { errno = EOVERFLOW; perror("input size"); goto done; }
	for (size_t used = 0; used < (size_t)st.st_size;) {
		ssize_t n = read(input, (uint8_t *)output[0].ptr + used, st.st_size - used);
		if (n < 0 && errno == EINTR) continue;
		if (n <= 0) { fprintf(stderr, "short input\n"); goto done; }
		used += (size_t)n;
	}
	CHECK(queue(fd, ot, 0, output[0].size, st.st_size, -1), "QBUF output");
	CHECK(xioctl(fd, VIDIOC_STREAMON, &ot), "STREAMON output"); output_on = 1;
	deadline = milliseconds() + 10000;
	for (;;) {
		struct v4l2_event ev = {0};
		struct pollfd p = { .fd = fd, .events = POLLPRI };
		if (milliseconds() > deadline) { fprintf(stderr, "source-change timeout\n"); goto done; }
		CHECK(poll(&p, 1, 100), "poll source");
		if (xioctl(fd, VIDIOC_DQEVENT, &ev) == 0) {
			if (ev.type == V4L2_EVENT_SOURCE_CHANGE) break;
		} else if (errno != EAGAIN) { perror("DQEVENT"); goto done; }
	}
	memset(&fmt, 0, sizeof(fmt)); fmt.type = ct;
	CHECK(xioctl(fd, VIDIOC_G_FMT, &fmt), "G_FMT capture");
	fmt.fmt.pix_mp.pixelformat = V4L2_PIX_FMT_YUV420;
	CHECK(xioctl(fd, VIDIOC_S_FMT, &fmt), "S_FMT capture");
	if (fmt.fmt.pix_mp.pixelformat != V4L2_PIX_FMT_YUV420 || fmt.fmt.pix_mp.num_planes != 1) {
		fprintf(stderr, "single-plane I420 required\n"); goto done;
	}
	CHECK(xioctl(fd, VIDIOC_G_SELECTION, &sel), "G_SELECTION");
	fprintf(stderr, "visible=%ux%u coded=%ux%u stride=%u\n", sel.r.width, sel.r.height,
		fmt.fmt.pix_mp.width, fmt.fmt.pix_mp.height, fmt.fmt.pix_mp.plane_fmt[0].bytesperline);
	const struct v4l2_pix_format_mplane *pix = &fmt.fmt.pix_mp;
	size_t stride = pix->plane_fmt[0].bytesperline;
	if (!stride || stride > 8192 || !pix->height || pix->height > 4320 ||
	    ((stride | pix->height) & 1) || sel.r.left < 0 || sel.r.top < 0 ||
	    !sel.r.width || !sel.r.height ||
	    ((sel.r.left | sel.r.top | sel.r.width | sel.r.height) & 1) ||
	    (size_t)sel.r.left + sel.r.width > stride ||
	    (size_t)sel.r.top + sel.r.height > pix->height) {
		fprintf(stderr, "invalid I420 geometry\n"); goto done;
	}
	if (sink) {
		struct v4l2_control ctrl = {.id = V4L2_CID_MIN_BUFFERS_FOR_CAPTURE};
		CHECK(xioctl(fd, VIDIOC_G_CTRL, &ctrl), "minimum capture buffers");
		if (ctrl.value < 1 || ctrl.value > MAX_BUFFERS - 2) {
			fprintf(stderr, "unsupported capture pool size\n"); goto done;
		}
		struct v4l2_requestbuffers req = {.type = ct, .memory = V4L2_MEMORY_DMABUF,
			.count = ctrl.value + 2};
		CHECK(xioctl(fd, VIDIOC_REQBUFS, &req), "DMABUF capture request");
		if (!req.count || req.count > MAX_BUFFERS) { errno = EOVERFLOW; goto done; }
		ncap = req.count;
		struct ar9311_frame format = {.stride = stride, .coded_height = pix->height,
			.left = sel.r.left, .top = sel.r.top, .width = sel.r.width, .height = sel.r.height};
		CHECK(sink->allocate(opaque, &format, ncap, shared), "allocate shared buffers");
		for (int i = 0; i < ncap; i++) {
			if (shared[i].fd < 0 || shared[i].size < pix->plane_fmt[0].sizeimage) {
				errno = EINVAL; goto done;
			}
			capture[i].size = shared[i].size;
		}
	} else {
		CHECK(ncap = buffers(fd, ct, 1, capture), "CAPTURE buffers");
	}
	fprintf(stderr, "capture_buffers=%d memory=%s\n", ncap, sink ? "DMABUF" : "MMAP");
	for (int i = 0; i < ncap; i++)
		CHECK(queue(fd, ct, i, capture[i].size, 0, sink ? shared[i].fd : -1), "QBUF capture");

	CHECK(xioctl(fd, VIDIOC_STREAMON, &ct), "STREAMON capture"); capture_on = 1;
	CHECK(xioctl(fd, VIDIOC_DECODER_CMD, &stop), "decoder STOP/drain");
	deadline = milliseconds() + 15000;
	for (;;) {
		struct v4l2_plane plane = {0};
		struct v4l2_buffer b = { .type = ct,
			.memory = sink ? V4L2_MEMORY_DMABUF : V4L2_MEMORY_MMAP,
			.length = 1, .m.planes = &plane };
		struct pollfd p = { .fd = fd, .events = POLLIN };
		if (milliseconds() > deadline) { fprintf(stderr, "frame/drain timeout (%u frames)\n", frames); goto done; }
		CHECK(poll(&p, 1, 100), "poll frame");
		if (xioctl(fd, VIDIOC_DQBUF, &b) < 0) {
			if (errno == EAGAIN) continue;
			perror("DQBUF capture"); goto done;
		}
		if (b.index >= (unsigned)ncap || (b.flags & V4L2_BUF_FLAG_ERROR)) {
			fprintf(stderr, "invalid/error frame\n"); goto done;
		}
		int release = sink ? -1 : (int)b.index;
		held[b.index] = 1;
		if (plane.bytesused) {
			size_t required = stride * pix->height * 3 / 2;
			if (plane.bytesused > capture[b.index].size || (sink && plane.data_offset) ||
			    plane.data_offset > plane.bytesused ||
			    plane.bytesused - plane.data_offset < required) {
				fprintf(stderr, "short/invalid I420 buffer\n"); goto done;
			}
			struct ar9311_frame frame = {
				.data = sink ? NULL : (const uint8_t *)capture[b.index].ptr + plane.data_offset,
				.stride = stride, .coded_height = pix->height,
				.left = sel.r.left, .top = sel.r.top,
				.width = sel.r.width, .height = sel.r.height,
				.index = frames, .buffer_index = b.index,
			};
			if (sink) {
				CHECK(sink->present(opaque, &frame, &release), "present DMA frame");
				if (release == (int)b.index) {
					fprintf(stderr, "cannot release current scanout buffer\n"); goto done;
				}
			} else {
				CHECK(consume(opaque, &frame), "consume frame");
			}
			frames++;
			/* Presentation may deliberately pace playback. Bound stalls,
			 * not the duration of a successfully progressing clip.
			 */
			deadline = milliseconds() + 15000;
		}

		if (b.flags & V4L2_BUF_FLAG_LAST) break;
		if (release >= 0) {
			if (release >= ncap || !held[release]) {
				fprintf(stderr, "invalid buffer release\n"); goto done;
			}
			CHECK(queue(fd, ct, release, capture[release].size, 0,
				    sink ? shared[release].fd : -1), "requeue capture");
			held[release] = 0;
		}
	}
	if (frames != expected) { fprintf(stderr, "expected %u frames, got %u\n", expected, frames); goto done; }
	ret = 0;
done:
	if (output_on && xioctl(fd, VIDIOC_STREAMOFF, &ot) < 0) { perror("STREAMOFF output"); ret = -1; }
	if (capture_on && xioctl(fd, VIDIOC_STREAMOFF, &ct) < 0) { perror("STREAMOFF capture"); ret = -1; }
	for (unsigned i = 0; i < MAX_BUFFERS; i++) {
		if (output[i].ptr) munmap(output[i].ptr, output[i].size);
		if (capture[i].ptr) munmap(capture[i].ptr, capture[i].size);
	}
	if (fd >= 0 && close(fd) < 0) ret = -1;
	if (input >= 0) close(input);
	if (!ret) fprintf(stderr, "PASS frames=%u width=%u height=%u format=I420\n", frames, sel.r.width, sel.r.height);
	return ret;
}

int ar9311_decode(const char *device, const char *codec, const char *path,
		  unsigned expected, ar9311_frame_fn consume, void *opaque)
{
	return decode(device, codec, path, expected, consume, NULL, opaque);
}
int ar9311_decode_dmabuf(const char *device, const char *codec, const char *path,
	unsigned expected, const struct ar9311_dma_sink *sink, void *opaque)
{
	return decode(device, codec, path, expected, NULL, sink, opaque);
}
