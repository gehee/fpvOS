// SPDX-License-Identifier: MIT
/* Bounded Annex-B playback through Wave521C and the fixed Gnd485 I420 plane.
 * Hardware decoding, shared DMA-BUF I420 capture/scanout, hardware color conversion.
 */
#define _POSIX_C_SOURCE 200809L
#include <errno.h>
#include <fcntl.h>
#include <poll.h>
#include <signal.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/ioctl.h>
#include <time.h>
#include <unistd.h>
#include <drm/drm.h>
#include <drm/drm_mode.h>
#include <drm/drm_fourcc.h>
#include "decode.h"

struct buffer {
	struct drm_mode_create_dumb dumb;
	uint32_t fb;
	int dmabuf;
};
static volatile sig_atomic_t stopped;
static void stop(int sig) { (void)sig; stopped = 1; }
static int ctl(int fd, unsigned long op, void *arg, const char *name)
{
	if (!ioctl(fd, op, arg))
		return 0;
	perror(name);
	return -1;
}
static int buffer_create(int fd, struct buffer *b, const struct ar9311_frame *f)
{
	b->dumb = (struct drm_mode_create_dumb) {
		.width = f->stride, .height = f->coded_height * 3 / 2, .bpp = 8
	};
	if (ctl(fd, DRM_IOCTL_MODE_CREATE_DUMB, &b->dumb, "create I420 DMA buffer")) return -1;
	if (b->dumb.pitch != f->stride) { errno = EINVAL; return -1; }
	unsigned ysize = f->stride * f->coded_height;
	struct drm_mode_fb_cmd2 fb = {
		.width = f->width, .height = f->height, .pixel_format = DRM_FORMAT_YUV420,
		.handles = {b->dumb.handle, b->dumb.handle, b->dumb.handle},
		.pitches = {f->stride, f->stride / 2, f->stride / 2},
		.offsets = {0, ysize, ysize + ysize / 4}
	};
	if (ctl(fd, DRM_IOCTL_MODE_ADDFB2, &fb, "add I420 framebuffer")) return -1;
	b->fb = fb.fb_id;
	struct drm_prime_handle prime = {.handle = b->dumb.handle, .flags = DRM_CLOEXEC | DRM_RDWR};
	if (ctl(fd, DRM_IOCTL_PRIME_HANDLE_TO_FD, &prime, "export capture DMA-BUF")) return -1;
	b->dmabuf = prime.fd;
	return 0;
}
static void buffer_destroy(int fd, struct buffer *b)
{
	struct drm_mode_destroy_dumb d = {.handle = b->dumb.handle};
	if (b->dmabuf >= 0) close(b->dmabuf);
	if (b->fb) ioctl(fd, DRM_IOCTL_MODE_RMFB, &b->fb);
	if (d.handle) ioctl(fd, DRM_IOCTL_MODE_DESTROY_DUMB, &d);
}
static int wait_flip(int fd, unsigned *sequence, uint64_t *timestamp)
{
	struct pollfd p = {.fd = fd, .events = POLLIN};
	char events[1024];
	int ret;
	do {
		ret = poll(&p, 1, 3000);
	} while (ret < 0 && errno == EINTR && !stopped);
	if (ret <= 0 || !(p.revents & POLLIN)) {
		fprintf(stderr, "Page-flip event missing (poll=%d)\n", ret);
		return -1;
	}
	ssize_t len = read(fd, events, sizeof(events));
	for (size_t off = 0; len > 0 && off + sizeof(struct drm_event) <= (size_t)len;) {
		struct drm_event *e = (void *)(events + off);
		if (e->length < sizeof(*e) || e->length > (size_t)len - off)
			break;
		if (e->type == DRM_EVENT_FLIP_COMPLETE && e->length >= sizeof(struct drm_event_vblank)) {
			struct drm_event_vblank *v = (void *)e;
			*sequence = v->sequence;
			*timestamp = (uint64_t)v->tv_sec * 1000000 + v->tv_usec;
			return 0;
		}
		off += e->length;
	}
	fprintf(stderr, "No flip completion in DRM event data\n");
	return -1;
}

struct player {
	int fd, active, front, retired;
	struct buffer buffers[32];
	struct drm_mode_crtc crtc;
	uint32_t connector;
	unsigned fps, frames, late, count;
	unsigned width, height;
	uint64_t start, last;
};
static uint64_t now_ns(void)
{
	struct timespec t;
	clock_gettime(CLOCK_MONOTONIC, &t);
	return (uint64_t)t.tv_sec * 1000000000 + t.tv_nsec;
}
static int until(uint64_t ns)
{
	struct timespec t = {.tv_sec = ns / 1000000000, .tv_nsec = ns % 1000000000};
	int r;
	do { r = clock_nanosleep(CLOCK_MONOTONIC, TIMER_ABSTIME, &t, NULL); }
	while (r == EINTR && !stopped);
	if (r) { errno = r; return -1; }
	return 0;
}
static int display_open(struct player *p, int force)
{
	uint32_t crtcs[16], connectors[16];
	struct drm_mode_card_res res = {
		.crtc_id_ptr = (uintptr_t)crtcs, .count_crtcs = 16,
		.connector_id_ptr = (uintptr_t)connectors, .count_connectors = 16
	};
	struct drm_mode_get_connector con = {0};
	p->fd = open("/dev/dri/card0", O_RDWR | O_CLOEXEC);
	if (p->fd < 0) { perror("/dev/dri/card0"); return -1; }
	if (ctl(p->fd, DRM_IOCTL_SET_MASTER, NULL, "DRM master: stop other display clients") ||
	    ctl(p->fd, DRM_IOCTL_MODE_GETRESOURCES, &res, "resources"))
		return -1;
	if (res.count_crtcs != 1 || res.count_connectors != 1) {
		fprintf(stderr, "Expected one AR9311 CRTC and connector\n"); return -1;
	}
	con.connector_id = connectors[0];
	if (ctl(p->fd, DRM_IOCTL_MODE_GETCONNECTOR, &con, "connector")) return -1;
	if (con.connection != 1 && !force) {
		fprintf(stderr, "No connected HDMI sink; use --force for fixed mode\n"); return -1;
	}
	p->connector = connectors[0];
	p->crtc = (struct drm_mode_crtc) {
		.crtc_id = crtcs[0], .set_connectors_ptr = (uintptr_t)&p->connector,
		.count_connectors = 1, .mode_valid = 1,
		.mode = {.clock = 148500, .hdisplay = 1920, .hsync_start = 2008,
			.hsync_end = 2052, .htotal = 2200, .vdisplay = 1080,
			.vsync_start = 1084, .vsync_end = 1089, .vtotal = 1125,
			.vrefresh = 60, .flags = DRM_MODE_FLAG_PHSYNC | DRM_MODE_FLAG_PVSYNC,
			.type = DRM_MODE_TYPE_DRIVER, .name = "1920x1080"}
	};
	return 0;
}
static int allocate(void *opaque, const struct ar9311_frame *f, unsigned count,
		    struct ar9311_dma_buffer *buffers)
{
	struct player *p = opaque;
	if (count > 32 || f->width != 1920 || f->height != 1080 ||
	    f->stride != 1920 || f->left || f->top || f->coded_height > 1440) {
		fprintf(stderr, "DMA scanout currently requires uncropped 1920x1080 I420\n");
		errno = EINVAL; return -1;
	}
	p->width = f->width; p->height = f->height; p->count = count;
	for (unsigned i = 0; i < count; i++) {
		if (buffer_create(p->fd, &p->buffers[i], f)) return -1;
		buffers[i] = (struct ar9311_dma_buffer) {
			.fd = p->buffers[i].dmabuf, .size = p->buffers[i].dumb.size
		};
	}
	printf("Shared %u I420 DMA buffers, %llu bytes each; no pixel mmap/copy\n",
	       count, (unsigned long long)p->buffers[0].dumb.size);
	return 0;
}
static int present(void *opaque, const struct ar9311_frame *f, int *release_index)
{
	struct player *p = opaque;
	unsigned seq;
	uint64_t ts;
	int next = f->buffer_index, previous = p->active ? p->front : -1;
	if (stopped) { errno = EINTR; return -1; }
	if (f->buffer_index >= p->count || next == previous) { errno = EINVAL; return -1; }
	if (!p->active) {
		p->crtc.fb_id = p->buffers[next].fb;
		if (ctl(p->fd, DRM_IOCTL_MODE_SETCRTC, &p->crtc, "enable I420 CRTC")) return -1;
		p->active = 1;
		p->start = now_ns();
	} else {
		uint64_t target = p->start + (uint64_t)p->frames * 1000000000 / p->fps;
		if (now_ns() > target + 1000000000 / p->fps) p->late++;
		if (until(target)) return -1;
		struct drm_mode_crtc_page_flip flip = {
			.crtc_id = p->crtc.crtc_id, .fb_id = p->buffers[next].fb,
			.flags = DRM_MODE_PAGE_FLIP_EVENT
		};
		if (ctl(p->fd, DRM_IOCTL_MODE_PAGE_FLIP, &flip, "page flip") ||
		    wait_flip(p->fd, &seq, &ts)) return -1;
	}
	/* Keep one retired buffer across another completed flip to cover any
	 * outstanding display fetches. The decoder pool includes two spares.
	 */
	*release_index = p->retired;
	p->retired = previous;
	p->last = now_ns(); p->front = next; p->frames++;
	return 0;
}
static int number(const char *s, unsigned max, unsigned *value)
{
	char *end;
	errno = 0;
	unsigned long n = strtoul(s, &end, 10);
	if (errno || !*s || *end || n > max) return -1;
	*value = n; return 0;
}
int main(int argc, char **argv)
{
	struct player p = {.fd = -1, .fps = 30, .retired = -1};
	const struct ar9311_dma_sink sink = {.allocate = allocate, .present = present};
	for (unsigned i = 0; i < 32; i++) p.buffers[i].dmabuf = -1;
	unsigned frames = 0, hold = 3;
	int force = 0, ret = 1;
	if (argc < 3) goto usage;
	for (int i = 3; i < argc; i++) {
		if (!strcmp(argv[i], "--force")) { force = 1; continue; }
		if (i + 1 >= argc) goto usage;
		const char *opt = argv[i++], *val = argv[i];
		if (!strcmp(opt, "--frames")) {
			if (number(val, 10000, &frames) || !frames) goto usage;
		} else if (!strcmp(opt, "--fps")) {
			if (number(val, 60, &p.fps) || !p.fps) goto usage;
		} else if (!strcmp(opt, "--hold")) {
			if (number(val, 3600, &hold)) goto usage;
		} else goto usage;
	}
	if (!frames || (strcmp(argv[1], "h264") && strcmp(argv[1], "hevc"))) goto usage;
	setbuf(stdout, NULL);
	signal(SIGINT, stop); signal(SIGTERM, stop);
	printf("Hardware decode -> shared I420 DMA-BUF -> HDMI; BT.709 limited, %u fps\n", p.fps);
	if (display_open(&p, force)) goto out;
	if (ar9311_decode_dmabuf("/dev/video0", argv[1], argv[2], frames, &sink, &p)) goto out;
	printf("presented=%u rate=%.3f fps late=%u pixel_copies=0\n",
	       p.frames, p.frames > 1 ? (p.frames - 1) * 1e9 / (p.last - p.start) : 0, p.late);

	if (hold && until(now_ns() + (uint64_t)hold * 1000000000)) goto out;
	ret = 0;
out:
	if (p.active) {
		p.crtc.fb_id = 0; p.crtc.count_connectors = 0; p.crtc.mode_valid = 0;
		if (ctl(p.fd, DRM_IOCTL_MODE_SETCRTC, &p.crtc, "disable CRTC")) ret = 1;
	}
	if (p.fd >= 0) {
		for (unsigned i = 0; i < 32; i++) buffer_destroy(p.fd, &p.buffers[i]);
		close(p.fd);
	}
	return ret;
usage:
	fprintf(stderr, "Usage: %s h264|hevc INPUT --frames N [--fps 1..60] [--force]\n"
		"  [--hold SECONDS]\n"
		"Short Annex-B input <=1 MiB; 1920x1080 I420 BT.709 limited; no scaling.\n", argv[0]);
	return 2;
}
