// SPDX-License-Identifier: MIT
/* Supervise one air application and its camera helpers. All state/logs are RAM.
 * A process group contains each generation; subreaping collects orphaned AE/AWB
 * workers after a crash before the next generation can acquire the camera.
 */
#define _GNU_SOURCE
#include <errno.h>
#include <fcntl.h>
#include <poll.h>
#include <signal.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/file.h>
#include <sys/prctl.h>
#include <sys/stat.h>
#include <sys/types.h>
#include <sys/wait.h>
#include <time.h>
#include <unistd.h>

/* Compile-time overrides let host tests exercise the same policy quickly. */
#ifndef RETRY_MS
#define RETRY_MS 2000
#endif
#ifndef STABLE_MS
#define STABLE_MS 60000
#endif
#ifndef STOP_MS
#define STOP_MS 5000
#endif
#ifndef LOG_BYTES
#define LOG_BYTES (1024 * 1024)
#endif
#define ATTEMPTS 5

static volatile sig_atomic_t stopping;
static int logfile = -1;
static size_t logsize;

static long long now_ms(void)
{
    struct timespec ts;
    if (clock_gettime(CLOCK_MONOTONIC, &ts)) abort();
    return (long long)ts.tv_sec * 1000 + ts.tv_nsec / 1000000;
}

static void on_stop(int sig) { (void)sig; stopping = 1; }

static int write_all(int fd, const char *s, size_t n)
{
    while (n) {
        ssize_t w = write(fd, s, n);
        if (w < 0 && errno == EINTR) continue;
        if (w <= 0) return -1;
        s += w; n -= (size_t)w;
    }
    return 0;
}

static void log_write(const char *s, size_t n)
{
    while (n) {
        if (logfile < 0 || logsize >= LOG_BYTES) {
            if (logfile >= 0) {
                close(logfile);
                if (rename("current.log", "previous.log")) { stopping = 1; return; }
            }
            logfile = open("current.log", O_CREAT | O_TRUNC | O_WRONLY | O_CLOEXEC, 0600);
            logsize = 0;
            if (logfile < 0) { stopping = 1; return; }
        }
        size_t count = n < LOG_BYTES - logsize ? n : LOG_BYTES - logsize;
        if (write_all(logfile, s, count)) { stopping = 1; return; }
        s += count; n -= count; logsize += count;
    }
}

static void status(const char *state, pid_t child, unsigned failures)
{
    char line[128];
    int n = snprintf(line, sizeof(line), "%s pid=%ld failures=%u\n", state, (long)child, failures);
    int fd = open("status.new", O_WRONLY | O_CREAT | O_TRUNC | O_CLOEXEC, 0600);
    if (fd < 0 || write_all(fd, line, (size_t)n) || rename("status.new", "status")) stopping = 1;
    if (fd >= 0) close(fd);
    log_write(line, (size_t)n);
}

/* Bound each drain so a noisy child cannot starve stop/reap handling. */
static void pump(int fd, int timeout)
{
    struct pollfd p = { .fd = fd, .events = POLLIN };
    if (poll(&p, 1, timeout) <= 0) return;
    for (unsigned i = 0; i < 16; i++) {
        char buf[4096];
        ssize_t n = read(fd, buf, sizeof(buf));
        if (n <= 0) break;
        log_write(buf, (size_t)n);
    }
    /* EOF can precede exit or leave an uninterruptible child; avoid busy loops. */
    if (p.revents & POLLHUP) poll(NULL, 0, 20);
}

int main(int argc, char **argv)
{
    if (argc < 3) { fprintf(stderr, "Usage: %s STATE_DIR COMMAND [ARGS]\n", argv[0]); return 2; }
    umask(0077);
    if (chdir(argv[1])) { perror("state directory"); return 1; }
    int lock = open("lock", O_CREAT | O_RDWR | O_CLOEXEC, 0600);
    if (lock < 0 || flock(lock, LOCK_EX | LOCK_NB)) return 1;
    if (prctl(PR_SET_CHILD_SUBREAPER, 1)) { perror("subreaper"); return 1; }
    struct sigaction sa = { .sa_handler = on_stop };
    sigemptyset(&sa.sa_mask);
    sigaction(SIGTERM, &sa, NULL);
    sigaction(SIGINT, &sa, NULL);
    int fd = open("pid", O_WRONLY | O_CREAT | O_TRUNC | O_CLOEXEC, 0600);
    if (fd < 0) return 1;
    char pid[32];
    int n = snprintf(pid, sizeof(pid), "%ld\n", (long)getpid());
    if (write_all(fd, pid, (size_t)n)) { close(fd); unlink("pid"); return 1; }
    close(fd);
    /* Retain the final log from the preceding manual start. */
    if (rename("current.log", "previous.log") && errno != ENOENT) stopping = 1;

    unsigned failures = 0;
    int result = 0;
    while (!stopping) {
        int pipefd[2];
        if (pipe2(pipefd, O_CLOEXEC)) { result = 1; break; }
        long long started = now_ms();
        pid_t child = fork();
        if (!child) {
            close(pipefd[0]);
            if (setpgid(0, 0)) _exit(126);
            signal(SIGINT, SIG_DFL); signal(SIGTERM, SIG_DFL);
            if (dup2(pipefd[1], STDOUT_FILENO) < 0 || dup2(pipefd[1], STDERR_FILENO) < 0) _exit(126);
            close(pipefd[1]);
            execvp(argv[2], argv + 2);
            perror("exec air launcher");
            _exit(127);
        }
        close(pipefd[1]);
        if (child < 0) { close(pipefd[0]); result = 1; break; }
        /* Both sides establish the group, including a stop immediately after fork. */
        setpgid(child, child);
        fcntl(pipefd[0], F_SETFL, O_NONBLOCK);
        status("running", child, failures);
        int leader_done = 0, exit_status = 0, phase = 0;
        long long deadline = 0, ended = 0;
        for (;;) {
            pump(pipefd[0], 50);
            pid_t reaped;
            int ws;
            while ((reaped = waitpid(-1, &ws, WNOHANG)) > 0) {
                if (reaped == child) { leader_done = 1; exit_status = ws; ended = now_ms(); }
            }
            if (!phase && (stopping || leader_done)) {
                /* Give the launcher/app a graceful shutdown first; only signal
                 * orphan helpers after its exit (or the shutdown timeout). */
                if (!leader_done) kill(child, SIGTERM);
                else kill(-child, SIGTERM);
                phase = 1; deadline = now_ms() + STOP_MS;
                status("stopping", child, failures);
            }
            if (leader_done && phase == 1) kill(-child, SIGTERM);
            if (leader_done && kill(-child, 0) < 0 && errno == ESRCH) break;
            if (phase && now_ms() >= deadline) {
                kill(-child, SIGKILL);
                if (phase == 2) {
                    /* Never start a competing generation if kernel teardown
                     * is stuck. Leave SSH and the rest of init running. */
                    status("failed-cleanup", child, failures);
                    result = 1;
                    goto out;
                }
                phase = 2; deadline = now_ms() + STOP_MS;
            }
        }
        pump(pipefd[0], 0);
        close(pipefd[0]);
        char message[96];
        n = snprintf(message, sizeof(message), "exit code=%d signal=%d\n",
                     WIFEXITED(exit_status) ? WEXITSTATUS(exit_status) : -1,
                     WIFSIGNALED(exit_status) ? WTERMSIG(exit_status) : 0);
        log_write(message, (size_t)n);
        if (stopping) break;
        failures = ended - started >= STABLE_MS ? 0 : failures + 1;
        if (failures >= ATTEMPTS) { status("failed", 0, failures); result = 1; goto out; }
        status("backoff", 0, failures);
        long long retry = now_ms() + RETRY_MS;
        while (!stopping && now_ms() < retry) poll(NULL, 0, 50);
    }
    status(result ? "failed" : "stopped", 0, failures);
out:
    unlink("pid");
    if (logfile >= 0) close(logfile);
    close(lock);
    return result;
}
