/* SPDX-License-Identifier: GPL-2.0-or-later */
/* Vendor OTRA serial framing. Receiving is confined to a private RAM directory.
 * FileEnd verifies the transfer; a separate, fixed helper checks the package.
 * Never interpret host-supplied paths or commands.
 */
#define _GNU_SOURCE
#include <errno.h>
#include <fcntl.h>
#include <poll.h>
#include <signal.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/file.h>
#include <sys/stat.h>
#include <sys/types.h>
#include <sys/wait.h>
#include <termios.h>
#include <unistd.h>

#include "board.h"
#include "fpvos-bytes.h"

#define CHUNK (1024U * 1024)
#define HEADER 36
#ifndef CLEAN_BOOT_MARKER
#define CLEAN_BOOT_MARKER "/run/fpvos-clean-boot"
#endif
static unsigned char payload[CHUNK];
static int port, file = -1, clean, prepared, state;
static uint32_t total, received, last_seq, last_crc, last_len;
static int have_last, install_requested;
static pid_t worker;
static unsigned install_progress;
static volatile sig_atomic_t stopping;
static char status_file[512];
static char expected_md5[33], staging[512], detail[64] = "normal mode";
static const char *helper;
static int io(int fd, void *buf, size_t n, int writing)
{
	unsigned char *p = buf;
	while (n) {
		struct pollfd f = {.fd = fd, .events = writing ? POLLOUT : POLLIN};
		int r = poll(&f, 1, 30000);
		if (r < 0 && errno == EINTR)
			continue;
		if (r <= 0 || !(f.revents & f.events))
			return -1;
		ssize_t k = writing ? write(fd, p, n) : read(fd, p, n);
		if (k < 0 && (errno == EINTR || errno == EAGAIN))
			continue;
		if (k <= 0)
			return -1;
		p += k;
		n -= k;
	}
	return 0;
}
static int reply(const unsigned char *request, const void *body, uint32_t n)
{
	unsigned char h[HEADER];
	memcpy(h, request, HEADER);
	h[6] = 2;
	h[7] = 0;
	fpvos_put_le32(h + 20, n);
	fpvos_put_le32(h + 32, 0);
	fpvos_put_le32(h + 32, ~fpvos_crc32_update(fpvos_crc32_update(~0U, h, HEADER), body, n));
	return io(port, h, sizeof(h), 1) || io(port, (void *)body, n, 1);
}
static int ack(const unsigned char *h, int status, const char *text)
{
	unsigned char body[80] = {0};
	uint32_t cmd = fpvos_get_le32(h + 12);
	int data = (cmd == 0x74 || cmd == 0x75), off = data ? 12 : 0;
	if (data) {
		fpvos_put_le32(body, fpvos_get_le32(h + 20));
		fpvos_put_le32(body + 4, received);
		fpvos_put_le32(body + 8, total);
	}
	fpvos_put_le32(body + off, (uint32_t)status);
	snprintf((char *)body + off + 4, 64, "%s", text);
	return reply(h, body, data ? 80 : 68);
}
static void reset_transfer(void)
{
	if (file >= 0)
		close(file);
	file = -1;
	unlink(staging);
	received = total = 0;
	have_last = 0;
	expected_md5[0] = 0;
}
static int run_helper(const char *operation)
{
	pid_t p = fork();
	int status;
	if (p < 0)
		return -1;
	if (!p) {
		execl(helper, helper, operation, staging, (char *)NULL);
		_exit(127);
	}
	while (waitpid(p, &status, 0) < 0)
		if (errno != EINTR)
			return -1;
	return WIFEXITED(status) ? WEXITSTATUS(status) : -1;
}
static int check_md5(void)
{
	int pipes[2], status;
	char buf[33] = {0};
	if (pipe(pipes))
		return -1;
	pid_t p = fork();
	if (p < 0) {
		close(pipes[0]);
		close(pipes[1]);
		return -1;
	}
	if (!p) {
		dup2(pipes[1], STDOUT_FILENO);
		close(pipes[0]);
		close(pipes[1]);
		execlp("md5sum", "md5sum", staging, (char *)NULL);
		_exit(127);
	}
	close(pipes[1]);
	int result = io(pipes[0], buf, 32, 0);
	char discard[256];
	while (read(pipes[0], discard, sizeof(discard)) > 0) {
	}
	close(pipes[0]);
	while (waitpid(p, &status, 0) < 0)
		if (errno != EINTR)
			return -1;
	if (result || !WIFEXITED(status) || WEXITSTATUS(status)) return -1;
	return strcmp(buf, expected_md5) ? 1 : 0;
}
static void stop_requested(int signum)
{
	(void)signum;
	stopping = 1;
}
static void refresh_worker(void)
{
	if (!worker)
		return;
	FILE *f = fopen(status_file, "r");
	int reported = 3;
	if (f) {
		unsigned percent;
		char message[64];
		if (fscanf(f, "%u %d %63[^\n]", &percent, &reported, message) == 3 &&
		    percent <= 100) {
			install_progress = percent;
			snprintf(detail, sizeof(detail), "%s", message);
		}
		fclose(f);
	}
	int status;
	pid_t done = waitpid(worker, &status, WNOHANG);
	if (done == worker) {
		worker = 0;
		if (WIFEXITED(status) && WEXITSTATUS(status) == 0 && reported == 4) {
			state = 4;
			install_progress = 100;
		} else {
			state = reported == -2 ? -2 : -1;
			if (reported >= 0)
				snprintf(detail, sizeof(detail),
					 "installer failed; see console log");
		}
	}
}
static void restore_status(void)
{
	FILE *f = fopen(status_file, "r");
	if (!f)
		return;
	unsigned percent;
	int saved;
	char message[64];
	if (fscanf(f, "%u %d %63[^\n]", &percent, &saved, message) == 3 &&
	    percent <= 100 && (saved == 4 || saved < 0)) {
		state = saved;
		install_progress = percent;
		snprintf(detail, sizeof(detail), "%s", message);
	}
	fclose(f);
}
static void reboot_after_ack(void)
{
	pid_t child = fork();
	if (!child) {
		setsid();
		sleep(1);
		_exit(run_helper("reboot") ? 1 : 0);
	}
}
static int destination_matches(const unsigned char *name, const char *current, const char *legacy)
{
    return !memcmp(name, current, strlen(current) + 1) ||
           (legacy[0] && !memcmp(name, legacy, strlen(legacy) + 1));
}
static int dispatch(const unsigned char *h, uint32_t n, uint32_t crc)
{
	uint32_t cmd = fpvos_get_le32(h + 12), seq = fpvos_get_le32(h + 24);
	refresh_worker();
	if (cmd == 0x3c && !n) {
		unsigned char b[300] = {0};
		fpvos_put_le32(b, CHUNK);
		snprintf((char *)b + 4, 32, "development");
		snprintf((char *)b + 36, 64, "fpvOS updater");
		snprintf((char *)b + 104, 64, "fpvOS unsigned development updates");
		FILE *identity = fopen("/etc/fpvos-installed-sha256", "r");
		if (identity) {
			char hash[65] = {0};
			if (fread(hash, 1, 64, identity) == 64 &&
			    strspn(hash, "0123456789abcdef") == 64)
				memcpy(b + 104, hash, 64);
			fclose(identity);
		}
		snprintf((char *)b + 168, 32, "%s", fpvos_board.usb_serial);
		snprintf((char *)b + 200, 32, "%s", fpvos_board.hardware);
		snprintf((char *)b + 236, 64, "%s", detail);
		return reply(h, b, sizeof(b));
	}
	if (cmd == 0x76 && !n) {
		unsigned char b[72] = {0};
		fpvos_put_le32(b, (state == 3 || state == 4)
			     ? install_progress
			     : (state == 2 ? 90 : (total ? (uint64_t)received * 80 / total : 0)));
		fpvos_put_le32(b + 4, (uint32_t)state);
		snprintf((char *)b + 8, 64, "%s", detail);
		return reply(h, b, sizeof(b));
	}
	if (worker)
		return ack(h, -1, "Update operation active; query status");
	if (cmd == 3 && n == 32 && !memcmp(payload, "reboot", 7)) {
		for (unsigned i = 7; i < 32; i++)
			if (payload[i])
				return ack(h, -1, "invalid reboot request");
		if (file >= 0 || state == -2)
			return ack(h, -1, "reboot blocked by update state");
		int result = ack(h, 0, "rebooting");
		if (!result)
			reboot_after_ack();
		return result;
	}
	if (state == -2)
		return ack(h, -1, "restoration failed; retain backups and recover via console");
	if (cmd == 3 && n == 32 && !memcmp(payload, "clean", 6)) {
		for (unsigned i = 6; i < 32; i++)
			if (payload[i])
				return ack(h, -1, "invalid clean request");
		if (file >= 0)
			return ack(h, -1, "transfer active");
		int clean_result = run_helper("clean");
		if (clean_result == 10) {
			clean = prepared = 0;
			snprintf(detail, sizeof(detail), "rebooting into clean mode");
			int result = ack(h, 0, detail);
			if (!result)
				reboot_after_ack();
			return result;
		}
		if (clean_result) {
			clean = prepared = 0;
			state = -1;
			snprintf(detail, sizeof(detail), "clean-mode preparation failed");
			return ack(h, -1, detail);
		}
		clean = 1;
		prepared = 0;
		state = 0;
		snprintf(detail, sizeof(detail), "clean RAM mode");
		return ack(h, 0, "OK");
	}
	if (!clean)
		return ack(h, -1, "enter clean mode first");
	if (cmd == 0x72 && !n) {
		reset_transfer();
		unlink(status_file);
		prepared = 1;
		state = 0;
		snprintf(detail, sizeof(detail), "ready to receive");
		return ack(h, 0, "OK");
	}
	if (cmd == 0x73 && n == 328 && prepared && file < 0) {
		uint32_t size = fpvos_get_le32(payload + 64);
		install_requested = destination_matches(payload + 72, "/tmp/pc/fpvos.fwu",
                                                    fpvos_board.legacy_install_destination);
        int verify_only = destination_matches(payload + 72, "/tmp/pc/fpvos.verify",
                                               fpvos_board.legacy_verify_destination);
		uint32_t limit = 0;
		for (unsigned kind = 0; kind < 2; kind++)
			if (fpvos_board.counts[kind] && fpvos_board.bundle_limits[kind] > limit)
				limit = fpvos_board.bundle_limits[kind];
		if (!size || size > limit || fpvos_get_le32(payload + 68) != 1 ||
		    (!install_requested && !verify_only))
			return ack(h, -1, "invalid size or destination");
		for (unsigned i = 0; i < 32; i++)
			if (!((payload[i] >= '0' && payload[i] <= '9') ||
			      (payload[i] >= 'a' && payload[i] <= 'f')))
				return ack(h, -1, "invalid MD5");
		for (unsigned i = 32; i < 64; i++)
			if (payload[i])
				return ack(h, -1, "invalid MD5 padding");
		reset_transfer();
		file = open(staging, O_WRONLY | O_CREAT | O_EXCL | O_NOFOLLOW | O_CLOEXEC, 0600);
		if (file < 0)
			return ack(h, -1, "cannot stage file");
		total = size;
		memcpy(expected_md5, payload, 32);
		expected_md5[32] = 0;
		state = 1;
		snprintf(detail, sizeof(detail), "receiving");
		return ack(h, 0, "OK");
	}
	if (cmd == 0x74 && n && file >= 0) {
		if (have_last && seq == last_seq) {
			if (crc != last_crc || n != last_len)
				return ack(h, -1, "changed retransmission");
			return ack(h, 0, "OK");
		}
		if (have_last && (int32_t)(seq - last_seq) <= 0)
			return ack(h, -1, "out-of-order data");
		if (n > total - received)
			return ack(h, -1, "file overrun");
		if (io(file, payload, n, 1)) {
			reset_transfer();
			state = -1;
			return ack(h, -1, "write failed");
		}
		received += n;
		have_last = 1;
		last_seq = seq;
		last_crc = crc;
		last_len = n;
		return ack(h, 0, "OK");
	}
	if (cmd == 0x75 && !n && file >= 0) {
		if (received != total)
			return ack(h, -1, "incomplete file");
		int error = fsync(file);
		if (close(file))
			error = 1;
		file = -1;
		prepared = 0;
		int md5_result = error ? 0 : check_md5();
		if (error || md5_result) {
			reset_transfer();
			state = -1;
			snprintf(detail, sizeof(detail), "%s", error ? "staging sync/close failed"
				 : md5_result < 0 ? "MD5 helper failed" : "MD5 mismatch");
			return ack(h, -1, detail);
		}
		if (!install_requested && run_helper("verify")) {
			reset_transfer();
			state = -1;
			snprintf(detail, sizeof(detail), "package validation failed");
			return ack(h, -1, detail);
		}
		if (install_requested) {
			worker = fork();
			if (worker < 0) {
				worker = 0;
				return ack(h, -1, "cannot start installer");
			}
			if (!worker) {
				signal(SIGHUP, SIG_IGN);
				signal(SIGINT, SIG_IGN);
				signal(SIGTERM, SIG_IGN);
				signal(SIGPIPE, SIG_IGN);
				_exit(run_helper("install") ? 1 : 0);
			}
			state = 3;
			install_progress = 0;
			snprintf(detail, sizeof(detail), "installer starting");
		} else {
			state = 2;
			snprintf(detail, sizeof(detail), "verified only; not installed");
		}
		return ack(h, 0, "transfer verified; query status");
	}
	return ack(h, -1, "invalid command or state");
}
int main(int argc, char **argv)
{
	if (argc != 4) {
		fprintf(stderr, "usage: %s TTY PRIVATE_STAGING_DIRECTORY HELPER\n", argv[0]);
		return 2;
	}
	signal(SIGTERM, stop_requested);
	signal(SIGINT, stop_requested);
	signal(SIGHUP, SIG_IGN);
	umask(077);
	helper = argv[3];
	struct stat st;
	if (lstat(argv[2], &st) || !S_ISDIR(st.st_mode) || st.st_uid != geteuid() ||
	    (st.st_mode & 077)) {
		fprintf(stderr, "staging directory must be private and owned by updater\n");
		return 2;
	}
	if (snprintf(staging, sizeof(staging), "%s/package.fwu", argv[2]) >= (int)sizeof(staging))
		return 2;
	if (snprintf(status_file, sizeof(status_file), "%s/status", argv[2]) >=
	    (int)sizeof(status_file))
		return 2;
	char lockname[512];
	if (snprintf(lockname, sizeof(lockname), "%s/lock", argv[2]) >= (int)sizeof(lockname))
		return 2;
	int lock = open(lockname, O_RDWR | O_CREAT | O_NOFOLLOW | O_CLOEXEC, 0600);
	if (lock < 0 || flock(lock, LOCK_EX | LOCK_NB))
		return 2;
	port = open(argv[1], O_RDWR | O_NOCTTY | O_CLOEXEC);
	if (port < 0) {
		perror("serial");
		return 1;
	}
	struct termios t;
	if (tcgetattr(port, &t))
		return 1;
	cfmakeraw(&t);
	t.c_cflag |= CLOCAL | CREAD;
	t.c_cflag &= ~CRTSCTS;
	if (tcsetattr(port, TCSANOW, &t))
		return 1;
	/* Preserve failed transaction evidence across USB reconnects. */
	restore_status();
	if (state >= 0)
		reset_transfer();
	if (state >= 0 && access(CLEAN_BOOT_MARKER, F_OK) == 0) {
		int clean_result = run_helper("clean");
		if (clean_result) {
			/* Keep info/status and a later clean retry available. Uploads
			 * remain blocked until readiness actually succeeds. */
			clean = prepared = 0;
			state = -1;
			snprintf(detail, sizeof(detail),
				 "clean-mode startup failed (helper status %d)", clean_result);
			fprintf(stderr, "%s\n", detail);
		} else {
			clean = 1;
			snprintf(detail, sizeof(detail), "clean RAM mode");
		}
	}
	for (;;) {
		refresh_worker();
		if (stopping && !worker)
			break;
		unsigned char h[HEADER];
		struct pollfd pending = {.fd = port, .events = POLLIN};
		int ready = poll(&pending, 1, 500);
		if (!ready)
			continue;
		if (ready < 0 && errno == EINTR)
			continue;
		if (ready <= 0 || !(pending.revents & POLLIN))
			break;
		if (io(port, h, HEADER, 0))
			break;
		uint32_t n = fpvos_get_le32(h + 20), crc = fpvos_get_le32(h + 32);
		if (memcmp(h, "OTRA", 4) || h[4] != 0xdc || h[5] != 0x0c || h[6] != 1 || h[7] ||
		    h[16] != 2 || h[17] || n > CHUNK)
			break;
		if (io(port, payload, n, 0))
			break;
		fpvos_put_le32(h + 32, 0);
		if (~fpvos_crc32_update(fpvos_crc32_update(~0U, h, HEADER), payload, n) != crc) {
			if (ack(h, -1, "CRC mismatch"))
				break;
			continue;
		}
		/* Retry count is excluded from data identity, so a retry can change it. */
		if (dispatch(h, n, ~fpvos_crc32_update(~0U, payload, n)))
			break;
	}
	/* Disconnecting the cable must not interrupt a flash transaction. */
	while (worker) {
		refresh_worker();
		if (worker)
			sleep(1);
	}
	if (state >= 0)
		reset_transfer();
	close(port);
	close(lock);
	return 0;
}
