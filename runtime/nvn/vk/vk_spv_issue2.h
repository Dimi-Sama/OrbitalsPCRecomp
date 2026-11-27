#pragma once
#include <stddef.h>
#include <stdint.h>

// Return a replacement module owned by the caller, or NULL. Return counts of zero
// for unchanged modules and leave the input untouched.
uint32_t *vkspv_no_contraction(const uint32_t *words, size_t n, size_t *out_n, unsigned *count);
uint32_t *vkspv_warp_sync(const uint32_t *words, size_t n, size_t *out_n, unsigned *control, unsigned *memory);
