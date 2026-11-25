# SwitchRecomp - Copyright 2026 MZ Labs
# Licensed under the GNU Affero General Public License v3.0, see LICENSE.txt and NOTICE.txt.
# Forks and derived works have to keep the credit to SwitchRecomp by MZ Labs and the startup screen.
"""The inline AdvSIMD templates of a64.fast_simd / fast_ld1 against swr_simd (cpu_helpers.c, itself checked against
unicorn): random encodings of each inlined family, random registers (special floats included) and memory; both must
leave the same vector registers, X registers and memory.

  python tests/a64/simd_inline_diff.py ROOT OUTDIR [seed]   -> OUTDIR/diff.c
  gcc -O2 -w -I ROOT/runtime OUTDIR/diff.c ROOT/runtime/cpu_helpers.c -lm -o diff && ./diff"""
import sys, random, importlib.util
root, out = sys.argv[1], sys.argv[2]
random.seed(int(sys.argv[3]) if len(sys.argv) > 3 else 1)
sp = importlib.util.spec_from_file_location('a64', root + '/a64.py'); a = importlib.util.module_from_spec(sp); sp.loader.exec_module(a)


def r5(): return random.randrange(32)


def fam_perm():
    Q = random.randrange(2); size = random.randrange(4); op = random.choice([1, 2, 3, 5, 6, 7])
    return (Q << 30) | 0x0E000800 | (size << 22) | (r5() << 16) | (op << 12) | (r5() << 5) | r5()


def fam_ext():
    Q = random.randrange(2); imm4 = random.randrange(16 if Q else 8)
    return (Q << 30) | 0x2E000000 | (r5() << 16) | (imm4 << 11) | (r5() << 5) | r5()


def fam_2misc():
    Q = random.randrange(2); k = random.randrange(3)
    if k == 0: U = random.randrange(2); size = random.randrange(2, 4); op = 0x0F
    elif k == 1: U = 1; size = 0; op = 0x05
    else: U = 0; size = random.randrange(3); op = 0
    return (Q << 30) | (U << 29) | 0x0E200800 | (size << 22) | (op << 12) | (r5() << 5) | r5()


def fam_3same():
    Q = random.randrange(2)
    if random.randrange(2): U, size, op = 0, random.randrange(3), 0x13
    else:
        U, hi = random.choice([(0, 0), (1, 0), (1, 1)]); size = (hi << 1) | random.randrange(2); op = 0x1C
    return (Q << 30) | (U << 29) | 0x0E200400 | (size << 22) | (r5() << 16) | (op << 11) | (r5() << 5) | r5()


def fam_ld1():
    Q = random.randrange(2); L = random.randrange(2); post = random.randrange(2); op = random.choice([7, 10, 6, 2])
    rn = random.randrange(31); rm = random.choice([31, random.randrange(31)]) if post else 0
    if post and rm == rn: rm = 31
    return (Q << 30) | 0x0C000000 | (post << 23) | (L << 22) | (rm << 16) | (op << 12) | (random.randrange(4) << 10) | (rn << 5) | r5()


def fam_shimm():
    Q = random.randrange(2); U = random.randrange(2)
    op = random.choice([0x00, 0x02, 0x04, 0x06, 0x0A, 0x14, 0x10, 0x11, 0x12, 0x13])
    size = random.randrange(3 if op >= 0x10 else 4)
    immh = 1 << size
    imm = random.randrange(8 << size) if op in (0x0A, 0x14) else random.randrange(1, (8 << size) + 1)
    if op in (0x0A, 0x14): v = (8 << size) + imm
    else: v = 2 * (8 << size) - imm
    immh, immb = v >> 3, v & 7
    return (Q << 30) | (U << 29) | 0x0F000400 | (immh << 19) | (immb << 16) | (op << 11) | (r5() << 5) | r5()


def fam_3diff():
    Q = random.randrange(2); U = random.randrange(2); size = random.randrange(3); op = random.choice([0, 1, 2, 3, 5, 7, 8, 10, 12])
    return (Q << 30) | (U << 29) | 0x0E200000 | (size << 22) | (r5() << 16) | (op << 12) | (r5() << 5) | r5()


def fam_narrow():
    Q = random.randrange(2); U = random.randrange(2); size = random.randrange(3); op = random.choice([0x12, 0x14])
    return (Q << 30) | (U << 29) | 0x0E200800 | (size << 22) | (op << 12) | (r5() << 5) | r5()


def fam_3int():
    Q = random.randrange(2); U = random.randrange(2); op = random.choice([0x00, 0x02, 0x06, 0x07, 0x0C, 0x0D, 0x0E, 0x0F, 0x11])
    size = random.randrange(4 if op in (0x06, 0x07, 0x11) else 3)
    if size == 3: Q = 1
    return (Q << 30) | (U << 29) | 0x0E200400 | (size << 22) | (r5() << 16) | (op << 11) | (r5() << 5) | r5()


def fam_f3same():
    # floating point three same: FMAXNM/FMINNM, FMLA/FMLS, FADD/FSUB, FADDP/FABD, FMULX/FMUL, FCMEQ/FCMGE/FCMGT, FACGE/FACGT,
    # FMAX/FMIN/FMAXP, FRECPS/FRSQRTS/FDIV (single and double lanes)
    Q = random.randrange(2); U = random.randrange(2); sz = random.randrange(2); a_ = random.randrange(2)
    if sz: Q = 1
    op = random.choice([0x18, 0x19, 0x1A, 0x1B, 0x1C, 0x1D, 0x1E, 0x1F])
    return (Q << 30) | (U << 29) | 0x0E200400 | (a_ << 23) | (sz << 22) | (r5() << 16) | (op << 11) | (r5() << 5) | r5()


def fam_f2misc():
    # floating point two-register misc (a64.fp_2misc): FCVT{N,M,A,P,Z}{S,U}, SCVTF/UCVTF, FRECPE/FRSQRTE, FCVTL(2)/FCVTN(2), FCM* #0
    Q = random.randrange(2); U = random.randrange(2); size = random.randrange(4)
    op = random.choice([0x0C, 0x0D, 0x0E, 0x16, 0x17, 0x1A, 0x1B, 0x1C, 0x1D])
    return (Q << 30) | (U << 29) | 0x0E200800 | (size << 22) | (op << 12) | (r5() << 5) | r5()


def fam_felem():
    # FMLA / FMLS / FMUL / FMULX by element (vector), single and double lanes
    Q = random.randrange(2); U = random.randrange(2); dbl = random.randrange(2); op = random.choice([1, 5, 9])
    if op != 9: U = 0
    if dbl: Q = 1
    size = 3 if dbl else 2; H = random.randrange(2); L = 0 if dbl else random.randrange(2); M = random.randrange(2)
    return (Q << 30) | (U << 29) | 0x0F000000 | (size << 22) | (L << 21) | (M << 20) | ((r5() & 15) << 16) | (op << 12) | (H << 11) | (r5() << 5) | r5()


def fam_ld1lane():
    # LD1/ST1 one lane and LD1R, offset and post-index (a64.fast_ld1_lane)
    Q = random.randrange(2); post = random.randrange(2); opc = random.choice([0, 2, 4, 6]); L = 1 if opc == 6 else random.randrange(2)
    S = 0 if opc == 6 else random.randrange(2); size = random.randrange(4)
    if opc == 2: size &= 2
    if opc == 4: size = random.randrange(2); S = 0 if size else S
    rn = random.randrange(31); rm = random.choice([31, random.randrange(31)]) if post else 0
    if post and rm == rn: rm = 31
    return (Q << 30) | 0x0D000000 | (post << 23) | (L << 22) | (rm << 16) | (opc << 13) | (S << 12) | (size << 10) | (rn << 5) | r5()


def fam_movi():
    # MOVI / MVNI / ORR / BIC (modified immediate), every cmode but FMOV's
    Q = random.randrange(2); op = random.randrange(2); cmode = random.randrange(15)
    return (Q << 30) | (op << 29) | 0x0F000400 | (random.randrange(8) << 16) | (cmode << 12) | (random.randrange(32) << 5) | r5()


def fam_ielem():
    # MLA / MLS / MUL by element, 16 and 32 bit lanes (a64.fast_simd_int)
    Q = random.randrange(2); U, op = random.choice([(1, 0), (1, 4), (0, 8)]); size = random.choice([1, 2])
    return (Q << 30) | (U << 29) | 0x0F000000 | (size << 22) | (random.randrange(2) << 21) | (random.randrange(2) << 20) | \
        ((r5() & 15) << 16) | (op << 12) | (random.randrange(2) << 11) | (r5() << 5) | r5()


def fam_addlp():
    # SADDLP / UADDLP and SHLL (2)
    Q = random.randrange(2); size = random.randrange(3)
    U, op = random.choice([(0, 0x02), (1, 0x02), (1, 0x13)])
    return (Q << 30) | (U << 29) | 0x0E200800 | (size << 22) | (op << 12) | (r5() << 5) | r5()


def fam_bsel():
    # BSL / BIT / BIF, and SQDMULH / SQRDMULH (vector)
    Q = random.randrange(2)
    if random.randrange(2): return (Q << 30) | 0x2E201C00 | (random.randrange(1, 4) << 22) | (r5() << 16) | (r5() << 5) | r5()
    return (Q << 30) | (random.randrange(2) << 29) | 0x0E20B400 | (random.randrange(1, 3) << 22) | (r5() << 16) | (r5() << 5) | r5()


def fam_misc3():
    # SLI / SRI, FMOV (vector, immediate), ADDV / ADDLV / MAXV / MINV, DUP (element, scalar)
    Q = random.randrange(2); k = random.randrange(4)
    if k == 0:
        size = random.randrange(4 if Q else 3); eb = 8 << size; op = random.choice([0x08, 0x0A])
        v = (eb + random.randrange(eb)) if op == 0x0A else (2 * eb - random.randrange(1, eb + 1))
        return (Q << 30) | (1 << 29) | 0x0F000400 | ((v >> 3) << 19) | ((v & 7) << 16) | (op << 11) | (r5() << 5) | r5()
    if k == 1:
        op = random.randrange(2)
        if op: Q = 1
        return (Q << 30) | (op << 29) | 0x0F000400 | (random.randrange(8) << 16) | (15 << 12) | (random.randrange(32) << 5) | r5()
    if k == 2:
        U = random.randrange(2); op = random.choice([0x03, 0x0A, 0x1A] + ([] if U else [0x1B])); size = random.randrange(3 if Q else 2)
        return (Q << 30) | (U << 29) | 0x0E300800 | (size << 22) | (op << 12) | (r5() << 5) | r5()
    size = random.randrange(4); imm5 = (1 << size) | (random.randrange(16 >> size) << (size + 1))
    return 0x5E000400 | (imm5 << 16) | (r5() << 5) | r5()


FZ = len(sys.argv) > 4 and sys.argv[4] == 'fz'   # flush to zero, as the game sets FPCR.FZ in gameplay (MXCSR FTZ+DAZ)
fams = [fam_perm, fam_ext, fam_2misc, fam_3same, fam_ld1, fam_shimm, fam_3diff, fam_narrow, fam_3int, fam_f3same, fam_felem, fam_ld1lane, fam_movi, fam_ielem, fam_addlp, fam_bsel, fam_misc3, fam_f2misc]
cases = []
# Cover both widths and both signs of the packed float accumulate, including accumulator/source aliasing.
for q in range(2):
    for negate in range(2):
        for i in range(32):
            d, n, m = r5(), r5(), r5()
            if i % 4 == 1: n = d
            elif i % 4 == 2: m = d
            elif i % 4 == 3: n = m = d
            w = 0x0E20CC00 | (q << 30) | (negate << 23) | (m << 16) | (n << 5) | d
            cases.append((w, a.emit_static(w, 0x1000)))
while len(cases) < 3000:
    w = random.choice(fams)()
    code = a.emit_static(w, 0x1000)
    if not isinstance(code, str) or 'swr_simd' in code: continue
    cases.append((w, code))
L = ['#define FPCR_INIT %s' % ('0x01000000u' if FZ else '0u'), '#include "cpu.h"', '#include <stdio.h>', '#include <string.h>', '#include <math.h>',
     'int swr_simd(CPU* c, u8* M, u32 w);']
for i, (w, code) in enumerate(cases):
    L.append('static void g%d(CPU* RESTRICT c, u8* M){ %s }' % (i, code))
L.append('typedef void (*GF)(CPU* RESTRICT, u8*);')
L.append('static const GF F[]={%s};' % ','.join('g%d' % i for i in range(len(cases))))
L.append('static const u32 W[]={%s};' % ','.join('0x%08xu' % w for w, _ in cases))
L.append(r'''
static u64 s_=0x9E3779B97F4A7C15ull; static u64 rnd(void){ s_^=s_<<13; s_^=s_>>7; s_^=s_<<17; return s_; }
static u64 special(void){ static const u64 v[]={0,0x8000000000000000ull,0x7FF0000000000000ull,0xFFF0000000000000ull,0x7FF8000000000001ull,
  0x7FF0000000000001ull,1,0x3FF0000000000000ull,0x7F8000007FC00001ull,0x80000000FF800000ull,0x0000000100000001ull,0x3F800000BF800000ull};
  return rnd()%3? rnd() : v[rnd()%12]; }
#define MEMN 4096
static u8 m1[MEMN+256], m2[MEMN+256];
int main(void){ static CPU a,b; int bad=0;''' + (' { unsigned mx; __asm__ __volatile__("stmxcsr %0":"=m"(mx)); mx|=0x8040; __asm__ __volatile__("ldmxcsr %0"::"m"(mx)); }' if FZ else '') + r'''
  for(int i=0;i<(int)(sizeof W/sizeof W[0]);i++) for(int rep=0;rep<8;rep++){
    memset(&a,0,sizeof a); a.fpcr=FPCR_INIT; for(int r=0;r<32;r++){ a.v[r].d[0]=special(); a.v[r].d[1]=special(); a.x[r]=0x100+(rnd()%(MEMN-512)); }
    if((W[i]&0x9FE0FC00u)==0x0E60B400u && rep<3){
      /* Force saturation, saturation confined to the high 64 bits, and a preexisting QC. */
      int n=(W[i]>>5)&31, m=(W[i]>>16)&31;
      for(int lane=0;lane<8;lane++) a.v[n].sh[lane]=a.v[m].sh[lane]=
        rep==0 || (rep==1 && lane>=4) ? -32768 : 16384;
      if(rep==2) a.fpsr=1u<<27;
    }
    if(((W[i]>>24)&0xBE)==0x0C){ int rm=(W[i]>>16)&31; if(rm!=31) a.x[rm]=rnd()%64; }
    for(int k=0;k<MEMN;k++) m1[k]=(u8)rnd(); memcpy(m2,m1,MEMN); b=a;
    F[i](&a,m1); if(!swr_simd(&b,m2,W[i])){ printf("reference refused %08x\n",W[i]); bad++; continue; }
    if(memcmp(a.v,b.v,sizeof a.v) || memcmp(a.x,b.x,sizeof a.x) || memcmp(m1,m2,MEMN) || a.fpsr!=b.fpsr){
      bad++; if(bad<20){ printf("MISMATCH %08x\n",W[i]); for(int r=0;r<32;r++) if(memcmp(&a.v[r],&b.v[r],16)) printf("  v%d inline %016llx%016llx ref %016llx%016llx\n",r,
        (unsigned long long)a.v[r].d[1],(unsigned long long)a.v[r].d[0],(unsigned long long)b.v[r].d[1],(unsigned long long)b.v[r].d[0]); } } }
  printf("%d encodings x 8 states: %s (%d mismatches)\n",(int)(sizeof W/sizeof W[0]),bad?"FAIL":"PASS",bad); return bad!=0; }
''')
open(out + '/diff.c', 'w').write('\n'.join(L))
print('%d cases' % len(cases))
