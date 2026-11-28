/* SPDX-License-Identifier: GPL-2.0-or-later */
#ifndef FPVOS_UPDATE_BOARD_H
#define FPVOS_UPDATE_BOARD_H
#include <stddef.h>
#include <stdint.h>

/* FPVOSUP1 has up to three ordered components. Kind 0 is a system update;
 * kind 1 is vendor restoration. A zero count disables a kind for this board. */
struct fpvos_update_board {
    uint32_t board_id;
    const char *hardware, *usb_serial;
    const char *legacy_install_destination, *legacy_verify_destination;
    /* where SET_LOCATION's fields are kept (a goggle's); "": not kept */
    const char *location_file;
    /* 1: the battery clock is the board helper's ("clock": write it from the
     * system clock), not /dev/rtc0 - the VRX Pro's pcf8563, kept on Beijing
     * time as stock reads it, behind an RTC that loses the time */
    int clock_helper;
    const char *names[3];
    uint32_t limits[3], counts[2], bundle_limits[2];
};
extern const struct fpvos_update_board fpvos_board;
/* Linked from the selected backend, after generic size/manifest checks. */
int fpvos_board_image_valid(unsigned index, const unsigned char *data, size_t size, unsigned kind);
#endif
