/* SPDX-License-Identifier: GPL-3.0-only */
#ifndef FPVOS_CAMERA_CONTROL_H
#define FPVOS_CAMERA_CONTROL_H
#include <errno.h>
#include <limits.h>
#include <math.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/socket.h>

/* Private inherited SOCK_SEQPACKET channel, one outstanding request. A reply
 * confirms the daemon has applied the request to its live control loop.
 * SET value [red blue]; EV -10..10, WB 0=auto/-1=lock. Optional Q8 gains
 * restore a saved lock; otherwise lock captures the currently applied gains.
 */
struct camera_request { int value, red, blue, gains; };
static inline int camera_parse(const char *buf, struct camera_request *r)
{
    long values[3]; int n=0; char *end;
    if (strncmp(buf,"SET ",4)) return -1;
    buf+=4;
    while (*buf) {
        if (n==3) return -1;
        errno=0; values[n]=strtol(buf,&end,10);
        if (errno || end==buf || values[n]<INT_MIN || values[n]>INT_MAX) return -1;
        ++n; buf=end;
        if (*buf && *buf!=' ') return -1;
        while (*buf==' ') ++buf;
    }
    if (n!=1 && n!=3) return -1;
    *r=(struct camera_request){.value=(int)values[0],.gains=n==3};
    if (n==3) { r->red=(int)values[1]; r->blue=(int)values[2]; }
    return 0;
}
static inline void camera_reply(int fd, int ok, int value, unsigned red, unsigned blue)
{
    char buf[64]; int n=snprintf(buf,sizeof(buf),"%s %d %u %u",ok?"OK":"ERR",value,red,blue);
    if (fd>=0) (void)send(fd,buf,n,MSG_NOSIGNAL);
}
/* 1 request, 0 none/malformed (already rejected), -1 disconnected/error. */
static inline int camera_receive(int fd, struct camera_request *r)
{
    char buf[64]; ssize_t n;
    if (fd<0) return 0;
    n=recv(fd,buf,sizeof(buf)-1,MSG_DONTWAIT|MSG_TRUNC);
    if (n<0) return errno==EAGAIN || errno==EWOULDBLOCK || errno==EINTR ? 0 : -1;
    if (!n) return -1;
    if (n>=(ssize_t)sizeof(buf)-1 || memchr(buf,0,n)) {
        camera_reply(fd,0,0,0,0); return 0;
    }
    buf[n]=0;
    if (camera_parse(buf,r)) { camera_reply(fd,0,0,0,0); return 0; }
    return 1;
}
static inline int camera_ev_valid(const struct camera_request *r)
{ return !r->gains && r->value>=-10 && r->value<=10; }
static inline int camera_wb_valid(const struct camera_request *r)
{
    return (r->value==0 && !r->gains) || (r->value==-1 && (!r->gains ||
        (r->red>=128 && r->red<=1024 && r->blue>=128 && r->blue<=1024)));
}
static inline float camera_ev_luma(float luma, int ev_x10)
{ return luma / exp2f(ev_x10/10.0f); }
#endif
