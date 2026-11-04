// SPDX-License-Identifier: MIT
/* Capture YUV420M and encode HEVC through DMA-BUF, without copying pixels.
 * Camera buffers stay out of the capture queue until the encoder returns them.
 */
#define _POSIX_C_SOURCE 200809L
#include <errno.h>
#include <fcntl.h>
#include <linux/videodev2.h>
#include <poll.h>
#include <signal.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/ioctl.h>
#include <sys/mman.h>
#include <time.h>
#include <unistd.h>

#define BUFFERS 5
#define PLANES 3
#define CAPTURE V4L2_BUF_TYPE_VIDEO_CAPTURE_MPLANE
#define OUTPUT V4L2_BUF_TYPE_VIDEO_OUTPUT_MPLANE
#define MMAP V4L2_MEMORY_MMAP
#define DMABUF V4L2_MEMORY_DMABUF

struct camera_plane { int fd; unsigned int size; };
struct coded_buffer { void *data; unsigned int size; };
static struct camera_plane camera[BUFFERS][PLANES];
static struct coded_buffer coded[BUFFERS];
static int capture_fd = -1, encoder_fd = -1;
static int capture_running, output_running, encoder_running;
static FILE *output;
static volatile sig_atomic_t interrupted;

static int xioctl(int fd, unsigned long request, void *arg)
{
	int ret;
	do { ret = ioctl(fd, request, arg); } while (ret < 0 && errno == EINTR);
	return ret;
}

static void cleanup(void)
{
	enum v4l2_buf_type type = CAPTURE;
	if (capture_running) xioctl(capture_fd, VIDIOC_STREAMOFF, &type);
	type = OUTPUT;
	if (output_running) xioctl(encoder_fd, VIDIOC_STREAMOFF, &type);
	type = CAPTURE;
	if (encoder_running) xioctl(encoder_fd, VIDIOC_STREAMOFF, &type);
	for (unsigned int i = 0; i < BUFFERS; i++) {
		if (coded[i].data && coded[i].data != MAP_FAILED)
			munmap(coded[i].data, coded[i].size);
		for (unsigned int j = 0; j < PLANES; j++)
			if (camera[i][j].fd >= 0) close(camera[i][j].fd);
	}
	if (encoder_fd >= 0) close(encoder_fd);
	if (capture_fd >= 0) close(capture_fd);
	if (output && output != stdout) fclose(output);
}

static void fail(const char *what)
{
	perror(what);
	exit(EXIT_FAILURE);
}

static void checked(int fd, unsigned long request, void *arg, const char *what)
{
	if (xioctl(fd, request, arg)) fail(what);
}

static struct v4l2_buffer buffer(unsigned int type, unsigned int memory,
		unsigned int index, unsigned int planes, struct v4l2_plane *p)
{
	return (struct v4l2_buffer) {
		.type = type, .memory = memory, .index = index,
		.length = planes, .m.planes = p,
	};
}

static void queue_camera(unsigned int index)
{
	struct v4l2_plane p[PLANES] = {0};
	struct v4l2_buffer b = buffer(CAPTURE, MMAP, index, PLANES, p);
	checked(capture_fd, VIDIOC_QBUF, &b, "camera QBUF");
}

static void request_buffers(int fd, unsigned int type, unsigned int memory)
{
	struct v4l2_requestbuffers r = {
		.type = type, .memory = memory, .count = BUFFERS,
	};
	checked(fd, VIDIOC_REQBUFS, &r, "REQBUFS");
	if (r.count < BUFFERS) { errno = ENOMEM; fail("buffer count"); }
}

static void control(unsigned int id, int value)
{
	struct v4l2_control c = { .id = id, .value = value };
	checked(encoder_fd, VIDIOC_S_CTRL, &c, "encoder control");
}

static double monotonic(void)
{
	struct timespec t;
	if (clock_gettime(CLOCK_MONOTONIC, &t)) fail("clock_gettime");
	return t.tv_sec + t.tv_nsec / 1e9;
}

static void interrupt(int signo)
{
	(void)signo;
	interrupted = 1;
}

int main(int argc, char **argv)
{
	if (argc != 5) {
		fprintf(stderr, "usage: %s CAMERA ENCODER FRAMES OUTPUT.h265|-\n"
			"FRAMES: 1..36000; SIGINT/SIGTERM drains queued frames.\n", argv[0]);
		return 2;
	}
	char *end;
	errno = 0;
	unsigned long target = strtoul(argv[3], &end, 10);
	if (errno || *end || !target || target > 36000) return 2;
	for (unsigned int i = 0; i < BUFFERS; i++)
		for (unsigned int j = 0; j < PLANES; j++) camera[i][j].fd = -1;
	atexit(cleanup);
	signal(SIGINT, interrupt);
	signal(SIGTERM, interrupt);
	signal(SIGPIPE, SIG_IGN);
	capture_fd = open(argv[1], O_RDWR | O_NONBLOCK | O_CLOEXEC);
	encoder_fd = open(argv[2], O_RDWR | O_NONBLOCK | O_CLOEXEC);
	if (capture_fd < 0 || encoder_fd < 0) fail("open video node");
	output = !strcmp(argv[4], "-") ? stdout : fopen(argv[4], "wb");
	if (!output) fail("open output");

	struct v4l2_format cf = { .type = CAPTURE };
	checked(capture_fd, VIDIOC_G_FMT, &cf, "camera G_FMT");
	struct v4l2_pix_format_mplane *f = &cf.fmt.pix_mp;
	if (f->pixelformat != V4L2_PIX_FMT_YUV420M || f->num_planes != PLANES) {
		fprintf(stderr, "camera must provide three-plane YUV420M\n");
		return 3;
	}
	request_buffers(capture_fd, CAPTURE, MMAP);
	for (unsigned int i = 0; i < BUFFERS; i++) {
		struct v4l2_plane p[PLANES] = {0};
		struct v4l2_buffer b = buffer(CAPTURE, MMAP, i, PLANES, p);
		checked(capture_fd, VIDIOC_QUERYBUF, &b, "camera QUERYBUF");
		for (unsigned int j = 0; j < PLANES; j++) {
			struct v4l2_exportbuffer x = {
				.type = CAPTURE, .index = i, .plane = j,
				.flags = O_CLOEXEC | O_RDWR,
			};
			checked(capture_fd, VIDIOC_EXPBUF, &x, "camera EXPBUF");
			camera[i][j].fd = x.fd;
			camera[i][j].size = p[j].length;
		}
		queue_camera(i);
	}

	struct v4l2_format ef = cf;
	ef.type = OUTPUT;
	for (unsigned int j = 0; j < PLANES; j++)
		ef.fmt.pix_mp.plane_fmt[j].sizeimage = camera[0][j].size;
	checked(encoder_fd, VIDIOC_S_FMT, &ef, "encoder source S_FMT");
	for (unsigned int j = 0; j < PLANES; j++) {
		if (ef.fmt.pix_mp.plane_fmt[j].bytesperline != f->plane_fmt[j].bytesperline ||
		    ef.fmt.pix_mp.plane_fmt[j].sizeimage > camera[0][j].size) {
			fprintf(stderr, "encoder substituted stride or requires a larger source buffer\n");
			return 3;
		}
	}
	ef = (struct v4l2_format) { .type = CAPTURE };
	ef.fmt.pix_mp = (struct v4l2_pix_format_mplane) {
		.width = f->width, .height = f->height, .pixelformat = V4L2_PIX_FMT_HEVC,
		.field = V4L2_FIELD_NONE, .num_planes = 1,
	};
	checked(encoder_fd, VIDIOC_S_FMT, &ef, "encoder HEVC S_FMT");
	if (ef.fmt.pix_mp.width != f->width || ef.fmt.pix_mp.height != f->height ||
	    ef.fmt.pix_mp.pixelformat != V4L2_PIX_FMT_HEVC || ef.fmt.pix_mp.num_planes != 1) {
		fprintf(stderr, "encoder substituted coded format\n");
		return 3;
	}
	struct v4l2_streamparm sp = { .type = OUTPUT };
	sp.parm.output.timeperframe = (struct v4l2_fract) {1, 60};
	checked(encoder_fd, VIDIOC_S_PARM, &sp, "encoder frame rate");
	control(V4L2_CID_MPEG_VIDEO_HEVC_LEVEL, V4L2_MPEG_VIDEO_HEVC_LEVEL_4_1);
	control(V4L2_CID_MPEG_VIDEO_BITRATE, 8000000);
	control(V4L2_CID_MPEG_VIDEO_GOP_SIZE, 60);
	control(V4L2_CID_MPEG_VIDEO_FRAME_RC_ENABLE, 1);
	control(V4L2_CID_MPEG_VIDEO_HEVC_I_FRAME_QP, 35);
	control(V4L2_CID_MPEG_VIDEO_PREPEND_SPSPPS_TO_IDR, 1);
	control(V4L2_CID_MPEG_VIDEO_AU_DELIMITER, 0);
	request_buffers(encoder_fd, OUTPUT, DMABUF);
	request_buffers(encoder_fd, CAPTURE, MMAP);
	for (unsigned int i = 0; i < BUFFERS; i++) {
		struct v4l2_plane p = {0};
		struct v4l2_buffer b = buffer(CAPTURE, MMAP, i, 1, &p);
		checked(encoder_fd, VIDIOC_QUERYBUF, &b, "coded QUERYBUF");
		coded[i].size = p.length;
		coded[i].data = mmap(NULL, p.length, PROT_READ, MAP_SHARED,
				encoder_fd, p.m.mem_offset);
		if (coded[i].data == MAP_FAILED) fail("coded mmap");
		checked(encoder_fd, VIDIOC_QBUF, &b, "coded QBUF");
	}
	enum v4l2_buf_type ct = CAPTURE, ot = OUTPUT;
	checked(capture_fd, VIDIOC_STREAMON, &ct, "camera STREAMON");
	capture_running = 1;
	checked(encoder_fd, VIDIOC_STREAMON, &ot, "encoder OUTPUT STREAMON");
	output_running = 1;
	checked(encoder_fd, VIDIOC_STREAMON, &ct, "encoder CAPTURE STREAMON");
	encoder_running = 1;
	unsigned long sent = 0, got = 0, returned = 0;
	unsigned int warmup = 8;
	int held[BUFFERS] = {0};
	double start = monotonic(), progress = start;
	size_t bytes = 0;
	while (got < target || returned < sent) {
		if (interrupted) target = sent;
		struct v4l2_plane p[PLANES] = {0};
		struct v4l2_buffer b = buffer(OUTPUT, DMABUF, 0, PLANES, p);
		while (xioctl(encoder_fd, VIDIOC_DQBUF, &b) == 0) {
			if (b.index >= BUFFERS || !held[b.index] || (b.flags & V4L2_BUF_FLAG_ERROR)) {
				fprintf(stderr, "encoder rejected source buffer\n");
				return 4;
			}
			held[b.index] = 0;
			queue_camera(b.index);
			returned++;
			progress = monotonic();
			memset(p, 0, sizeof(p));
			b = buffer(OUTPUT, DMABUF, 0, PLANES, p);
		}
		if (errno != EAGAIN) fail("encoder source DQBUF");
		memset(p, 0, sizeof(p));
		b = buffer(CAPTURE, MMAP, 0, 1, p);
		while (xioctl(encoder_fd, VIDIOC_DQBUF, &b) == 0) {
			if (b.index >= BUFFERS || p[0].bytesused > coded[b.index].size ||
			    p[0].bytesused <= p[0].data_offset || (b.flags & V4L2_BUF_FLAG_ERROR)) {
				fprintf(stderr, "invalid encoded buffer\n");
				return 4;
			}
			size_t n = p[0].bytesused - p[0].data_offset;
			if (fwrite((char *)coded[b.index].data + p[0].data_offset, 1, n, output) != n)
				fail("write encoded data");
			bytes += n;
			got++;
			progress = monotonic();
			checked(encoder_fd, VIDIOC_QBUF, &b, "coded requeue");
			memset(p, 0, sizeof(p));
			b = buffer(CAPTURE, MMAP, 0, 1, p);
		}
		if (errno != EAGAIN) fail("coded DQBUF");
		if (sent < target) {
			memset(p, 0, sizeof(p));
			b = buffer(CAPTURE, MMAP, 0, PLANES, p);
			if (xioctl(capture_fd, VIDIOC_DQBUF, &b) == 0) {
				if (b.index >= BUFFERS || held[b.index] || (b.flags & V4L2_BUF_FLAG_ERROR)) {
					fprintf(stderr, "invalid camera buffer\n");
					return 4;
				}
				unsigned int index = b.index;
				if (warmup) {
					queue_camera(index);
					warmup--;
					progress = monotonic();
					if (!warmup) start = progress;
					continue;
				}
				struct timeval timestamp = b.timestamp;
				memset(p, 0, sizeof(p));
				b = buffer(OUTPUT, DMABUF, index, PLANES, p);
				b.timestamp = timestamp;
				for (unsigned int j = 0; j < PLANES; j++) {
					p[j].m.fd = camera[index][j].fd;
					p[j].length = camera[index][j].size;
					p[j].bytesused = camera[index][j].size;
				}
				checked(encoder_fd, VIDIOC_QBUF, &b, "encoder source QBUF");
				held[index] = 1;
				sent++;
			} else if (errno != EAGAIN) fail("camera DQBUF");
		}
		if (monotonic() - progress > 5) {
			fprintf(stderr, "stalled: submitted=%lu encoded=%lu returned=%lu\n", sent, got, returned);
			return 5;
		}
		struct pollfd pf[2] = {
			{capture_fd, sent < target ? POLLIN : 0, 0}, {encoder_fd, POLLIN, 0},
		};
		int ret = poll(pf, 2, 10);
		if (ret < 0 && errno != EINTR) fail("poll");
	}
	if (fflush(output)) fail("flush encoded data");
	double seconds = monotonic() - start;
	fprintf(stderr, "RESULT encoded=%lu returned=%lu bytes=%zu seconds=%.3f fps=%.3f pixel_copies=0\n",
		got, returned, bytes, seconds, got / seconds);
	return 0;
}
