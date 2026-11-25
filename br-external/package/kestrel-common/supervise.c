// SPDX-License-Identifier: MIT
/* Supervise one application and its helpers. All state/logs are RAM.
 * A process group contains each generation; subreaping collects orphaned AE/AWB
 * workers after a crash before the next generation can acquire the camera.
 * Nothing restarts the supervisor itself, so once it runs only a stop ends it:
 * a full /run or a failed fork costs logs or a retry, never the application.
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
#ifndef MAX_RETRY_MS
#define MAX_RETRY_MS 10000
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
#ifndef LOG_RETRY_MS
#define LOG_RETRY_MS 5000
#endif

static volatile sig_atomic_t stopping;
static int logfile = -1;
static size_t logsize;
/* After a log error, output is dropped (and counted) until this time. */
static long long log_retry;
static unsigned long long log_dropped;

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

static void log_lost(void)
{
    if (logfile >= 0) close(logfile);
    logfile = -1;
    log_retry = now_ms() + LOG_RETRY_MS;
}

/* Logs are best effort: an error (ENOSPC, a read-only or missing directory)
 * drops output for LOG_RETRY_MS, then the next write starts a new file. */
static void log_write(const char *s, size_t n)
{
    while (n) {
        if (logfile < 0 || logsize >= LOG_BYTES) {
            if (logfile < 0 && now_ms() < log_retry) { log_dropped += n; return; }
            if (logfile >= 0) close(logfile);
            logfile = -1;
            /* Keep the full (or failed) file, or at the first write the
             * preceding start's final log. If the rename fails, the
             * truncating open still bounds the log. */
            (void)rename("current.log", "previous.log");
            logfile = open("current.log", O_CREAT | O_TRUNC | O_WRONLY | O_CLOEXEC, 0600);
            logsize = 0;
            if (logfile < 0) { log_lost(); log_dropped += n; return; }
            if (log_dropped) {
                char note[64];
                int m = snprintf(note, sizeof(note), "supervise: %llu log bytes dropped\n", log_dropped);
                if (m > 0 && (size_t)m < LOG_BYTES && !write_all(logfile, note, (size_t)m)) {
                    logsize = (size_t)m;
                    log_dropped = 0;
                }
            }
        }
        size_t count = n < LOG_BYTES - logsize ? n : LOG_BYTES - logsize;
        if (write_all(logfile, s, count)) { log_lost(); log_dropped += n; return; }
        s += count; n -= count; logsize += count;
    }
}

/* Best effort as well: a stale status file is better than a stopped unit. */
static void status(const char *state, pid_t child, unsigned failures)
{
    char line[128];
    int n = snprintf(line, sizeof(line), "%s pid=%ld failures=%u\n", state, (long)child, failures);
    int fd = open("status.new", O_WRONLY | O_CREAT | O_TRUNC | O_CLOEXEC, 0600);
    if (fd >= 0) {
        int failed = write_all(fd, line, (size_t)n);
        close(fd);
        if (failed || rename("status.new", "status")) unlink("status.new");
    }
    log_write(line, (size_t)n);
}

static void log_error(const char *what, int error)
{
    char line[128];
    int n = snprintf(line, sizeof(line), "supervise: %s: %s\n", what, strerror(error));
    if (n > 0) log_write(line, (size_t)n < sizeof(line) ? (size_t)n : sizeof(line) - 1);
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

/* One generation: start the launcher in its own group, relay its output and
 * reap the whole group. Returns -1 only when a stop could not clean up. A
 * pipe or fork failure (fds or memory short, as right after an OOM kill)
 * starts nothing and leaves *ended as it was: the caller counts it as a short
 * run and retries after the usual backoff. */
static int generation(char **argv, unsigned failures, long long *ended)
{
    int pipefd[2];
    if (pipe2(pipefd, O_CLOEXEC)) { log_error("pipe", errno); return 0; }
    /* Blocked across fork(): a stop in that window stays pending until the
     * child has the default handlers back, so it ends the child instead of
     * setting the copy of our flag and letting the exec go ahead. */
    sigset_t stops, previous;
    sigemptyset(&stops);
    sigaddset(&stops, SIGINT);
    sigaddset(&stops, SIGTERM);
    sigprocmask(SIG_BLOCK, &stops, &previous);
    pid_t child = fork();
    int fork_error = errno;
    if (!child) {
        close(pipefd[0]);
        if (setpgid(0, 0)) _exit(126);
        signal(SIGINT, SIG_DFL); signal(SIGTERM, SIG_DFL);
        sigprocmask(SIG_SETMASK, &previous, NULL);
        if (dup2(pipefd[1], STDOUT_FILENO) < 0 || dup2(pipefd[1], STDERR_FILENO) < 0) _exit(126);
        close(pipefd[1]);
        execvp(argv[2], argv + 2);
        perror("exec application launcher");
        _exit(127);
    }
    sigprocmask(SIG_SETMASK, &previous, NULL);
    close(pipefd[1]);
    if (child < 0) { close(pipefd[0]); log_error("fork", fork_error); return 0; }
    /* Both sides establish the group, including a stop immediately after fork. */
    setpgid(child, child);
    fcntl(pipefd[0], F_SETFL, O_NONBLOCK);
    status("running", child, failures);
    int leader_done = 0, exit_status = 0, phase = 0;
    long long deadline = 0;
    for (;;) {
        pump(pipefd[0], 50);
        pid_t reaped;
        int ws;
        while ((reaped = waitpid(-1, &ws, WNOHANG)) > 0) {
            if (reaped == child) { leader_done = 1; exit_status = ws; *ended = now_ms(); }
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
            /* Never start a competing generation while kernel teardown is
             * stuck. A stop gives up (SSH and the rest of init keep
             * running); otherwise keep killing and restart once it's gone. */
            if (phase == 2 && stopping) {
                status("failed-cleanup", child, failures);
                return -1;
            }
            if (phase == 2) status("stuck-cleanup", child, failures);
            phase = 2; deadline = now_ms() + STOP_MS;
        }
    }
    pump(pipefd[0], 0);
    close(pipefd[0]);
    char message[96];
    int n = snprintf(message, sizeof(message), "exit code=%d signal=%d\n",
                     WIFEXITED(exit_status) ? WEXITSTATUS(exit_status) : -1,
                     WIFSIGNALED(exit_status) ? WTERMSIG(exit_status) : 0);
    log_write(message, (size_t)n);
    return 0;
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

    unsigned failures = 0;
    int result = 0;
    while (!stopping) {
        long long started = now_ms(), ended = started;
        if (generation(argv, failures, &ended)) { result = 1; goto out; }
        if (stopping) break;
        failures = ended - started >= STABLE_MS ? 0 : failures + 1;
        /* Never give up: a flight unit must get its video back. Each short run
         * doubles the wait from RETRY_MS, up to MAX_RETRY_MS. */
        long long delay = RETRY_MS;
        for (unsigned i = 1; i < failures && delay < MAX_RETRY_MS; i++) delay *= 2;
        if (delay > MAX_RETRY_MS) delay = MAX_RETRY_MS;
        status("backoff", 0, failures);
        long long retry = now_ms() + delay;
        while (!stopping && now_ms() < retry) poll(NULL, 0, 50);
    }
    status("stopped", 0, failures);
out:
    unlink("pid");
    if (logfile >= 0) close(logfile);
    close(lock);
    return result;
}
