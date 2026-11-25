#pragma once
#include <stdint.h>

enum { NVN_FRAME_HISTORY_CAPACITY = 8 };

// nn::vi::FrameInfo, newest entry first. Timestamps use the guest 19.2 MHz clock.
typedef struct {
    uint64_t state, number, submitted_tick, presented_tick, display_tick;
} NvnFrameInfo;

uint64_t vkp_begin_frame(const void *native);
int vkp_latest_frame(const void *native, uint64_t *number);
int vkp_frame_history(const void *native, NvnFrameInfo *out, int capacity);

int gfx_frame_history_available(void);
uint64_t gfx_nvn_begin_frame(const void *native);
int gfx_nvn_latest_frame(const void *native, uint64_t *number);
int gfx_nvn_frame_history(const void *native, NvnFrameInfo *out, int capacity);
