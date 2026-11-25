// SwitchRecomp - Copyright 2026 MZ Labs
// Licensed under the GNU Affero General Public License v3.0, see LICENSE.txt and NOTICE.txt.
// In place of ooz's stdafx.h (Windows and MSVC only) for the decoder part of kraken.cpp that nxs_kraken.py compiles with GCC or Clang on
// Windows and Linux: its integer types and the MSVC intrinsics it calls (32-bit bit scans, byte swaps, rotation), with SSE from the
// standard x86 headers.
#pragma once
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <stdint.h>
#include <assert.h>
#include <emmintrin.h>
#include <smmintrin.h>

typedef unsigned char byte;
typedef unsigned char uint8;
typedef unsigned int uint32;
typedef unsigned long long uint64;
typedef signed long long int64;
typedef signed int int32;
typedef unsigned short uint16;
typedef signed short int16;
typedef unsigned int uint;

#ifndef __forceinline
#define __forceinline inline __attribute__((always_inline))
#endif

static inline unsigned char _BitScanReverse(unsigned long *index, unsigned long mask) {   // MSVC: on the low 32 bits
    uint32_t m = (uint32_t)mask;
    if (!m) return 0;
    *index = 31u - (unsigned)__builtin_clz(m);
    return 1;
}
static inline unsigned char _BitScanForward(unsigned long *index, unsigned long mask) {
    uint32_t m = (uint32_t)mask;
    if (!m) return 0;
    *index = (unsigned)__builtin_ctz(m);
    return 1;
}
#define _byteswap_ushort(x) __builtin_bswap16((uint16_t)(x))
#define _byteswap_ulong(x) __builtin_bswap32((uint32_t)(x))
#define _byteswap_uint64(x) __builtin_bswap64((uint64_t)(x))
#if !defined(_WIN32) || !defined(_rotl)
static inline uint32_t ooz_rotl(uint32_t x, int s) { s &= 31; return s ? (x << s) | (x >> (32 - s)) : x; }
#undef _rotl
#define _rotl(x, s) ooz_rotl((uint32_t)(x), (int)(s))
#endif
