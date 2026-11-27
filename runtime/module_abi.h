/* Orbitals PC Recomp, based on SwitchRecomp by MZ Labs. AGPL-3.0 with NOTICE.txt terms. */
#ifndef SWR_MODULE_ABI_H
#define SWR_MODULE_ABI_H
#include "cpu.h"

/* Bump when callback or dispatch semantics change without a declaration change.
   The build also hashes this header and the generator that emits the tables. */
#define SWR_MODULE_ABI 2
#define SWR_ORBITALS_PARSE_RES 0x35d1740
#define SWR_ORBITALS_PARSE_RES_INSN1 0xd503237f
#define SWR_ORBITALS_PARSE_RES_INSN2 0xd10243ff

typedef struct SwrModInfo {
  const char* name;
  u64 base, size;
  u8 build_id[32];
  u32 text_off, text_size, ro_off, ro_size, data_off, data_size, bss_size, is_nro;
} SwrModInfo;

typedef struct SwrModule {
  u32 abi; u32 nmods; const SwrModInfo* mods;
  u32 nentries; const u64* entry_addr; const GuestFn* entry_fn;
  GuestFn interp;
  u64 code_lo, code_hi;
  const char* title; u64 title_id;
  u32 main_stack, main_prio, main_core;
  void (*init)(const RtAPI* rt);
  u64 (*step)(CPU* c, u32 w, u64 pc);
} SwrModule;

#endif
