// SwitchRecomp - Copyright 2026 MZ Labs
// Licensed under the GNU Affero General Public License v3.0, see LICENSE.txt and NOTICE.txt.
// The shader decoder nxs_kraken.py builds on the user's PC: OodleLZ_Decompress's calling convention over Kraken_Decompress of ooz's
// kraken.cpp (Powzix, GPL-3.0-or-later; downloaded at a pinned commit and checked by its SHA-256, never shipped by this project), so
// nxs_ue_nv2.py loads it like an Oodle library. Only Kraken-family streams (Kraken, Mermaid, Selkie, Leviathan) decode: LZNA and BitKnit
// are left out, their ooz sources carry no license notice. Orbitals' shader archives decode in full without them.
#include <stddef.h>
#include <stdint.h>
typedef unsigned char byte;
int Kraken_Decompress(const byte *src, size_t src_len, byte *dst, size_t dst_len);
struct LznaState; struct BitknitState;
int LZNA_DecodeQuantum(byte *, byte *, byte *, const byte *, const byte *, struct LznaState *) { return -1; }
void LZNA_InitLookup(struct LznaState *) {}
void BitknitState_Init(struct BitknitState *) {}
size_t Bitknit_Decode(const byte *, const byte *, byte *, byte *, byte *, struct BitknitState *) { return 0; }
#if defined(_WIN32)
#define EXPORT extern "C" __declspec(dllexport)
#else
#define EXPORT extern "C" __attribute__((visibility("default")))
#endif
EXPORT ptrdiff_t OodleLZ_Decompress(const void *src, ptrdiff_t src_len, void *dst, ptrdiff_t dst_len, int fuzz, int crc, int verbosity,
                                    void *dec_base, ptrdiff_t dec_size, void *cb, void *cb_user, void *scratch, ptrdiff_t scratch_size, int phase) {
    (void)fuzz; (void)crc; (void)verbosity; (void)dec_base; (void)dec_size; (void)cb; (void)cb_user; (void)scratch; (void)scratch_size; (void)phase;
    if (src_len <= 0 || dst_len <= 0) return 0;
    int n = Kraken_Decompress((const byte *)src, (size_t)src_len, (byte *)dst, (size_t)dst_len);
    return n < 0 ? 0 : n;
}
