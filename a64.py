# SwitchRecomp - Copyright 2026 MZ Labs
# Licensed under the GNU Affero General Public License v3.0, see LICENSE.txt and NOTICE.txt.
# Forks and derived works have to keep the credit to SwitchRecomp by MZ Labs and the startup screen.
"""a64: AArch64 (ARMv8.0 for Switch 1, plus the ARMv8.1-8.3 instructions Switch 2 code uses) instruction templates. each instruction is one python function that
emits its C, used two ways: static, where fields are constants (recompiled code), and dynamic,
where fields get decoded at runtime (fallback interpreter). so both paths share the same code.
the less common AdvSIMD ops call swr_simd() (hand written C, tested against unicorn like
everything else), the common ones are inlined"""

FIELDS = {
    'rd': (0, 5), 'rn': (5, 5), 'rm': (16, 5), 'ra': (10, 5), 'rt': (0, 5), 'rt2': (10, 5), 'rs': (16, 5),
    'sf': (31, 1), 'imm12': (10, 12), 'sh': (22, 1), 'imm6': (10, 6), 'shift': (22, 2), 'N': (22, 1),
    'immr': (16, 6), 'imms': (10, 6), 'hw': (21, 2), 'imm16': (5, 16), 'cond': (12, 4), 'bcond': (0, 4),
    'imm19': (5, 19, 1), 'imm26': (0, 26, 1), 'imm14': (5, 14, 1), 'b40': (19, 5), 'b5': (31, 1),
    'imm9': (12, 9, 1), 'imm7': (15, 7, 1), 'option': (13, 3), 'imm3': (10, 3), 'nzcv': (0, 4), 'imm5': (16, 5),
    'immlo': (29, 2), 'immhi': (5, 19, 1), 'S': (29, 1), 'op': (30, 1), 'opc': (29, 2), 'size': (30, 2),
    'ftype': (22, 2), 'rmode': (19, 2), 'fop': (16, 3), 'scale': (10, 6), 'imm8': (13, 8), 'o0': (15, 1),
    'o1': (21, 1), 'lopc': (22, 2), 'sysreg': (5, 15), 'CRm': (8, 4), 'op2': (5, 3), 'Sb': (12, 1),
    'V': (26, 1), 'L': (22, 1), 'mode': (23, 2), 'imode': (10, 2), 'op31': (21, 3), 'o2': (23, 1),
    'mteopc': (22, 2), 'mteop2': (10, 2), 'dpop': (10, 6), 'fop1': (15, 6), 'fop2': (12, 4), 'fcmpop': (3, 2), 'Q': (30, 1), 'lsop1': (21, 1),
    'op0_1': (21, 3), 'CRn': (12, 4), 'op1': (16, 3), 'b24': (24, 1), 'b21': (21, 1), 'b10': (10, 1), 'b11': (11, 1),
    'lseop': (12, 4),
    'pacS': (22, 1), 'pacimm9': (12, 9), 'pacW': (11, 1), 'uimm6': (16, 6), 'rmif_imm6': (15, 6),
}


def field(w, name):
    f = FIELDS[name]
    v = (w >> f[0]) & ((1 << f[1]) - 1)
    if len(f) > 2 and v >> (f[1] - 1):
        v -= 1 << f[1]
    return v


def lit(v):
    v &= 0xFFFFFFFFFFFFFFFF
    if v < 0x80000000: return str(v)
    return '0x%Xull' % v


def mask(n):
    return (1 << n) - 1 if n < 64 else 0xFFFFFFFFFFFFFFFF


class G:
    """generation context. static=True: constant fields"""
    __slots__ = ('static', 'w', '_pcv', 'spec', 'used', 'pcused')

    def __init__(self, static, w=0, pc=0, spec=None):
        self.static = static; self.w = w; self._pcv = pc; self.spec = spec or {}; self.used = set(); self.pcused = False

    @property
    def pcv(self):
        self.pcused = True; return self._pcv

    def v(self, n):
        if self.static: return field(self.w, n)
        if n in self.spec: return self.spec[n]
        raise KeyError('field %s not specialized' % n)

    def f(self, n):
        if self.static or n in self.spec: return lit(self.v(n)) if self.v(n) >= 0 else '(%d)' % self.v(n)
        self.used.add(n); return 'f_' + n

    def known(self, n):
        return self.static or n in self.spec

    @property
    def pc(self):
        return lit(self.pcv) if self.static else 'pc'

    def X(self, n):
        if self.known(n):
            r = self.v(n); return '0' if r == 31 else 'c->x[%d]' % r
        return 'RX(%s)' % self.f(n)

    def W(self, n):
        x = self.X(n); return '0' if x == '0' else '(u32)' + x

    def XS(self, n):
        return 'c->x[%s]' % self.f(n)

    def WS(self, n):
        return '(u32)c->x[%s]' % self.f(n)

    def setX(self, n, e):
        if self.known(n):
            r = self.v(n)
            return '(void)(%s);' % e if r == 31 else 'c->x[%d]=(u64)(%s);' % (r, e)
        return 'SETX(%s,(u64)(%s));' % (self.f(n), e)

    def setW(self, n, e):
        return self.setX(n, '(u32)(%s)' % e)

    def setXS(self, n, e):
        return 'c->x[%s]=(u64)(%s);' % (self.f(n), e)

    def setWS(self, n, e):
        return 'c->x[%s]=(u64)(u32)(%s);' % (self.f(n), e)

    def Vr(self, n):
        return 'c->v[%s]' % self.f(n)


# ======================================================================= table
TABLE = []


def ins(name, pattern, spec=(), kind=None):
    p = pattern.replace(' ', '')
    assert len(p) == 32, (name, len(p))
    m = v = 0
    for i, ch in enumerate(p):
        b = 31 - i
        if ch in '01':
            m |= 1 << b
            if ch == '1': v |= 1 << b

    def deco(fn):
        TABLE.append((name, m, v, tuple(spec), fn))
        return fn
    return deco


# ------------------------------------------------------------------ PC-relative
@ins('ADR', '0 xx 10000 xxxxxxxxxxxxxxxxxxx xxxxx')
def _(g):
    if g.static:
        imm = (field(g.w, 'immhi') << 2) | field(g.w, 'immlo')
        return g.setX('rd', lit(g.pcv + imm))
    return g.setX('rd', 'pc+(u64)(i64)((%s<<2)|%s)' % (g.f('immhi'), g.f('immlo')))


@ins('ADRP', '1 xx 10000 xxxxxxxxxxxxxxxxxxx xxxxx')
def _(g):
    if g.static:
        imm = ((field(g.w, 'immhi') << 2) | field(g.w, 'immlo')) << 12
        return g.setX('rd', lit((g.pcv & ~0xFFF) + imm))
    return g.setX('rd', '(pc&~0xFFFull)+((u64)(i64)((%s<<2)|%s)<<12)' % (g.f('immhi'), g.f('immlo')))


# ------------------------------------------------------------------ add/sub immediate
@ins('ADDSUB_IMM', 'x x x 100010 x xxxxxxxxxxxx xxxxx xxxxx', spec=('sf', 'op', 'S', 'sh'))
def _(g):
    sf, op, S, sh = g.v('sf'), g.v('op'), g.v('S'), g.v('sh')
    imm = '(%s<<12)' % g.f('imm12') if sh else g.f('imm12')
    if g.static: imm = lit(field(g.w, 'imm12') << (12 * sh))
    if sf:
        a = g.XS('rn')
        if S: return g.setX('rd', ('subs64(c,%s,%s)' if op else 'adds64(c,%s,%s,0)') % (a, imm))
        return g.setXS('rd', '%s%s%s' % (a, '-' if op else '+', imm))
    a = g.WS('rn')
    if S: return g.setW('rd', ('subs32(c,%s,(u32)%s)' if op else 'adds32(c,%s,(u32)%s,0)') % (a, imm))
    return g.setWS('rd', '%s%s(u32)%s' % (a, '-' if op else '+', imm))


# ------------------------------------------------------------------ logical immediate
def decode_bitmask(N, imms, immr, ds):
    v = (N << 6) | (~imms & 0x3F)
    ln = v.bit_length() - 1
    if ln < 1: return None
    esize = 1 << ln; levels = esize - 1
    S = imms & levels; R = immr & levels
    if S == levels: return None
    we = mask(S + 1)
    if R: we = ((we >> R) | (we << (esize - R))) & mask(esize)
    r = 0
    for i in range(0, ds, esize): r |= we << i
    return r & mask(ds)


@ins('LOGIC_IMM', 'x xx 100100 x xxxxxx xxxxxx xxxxx xxxxx', spec=('sf', 'opc'))
def _(g):
    sf, opc = g.v('sf'), g.v('opc')
    ds = 64 if sf else 32
    if g.static:
        if not sf and g.v('N'): return None
        m = decode_bitmask(g.v('N'), g.v('imms'), g.v('immr'), ds)
        if m is None: return None
        imm = lit(m)
    else:
        imm = 'swr_decode_bitmask(%s,%s,%s,%d)' % (g.f('N'), g.f('imms'), g.f('immr'), ds)
    src = g.X('rn') if sf else g.W('rn')
    opx = ['&', '|', '^', '&'][opc]
    e = '(%s%s%s)' % (src, opx, imm)
    if opc == 3:
        return ('{ u64 r_=%s; logic64(c,r_); %s }' % (e, g.setX('rd', 'r_'))) if sf else \
               ('{ u32 r_=(u32)%s; logic32(c,r_); %s }' % (e, g.setW('rd', 'r_')))
    return g.setXS('rd', e) if sf else g.setWS('rd', e)


# ------------------------------------------------------------------ move wide
@ins('MOVW', 'x xx 100101 xx xxxxxxxxxxxxxxxx xxxxx', spec=('sf', 'opc'))
def _(g):
    sf, opc = g.v('sf'), g.v('opc')
    if opc == 1: return None
    if g.static:
        hw = g.v('hw')
        if not sf and hw >= 2: return None
        sh = hw * 16; imm = g.v('imm16') << sh
        if opc == 0: return (g.setX if sf else g.setW)('rd', lit(~imm & mask(64 if sf else 32)))
        if opc == 2: return (g.setX if sf else g.setW)('rd', lit(imm))
        keep = lit(~(0xFFFF << sh) & mask(64))
        return (g.setX if sf else g.setW)('rd', '(%s&%s)|%s' % (g.X('rd'), keep, lit(imm)))
    sh = '(%s*16)' % g.f('hw'); imm = '((u64)%s<<%s)' % (g.f('imm16'), sh)
    if opc == 0: return (g.setX if sf else g.setW)('rd', '~%s' % imm)
    if opc == 2: return (g.setX if sf else g.setW)('rd', imm)
    return (g.setX if sf else g.setW)('rd', '(%s&~(0xFFFFull<<%s))|%s' % (g.X('rd'), sh, imm))


# ------------------------------------------------------------------ bit fields
@ins('BITFIELD', 'x xx 100110 x xxxxxx xxxxxx xxxxx xxxxx', spec=('sf', 'opc'))
def _(g):
    sf, opc = g.v('sf'), g.v('opc')
    if opc == 3: return None
    ds = 64 if sf else 32
    src = g.X('rn') if sf else g.W('rn')
    wr = g.setX if sf else g.setW
    if not g.static:
        if opc == 0: return wr('rd', 'sbfm_(%s,%s,%s,%d)' % (src, g.f('immr'), g.f('imms'), ds))
        if opc == 2: return wr('rd', 'ubfm_(%s,%s,%s,%d)' % (src, g.f('immr'), g.f('imms'), ds))
        dst = g.X('rd') if sf else g.W('rd')
        return wr('rd', 'bfm_(%s,%s,%s,%s,%d)' % (dst, src, g.f('immr'), g.f('imms'), ds))
    N, immr, imms = g.v('N'), g.v('immr'), g.v('imms')
    if N != sf or (not sf and (immr > 31 or imms > 31)): return None
    T = 'u64' if sf else 'u32'; ST = 'i64' if sf else 'i32'
    if opc == 2:
        if imms >= immr:
            w = imms - immr + 1
            if immr == 0 and w == ds: return wr('rd', src)
            if immr + w == ds: return wr('rd', '(%s)%s>>%d' % (T, src, immr))
            return wr('rd', '((%s)%s>>%d)&%s' % (T, src, immr, lit(mask(w))))
        w = imms + 1; p = ds - immr
        return wr('rd', '((%s)%s<<%d)&%s' % (T, src, p, lit(mask(w) << p)))
    if opc == 0:
        if imms >= immr:
            w = imms - immr + 1
            if immr == 0 and w == ds: return wr('rd', src)
            return wr('rd', '(%s)((%s)((%s)%s<<%d)>>%d)' % (T, ST, T, src, ds - immr - w, ds - w))
        w = imms + 1; p = ds - immr
        return wr('rd', '(%s)(((%s)((%s)%s<<%d)>>%d)<<%d)' % (T, ST, T, src, ds - w, ds - w, p))
    dst = g.X('rd') if sf else g.W('rd')
    if imms >= immr:
        w = imms - immr + 1; m = mask(w)
        return wr('rd', '(%s&%s)|(((%s)%s>>%d)&%s)' % (dst, lit(~m & mask(ds)), T, src, immr, lit(m)))
    w = imms + 1; p = ds - immr; m = (mask(w) << p) & mask(ds)
    return wr('rd', '(%s&%s)|(((%s)%s<<%d)&%s)' % (dst, lit(~m & mask(ds)), T, src, p, lit(m)))


@ins('EXTR', 'x 00 100111 x 0 xxxxx xxxxxx xxxxx xxxxx', spec=('sf',))
def _(g):
    sf = g.v('sf')
    if g.static:
        if g.v('N') != sf: return None
        lsb = g.v('imms')
        if not sf and lsb > 31: return None
        if sf:
            if lsb == 0: return g.setX('rd', g.X('rm'))
            return g.setX('rd', '(%s>>%d)|(%s<<%d)' % (g.X('rm'), lsb, g.X('rn'), 64 - lsb))
        if lsb == 0: return g.setW('rd', g.W('rm'))
        return g.setW('rd', '((u32)%s>>%d)|((u32)%s<<%d)' % (g.W('rm'), lsb, g.W('rn'), 32 - lsb))
    l = g.f('imms')
    if sf: return g.setX('rd', '%s? (%s>>%s)|(%s<<(64-%s)) : %s' % (l, g.X('rm'), l, g.X('rn'), l, g.X('rm')))
    return g.setW('rd', '%s? ((u32)%s>>%s)|((u32)%s<<(32-%s)) : %s' % (l, g.W('rm'), l, g.W('rn'), l, g.W('rm')))


# ------------------------------------------------------------------ branches
@ins('B', '0 00101 xxxxxxxxxxxxxxxxxxxxxxxxxx')
def _(g):
    if g.static: return ('b', g.pcv + g.v('imm26') * 4)
    return ('b', 'pc+(u64)((i64)%s*4)' % g.f('imm26'))


@ins('BL', '1 00101 xxxxxxxxxxxxxxxxxxxxxxxxxx')
def _(g):
    if g.static: return ('bl', g.pcv + g.v('imm26') * 4)
    return ('bl', 'pc+(u64)((i64)%s*4)' % g.f('imm26'))


def cond_expr(g, cf):
    if not g.known(cf): return 'cond_ok(c,%s)' % g.f(cf)
    c = g.v(cf)
    base = ['c->z', 'c->cf', 'c->n', 'c->vf', '(c->cf&&!c->z)', '(c->n==c->vf)', '(!c->z&&c->n==c->vf)', '1'][c >> 1]
    if c >> 1 == 7: return '1'
    return ('!' + base) if c & 1 else base


@ins('BCOND', '0101010 0 xxxxxxxxxxxxxxxxxxx 0 xxxx')
def _(g):
    t = g.pcv + g.v('imm19') * 4 if g.static else 'pc+(u64)((i64)%s*4)' % g.f('imm19')
    return ('bc', cond_expr(g, 'bcond'), t)


@ins('CBZ', 'x 011010 x xxxxxxxxxxxxxxxxxxx xxxxx', spec=('sf', 'b24'))
def _(g):
    r = g.X('rt') if g.v('sf') else g.W('rt')
    t = g.pcv + g.v('imm19') * 4 if g.static else 'pc+(u64)((i64)%s*4)' % g.f('imm19')
    return ('bc', '(%s%s0)' % (r, '!=' if g.v('b24') else '=='), t)


@ins('TBZ', 'x 011011 x xxxxx xxxxxxxxxxxxxx xxxxx', spec=('b24',))
def _(g):
    if g.static:
        bit = (g.v('b5') << 5) | g.v('b40')
        e = '((%s>>%d)&1)' % (g.X('rt'), bit)
        t = g.pcv + g.v('imm14') * 4
    else:
        e = '((%s>>((%s<<5)|%s))&1)' % (g.X('rt'), g.f('b5'), g.f('b40'))
        t = 'pc+(u64)((i64)%s*4)' % g.f('imm14')
    return ('bc', e if g.v('b24') else '!' + e, t)


@ins('BR', '1101011 0000 11111 000000 xxxxx 00000')
def _(g): return ('br', g.X('rn'))


@ins('BLR', '1101011 0001 11111 000000 xxxxx 00000')
def _(g): return ('blr', g.X('rn'))


@ins('RET', '1101011 0010 11111 000000 xxxxx 00000')
def _(g): return ('ret', g.X('rn'))


# pointer authentication (ARMv8.3, Switch 2 code): nothing here signs pointers (PACIASP and the other hint forms are
# NOPs), so the authenticating branches are the plain ones and PAC/AUT/XPAC leave the register as it is
@ins('RETAA', '1101011 0010 11111 00001 x 11111 11111')
def _(g): return ('ret', 'c->x[30]')


@ins('BRAZ', '1101011 0000 11111 00001 x xxxxx 11111')
def _(g): return ('br', g.X('rn'))


@ins('BLRAZ', '1101011 0001 11111 00001 x xxxxx 11111')
def _(g): return ('blr', g.X('rn'))


@ins('BRA', '1101011 1000 11111 00001 x xxxxx xxxxx')
def _(g): return ('br', g.X('rn'))


@ins('BLRA', '1101011 1001 11111 00001 x xxxxx xxxxx')
def _(g): return ('blr', g.X('rn'))


@ins('PACAUT', '1 1 0 11010110 00001 00 x xxx xxxxx xxxxx')
def _(g): return ''


@ins('XPAC', '1 1 0 11010110 00001 01000 x 11111 xxxxx')
def _(g): return ''


# memory tagging stores (ARMv8.5 STG/STZG/ST2G/STZ2G): tags are always 0, so only the zeroing forms write data and
# the pre/post-index forms update the base. opc 01 with op2 00 is LDG: the pointer keeps tag 0
@ins('MTE_TAGST', '11011001 xx 1 xxxxxxxxx xx xxxxx xxxxx', spec=('mteopc', 'mteop2'))
def _(g):
    opc, op2 = g.v('mteopc'), g.v('mteop2')
    if op2 == 0:
        return '' if opc == 1 else None
    if opc == 3 and False: return None
    off = '(%s<<4)' % g.f('imm9')
    base = g.XS('rn')
    addr = base if op2 == 1 else '(%s+%s)' % (base, off)
    code = ''
    if opc in (1, 3):   # STZG, STZ2G: zero 16 or 32 bytes
        n = 2 if opc == 1 else 4
        code = ' '.join('WR64(%s+%d,0);' % (addr, 8 * i) for i in range(n))
    if op2 in (1, 3):
        code += ' ' + g.setXS('rn', '%s+%s' % (base, off))
    return code.strip()


# ------------------------------------------------------------------ system
@ins('SVC', '11010100 000 xxxxxxxxxxxxxxxx 00001')
def _(g): return ('svc', g.f('imm16'))


@ins('BRK', '11010100 001 xxxxxxxxxxxxxxxx 00000')
def _(g): return ('brk', g.f('imm16'))


@ins('HINT', '11010101 00000011 0010 xxxx xxx 11111')
def _(g):
    if g.static:
        k = (g.v('CRm') << 3) | g.v('op2')
        if k == 1: return 'YIELD();'
        if k == 2: return 'c->rt->wfe(c);'
        if k in (4, 5): return 'c->rt->sev();'
        return ''
    return '{ u32 k_=(%s<<3)|%s; if(k_==1) YIELD(); else if(k_==2) c->rt->wfe(c); else if(k_==4||k_==5) c->rt->sev(); }' % (g.f('CRm'), g.f('op2'))


@ins('CLREX', '11010101 00000011 0011 xxxx 010 11111')
def _(g): return 'c->excl_on=0;'


@ins('BARRIER', '11010101 00000011 0011 xxxx 1xx 11111')
def _(g):
    if g.static:
        op2 = g.v('op2'); crm = g.v('CRm')
        if op2 == 6: return 'CBAR();'                 # ISB
        if (crm & 3) == 1: return 'CBAR();'           # DMB/DSB ld-only
        return 'SWR_FENCE();'
    return 'SWR_FENCE();'


@ins('MSR_IMM', '1101010100000 xxx 0100 xxxx xxx 11111')
def _(g): return ''


@ins('SYS', '1101010100001 xxx xxxx xxxx xxx xxxxx')
def _(g):
    if g.static:
        if g.v('op1') == 3 and g.v('CRn') == 7 and g.v('CRm') == 4 and g.v('op2') == 1:
            return 'dc_zva(M,%s);' % g.X('rt')
        return ''
    return 'if(%s==3&&%s==7&&%s==4&&%s==1) dc_zva(M,%s);' % (g.f('op1'), g.f('CRn'), g.f('CRm'), g.f('op2'), g.X('rt'))


SR_TPIDR = (1 << 14) | (3 << 11) | (13 << 7) | (0 << 3) | 2
SR_TPIDRRO = SR_TPIDR + 1
SR_NZCV = (1 << 14) | (3 << 11) | (4 << 7) | (2 << 3) | 0


@ins('MRS', '1101010100 1 1 x xxx xxxx xxxx xxx xxxxx')
def _(g):
    if g.static:
        r = g.v('sysreg')
        if r == SR_TPIDR: return g.setX('rt', 'c->tpidr')
        if r == SR_TPIDRRO: return g.setX('rt', 'c->tpidrro')
        if r == SR_NZCV: return g.setX('rt', 'get_nzcv(c)')
    return g.setX('rt', 'swr_mrs(c,%s)' % g.f('sysreg'))


@ins('MSR', '1101010100 0 1 x xxx xxxx xxxx xxx xxxxx')
def _(g):
    if g.static:
        r = g.v('sysreg')
        if r == SR_TPIDR: return 'c->tpidr=%s;' % g.X('rt')
        if r == SR_NZCV: return 'set_nzcv(c,(u32)(%s>>28));' % g.X('rt')
    return 'swr_msr(c,%s,%s);' % (g.f('sysreg'), g.X('rt'))


# ------------------------------------------------------------------ loads / stores
RD = {0: 'RD8', 1: 'RD16', 2: 'RD32', 3: 'RD64'}
RDS = {0: 'RDS8', 1: 'RDS16', 2: 'RDS32'}
WR = {0: 'WR8', 1: 'WR16', 2: 'WR32', 3: 'WR64'}


def ldst_body(g, size, V, opc, A):
    """C for the transfer with the address already in 'A' (expression)"""
    if not V:
        if opc == 0: return '%s(%s,%s);' % (WR[size], A, g.X('rt'))
        if opc == 1: return g.setX('rt', '%s(%s)' % (RD[size], A))
        if opc == 2:
            if size == 3: return ''                                  # PRFM
            return g.setX('rt', '(u64)(i64)%s(%s)' % (RDS[size], A))
        if size >= 2: return None
        return g.setW('rt', '(u32)(i32)%s(%s)' % (RDS[size], A))
    t = g.f('rt')
    if opc >= 2:
        if size != 0: return None
        if opc == 2: return 'WRQ(%s,c->v[%s]);' % (A, t)
        return 'RDQ(c->v[%s],%s);' % (t, A)
    if opc == 0: return '%s(%s,c->v[%s].d[0]);' % (WR[size], A, t)
    return '{ u64 t_=%s(%s); c->v[%s].d[1]=0; c->v[%s].d[0]=t_; }' % (RD[size], A, t, t)


def ls_scale(size, V, opc):
    return 4 if (V and opc >= 2) else size


@ins('LDST_UIMM', 'xx 111 x 01 xx xxxxxxxxxxxx xxxxx xxxxx', spec=('size', 'V', 'lopc'))
def _(g):
    size, V, opc = g.v('size'), g.v('V'), g.v('lopc')
    sc = ls_scale(size, V, opc)
    if g.static: off = lit(g.v('imm12') << sc)
    else: off = '((u64)%s<<%d)' % (g.f('imm12'), sc)
    A = '%s+%s' % (g.XS('rn'), off) if off != '0' else g.XS('rn')
    return ldst_body(g, size, V, opc, '(%s)' % A)


@ins('LDST_IMM9', 'xx 111 x 00 xx 0 xxxxxxxxx xx xxxxx xxxxx', spec=('size', 'V', 'lopc', 'imode'))
def _(g):
    size, V, opc, mode = g.v('size'), g.v('V'), g.v('lopc'), g.v('imode')
    off = g.f('imm9')
    if mode in (0, 2):
        return ldst_body(g, size, V, opc, '(%s+(u64)(i64)%s)' % (g.XS('rn'), off))
    body = ldst_body(g, size, V, opc, 'a_')
    if body is None: return None
    if mode == 1:
        return '{ u64 a_=%s; %s %s }' % (g.XS('rn'), body, g.setXS('rn', 'a_+(u64)(i64)%s' % off))
    return '{ u64 a_=%s+(u64)(i64)%s; %s %s }' % (g.XS('rn'), off, body, g.setXS('rn', 'a_'))


@ins('LDST_REG', 'xx 111 x 00 xx 1 xxxxx xxx x 10 xxxxx xxxxx', spec=('size', 'V', 'lopc'))
def _(g):
    size, V, opc = g.v('size'), g.v('V'), g.v('lopc')
    sc = ls_scale(size, V, opc)
    if g.static:
        opt = g.v('option'); S = g.v('Sb')
        if not opt & 2: return None
        sh = sc if S else 0
        m = g.X('rm')
        if opt == 3 or opt == 7: e = m
        elif opt == 2: e = '(u64)(u32)%s' % m
        else: e = '(u64)(i64)(i32)%s' % m
        if sh: e = '(%s<<%d)' % (e, sh)
    else:
        e = 'ext64(%s,%s,%s?%d:0)' % (g.X('rm'), g.f('option'), g.f('Sb'), sc)
    return ldst_body(g, size, V, opc, '(%s+%s)' % (g.XS('rn'), e))


@ins('LDR_LIT', 'xx 011 x 00 xxxxxxxxxxxxxxxxxxx xxxxx', spec=('lopc_lit', 'V'))
def _(g):
    opc, V = g.v('lopc_lit'), g.v('V')
    A = lit(g.pcv + g.v('imm19') * 4) if g.static else '(pc+(u64)((i64)%s*4))' % g.f('imm19')
    if not V:
        if opc == 0: return g.setX('rt', 'RD32(%s)' % A)
        if opc == 1: return g.setX('rt', 'RD64(%s)' % A)
        if opc == 2: return g.setX('rt', '(u64)(i64)RDS32(%s)' % A)
        return ''
    if opc == 3: return None
    return ldst_body(g, [2, 3, 0][opc], 1, [1, 1, 3][opc], A)


FIELDS['lopc_lit'] = (30, 2)


@ins('LDSTP', 'xx 101 x 0 xx x xxxxxxx xxxxx xxxxx xxxxx', spec=('size', 'V', 'mode', 'L'))
def _(g):
    opc, V, mode, L = g.v('size'), g.v('V'), g.v('mode'), g.v('L')
    if V:
        if opc == 3: return None
        sz = 2 + opc; by = 4 << opc
    else:
        if opc == 3 or (opc == 1 and not L): return None
        sz = 3 if opc == 2 else 2; by = 8 if opc == 2 else 4
    off = lit(g.v('imm7') * by) if g.static else '((u64)(i64)%s*%d)' % (g.f('imm7'), by)
    base = g.XS('rn')
    a = base if mode == 1 else '%s+%s' % (base, off)
    s = '{ u64 a_=%s; ' % a
    if not V:
        if L:
            if opc == 1: rd1, rd2 = '(u64)(i64)RDS32(a_)', '(u64)(i64)RDS32(a_+4)'
            else: rd1, rd2 = '%s(a_)' % RD[sz], '%s(a_+%d)' % (RD[sz], by)
            s += 'u64 v1_=%s, v2_=%s; %s %s ' % (rd1, rd2, g.setX('rt', 'v1_'), g.setX('rt2', 'v2_'))
        else:
            s += '%s(a_,%s); %s(a_+%d,%s); ' % (WR[sz], g.X('rt'), WR[sz], by, g.X('rt2'))
    else:
        t1, t2 = g.f('rt'), g.f('rt2')
        if sz == 4:
            if L: s += 'V128 q1_,q2_; RDQ(q1_,a_); RDQ(q2_,a_+16); c->v[%s]=q1_; c->v[%s]=q2_; ' % (t1, t2)
            else: s += 'WRQ(a_,c->v[%s]); WRQ(a_+16,c->v[%s]); ' % (t1, t2)
        else:
            if L: s += 'u64 v1_=%s(a_), v2_=%s(a_+%d); c->v[%s].d[0]=v1_; c->v[%s].d[1]=0; c->v[%s].d[0]=v2_; c->v[%s].d[1]=0; ' % (
                RD[sz], RD[sz], by, t1, t1, t2, t2)
            else: s += '%s(a_,c->v[%s].d[0]); %s(a_+%d,c->v[%s].d[0]); ' % (WR[sz], t1, WR[sz], by, t2)
    if mode == 1: s += g.setXS('rn', 'a_+%s' % off)
    elif mode == 3: s += g.setXS('rn', 'a_')
    return s + ' }'


@ins('LDSTX', 'xx 001000 x x x xxxxx x xxxxx xxxxx xxxxx', spec=('size', 'o2', 'L', 'o1'))
def _(g):
    size, o2, L, o1 = g.v('size'), g.v('o2'), g.v('L'), g.v('o1')
    A = g.XS('rn')
    if not o2 and not o1:
        if L: return g.setX('rt', 'ldx(c,M,%s,%d)' % (A, size))
        return g.setW('rs', 'stx(c,M,%s,%d,%s)' % (A, size, g.X('rt')))
    if not o2 and o1:
        if size < 2:   # CASP (LSE): size 0 a pair of words, 1 a pair of doublewords; Rs and Rt are even (never 31)
            if g.static and (g.v('rs') & 1 or g.v('rt') & 1 or g.v('rt2') != 31): return None
            rs, rt, cast = g.f('rs'), g.f('rt'), '(u32)' if size == 0 else ''
            return ('{ u64 e0_=c->x[%s], e1_=c->x[%s+1]; swr_casp(M,%s,%d,&e0_,&e1_,c->x[%s],c->x[%s+1]); '
                    'c->x[%s]=%se0_; c->x[%s+1]=%se1_; }' % (rs, rs, g.XS('rn'), size + 2, rt, rt, rs, cast, rs, cast))
        if L: return '{ u64 v1_,v2_; ldxp(c,M,%s,%d,&v1_,&v2_); %s %s }' % (A, size, g.setX('rt', 'v1_'), g.setX('rt2', 'v2_'))
        return g.setW('rs', 'stxp(c,M,%s,%d,%s,%s)' % (A, size, g.X('rt'), g.X('rt2')))
    if o2 and not o1:
        ctype = ['u8', 'u16', 'u32', 'u64'][size]
        if L: return g.setX('rt', 'LDAR_(%s,%s)' % (ctype, A))
        return 'STLR_(%s,%s,%s);' % (ctype, A, g.X('rt'))
    # CAS, CASA, CASL, CASAL (LSE) in every size: Rs gets the old value, memory gets Rt when it held Rs
    if g.static and g.v('rt2') != 31: return None
    return g.setX('rs', 'swr_casv(M,%s,%d,%s,%s)' % (A, size, g.X('rs'), g.X('rt')))


# LDAPR (ARMv8.3 RCpc): a load-acquire, LDAR's code
@ins('LDAPR', 'xx 111000 101 11111 110000 xxxxx xxxxx', spec=('size',))
def _(g):
    return g.setX('rt', 'LDAR_(%s,%s)' % (['u8', 'u16', 'u32', 'u64'][g.v('size')], g.XS('rn')))


# LSE atomics (ARMv8.1): LDADD LDCLR LDEOR LDSET LDSMAX LDSMIN LDUMAX LDUMIN (o3=0, opc) and SWP (o3=1, opc=0), with
# any acquire/release bits (all are sequentially consistent here). Rt gets the old value, Rt=XZR is the ST* alias.
# swr_lse is in cpu.h; a STXR of another thread still sees the change (its compare-and-swap fails)
@ins('LSE', 'xx 111000 x x 1 xxxxx xxxx 00 xxxxx xxxxx', spec=('size', 'lseop'))
def _(g):
    op = g.v('lseop')
    if op > 8: return None
    return g.setX('rt', 'swr_lse(M,%s,%d,%d,%s)' % (g.XS('rn'), g.v('size'), op, g.X('rs')))


# ------------------------------------------------------------------ logical / register arithmetic
def shifted(g, reg, sf):
    """shifted register operand (LSL/LSR/ASR/ROR #imm6)"""
    if g.static:
        t, a = g.v('shift'), g.v('imm6')
        x = g.X(reg) if sf else g.W(reg)
        if a == 0 or x == '0': return x
        T = 'u64' if sf else 'u32'; ST = 'i64' if sf else 'i32'
        if t == 0: return '((%s)%s<<%d)' % (T, x, a)
        if t == 1: return '((%s)%s>>%d)' % (T, x, a)
        if t == 2: return '(%s)((%s)%s>>%d)' % (T, ST, x, a)
        return ('ror64(%s,%d)' if sf else 'ror32(%s,%d)') % (x, a)
    if sf: return 'shf64(%s,%s,%s)' % (g.X(reg), g.f('shift'), g.f('imm6'))
    return 'shf32(%s,%s,%s)' % (g.W(reg), g.f('shift'), g.f('imm6'))


@ins('LOGIC_REG', 'x xx 01010 xx x xxxxx xxxxxx xxxxx xxxxx', spec=('sf', 'opc', 'o1'))
def _(g):
    sf, opc, N = g.v('sf'), g.v('opc'), g.v('o1')
    if not sf and g.static and g.v('imm6') > 31: return None
    b = shifted(g, 'rm', sf)
    if N: b = '(~%s)' % b if b != '0' else ('~0ull' if sf else '0xFFFFFFFFu')
    a = g.X('rn') if sf else g.W('rn')
    if g.static and opc == 1 and a == '0' and not N:
        return (g.setX if sf else g.setW)('rd', b)                 # MOV
    e = '(%s%s%s)' % (a, ['&', '|', '^', '&'][opc], b)
    if opc == 3:
        return ('{ u64 r_=%s; logic64(c,r_); %s }' % (e, g.setX('rd', 'r_'))) if sf else \
               ('{ u32 r_=(u32)%s; logic32(c,r_); %s }' % (e, g.setW('rd', 'r_')))
    return (g.setX if sf else g.setW)('rd', e)


@ins('ADDSUB_SREG', 'x x x 01011 xx 0 xxxxx xxxxxx xxxxx xxxxx', spec=('sf', 'op', 'S'))
def _(g):
    sf, op, S = g.v('sf'), g.v('op'), g.v('S')
    if g.static and (g.v('shift') == 3 or (not sf and g.v('imm6') > 31)): return None
    b = shifted(g, 'rm', sf)
    a = g.X('rn') if sf else g.W('rn')
    if sf:
        if S: return g.setX('rd', ('subs64(c,%s,%s)' if op else 'adds64(c,%s,%s,0)') % (a, b))
        if a == '0' and op: return g.setX('rd', '0-%s' % b)
        return g.setX('rd', '%s%s%s' % (a, '-' if op else '+', b))
    if S: return g.setW('rd', ('subs32(c,%s,%s)' if op else 'adds32(c,%s,%s,0)') % (a, b))
    return g.setW('rd', '(u32)%s%s(u32)%s' % (a, '-' if op else '+', b))


@ins('ADDSUB_EXT', 'x x x 01011 00 1 xxxxx xxx xxx xxxxx xxxxx', spec=('sf', 'op', 'S'))
def _(g):
    sf, op, S = g.v('sf'), g.v('op'), g.v('S')
    if g.static:
        opt, sh = g.v('option'), g.v('imm3')
        if sh > 4: return None
        m = g.X('rm')
        ex = ['(u64)(u8)%s', '(u64)(u16)%s', '(u64)(u32)%s', '(u64)%s', '(u64)(i64)(i8)%s', '(u64)(i64)(i16)%s',
              '(u64)(i64)(i32)%s', '(u64)%s'][opt] % m
        b = '(%s<<%d)' % (ex, sh) if sh else ex
    else:
        b = 'ext64(%s,%s,%s)' % (g.X('rm'), g.f('option'), g.f('imm3'))
    a = g.XS('rn')
    if sf:
        if S: return g.setX('rd', ('subs64(c,%s,%s)' if op else 'adds64(c,%s,%s,0)') % (a, b))
        return g.setXS('rd', '%s%s%s' % (a, '-' if op else '+', b))
    if S: return g.setW('rd', ('subs32(c,(u32)%s,(u32)%s)' if op else 'adds32(c,(u32)%s,(u32)%s,0)') % (a, b))
    return g.setWS('rd', '(u32)%s%s(u32)%s' % (a, '-' if op else '+', b))


@ins('ADC', 'x x x 11010000 xxxxx 000000 xxxxx xxxxx', spec=('sf', 'op', 'S'))
def _(g):
    sf, op, S = g.v('sf'), g.v('op'), g.v('S')
    a = g.X('rn') if sf else g.W('rn'); b = g.X('rm') if sf else g.W('rm')
    if sf:
        if S: return g.setX('rd', ('sbcs64(c,%s,%s,c->cf)' if op else 'adds64(c,%s,%s,c->cf)') % (a, b))
        return g.setX('rd', ('%s+~%s+c->cf' if op else '%s+%s+c->cf') % (a, b))
    if S: return g.setW('rd', ('sbcs32(c,%s,%s,c->cf)' if op else 'adds32(c,%s,%s,c->cf)') % (a, b))
    return g.setW('rd', ('(u32)%s+~(u32)%s+c->cf' if op else '(u32)%s+(u32)%s+c->cf') % (a, b))


@ins('CCMP', 'x x 1 11010010 xxxxx xxxx x 0 xxxxx 0 xxxx', spec=('sf', 'op', 'b11'))
def _(g):
    sf, op, im = g.v('sf'), g.v('op'), g.v('b11')
    a = g.X('rn') if sf else g.W('rn')
    b = g.f('imm5') if im else (g.X('rm') if sf else g.W('rm'))
    fn = ('subs%d(c,%s,%s)' if op else 'adds%d(c,%s,%s,0)') % (64 if sf else 32, a, b)
    return 'if(%s) (void)%s; else set_nzcv(c,%s);' % (cond_expr(g, 'cond'), fn, g.f('nzcv'))


@ins('CSEL', 'x x 0 11010100 xxxxx xxxx 0 x xxxxx xxxxx', spec=('sf', 'op', 'b10'))
def _(g):
    sf, op, o2 = g.v('sf'), g.v('op'), g.v('b10')
    a = g.X('rn') if sf else g.W('rn'); b = g.X('rm') if sf else g.W('rm')
    T = 'u64' if sf else 'u32'
    if op == 0 and o2 == 0: e = b
    elif op == 0: e = '(%s)(%s+1)' % (T, b)
    elif o2 == 0: e = '(%s)~%s' % (T, b)
    else: e = '(%s)(0-%s)' % (T, b)
    return (g.setX if sf else g.setW)('rd', '%s? %s : %s' % (cond_expr(g, 'cond'), a, e))


@ins('DP1', 'x 1 0 11010110 00000 xxxxxx xxxxx xxxxx', spec=('sf', 'dpop'))
def _(g):
    sf, op = g.v('sf'), g.v('dpop')
    a = g.X('rn') if sf else g.W('rn')
    if sf:
        e = {0: 'rbit64(%s)', 1: 'rev16_64(%s)', 2: 'rev32_64(%s)', 3: 'bswap64(%s)', 4: 'clz64(%s)', 5: 'cls64(%s)'}.get(op)
    else:
        e = {0: 'rbit32(%s)', 1: '(u32)rev16_64(%s)', 2: 'bswap32(%s)', 4: 'clz32(%s)', 5: 'cls32(%s)'}.get(op)
    if not e: return None
    return (g.setX if sf else g.setW)('rd', e % a)


@ins('DP2', 'x 0 0 11010110 xxxxx xxxxxx xxxxx xxxxx', spec=('sf', 'dpop'))
def _(g):
    sf, op = g.v('sf'), g.v('dpop')
    a = g.X('rn') if sf else g.W('rn'); b = g.X('rm') if sf else g.W('rm')
    if sf and op == 12:
        # PACGA (ARMv8.3): a 32 bit code for Xn under the key modifier Xm|SP in the top half. Nothing checks it against
        # a real key, the game only compares codes it made itself, so any fixed mix of the two values does
        return g.setX('rd', '((((%s)*0x9E3779B97F4A7C15ull)^(((%s)<<29|(%s)>>35)*0xC2B2AE3D27D4EB4Full)^0x5bd1e995ull)&0xFFFFFFFF00000000ull)'
                      % (g.X('rn'), g.XS('rm'), g.XS('rm')))
    if sf and op in (0, 4, 5):
        # memory tagging (ARMv8.5): tags are always 0 here. SUBP subtracts the 56 bit addresses, IRG gives the pointer
        # with tag 0, GMI adds tag 0 to the exclusion mask
        if op == 0:
            return g.setX('rd', '(u64)(((i64)(%s<<8)>>8)-((i64)(%s<<8)>>8))' % (g.XS('rn'), g.XS('rm')))
        if op == 4:
            return g.setXS('rd', '%s&0xF0FFFFFFFFFFFFFFull' % g.XS('rn'))
        return g.setX('rd', '%s|1' % g.X('rm'))
    if sf:
        e = {2: 'udiv64(%s,%s)', 3: '(u64)sdiv64((i64)%s,(i64)%s)', 8: '%s<<(%s&63)', 9: '%s>>(%s&63)',
             10: '(u64)((i64)%s>>(%s&63))', 11: 'ror64(%s,(u32)%s)'}.get(op)
        if op in (19, 23):
            return g.setW('rd', 'swr_crc32(%s,%s,8,%d)' % (g.W('rn'), g.X('rm'), op >> 2 & 1))
    else:
        e = {2: 'udiv32(%s,%s)', 3: '(u32)sdiv32((i32)%s,(i32)%s)', 8: '(u32)%s<<(%s&31)', 9: '(u32)%s>>(%s&31)',
             10: '(u32)((i32)%s>>(%s&31))', 11: 'ror32(%s,%s)'}.get(op)
        if op in (16, 17, 18, 20, 21, 22):
            return g.setW('rd', 'swr_crc32(%s,%s,%d,%d)' % (a, b, 1 << (op & 3), op >> 2 & 1))
    if not e: return None
    return (g.setX if sf else g.setW)('rd', e % (a, b))


@ins('DP3', 'x 00 11011 xxx xxxxx x xxxxx xxxxx xxxxx', spec=('sf', 'op31', 'o0'))
def _(g):
    sf, op, o0 = g.v('sf'), g.v('op31'), g.v('o0')
    s = '-' if o0 else '+'
    if op == 0:
        if sf:
            ra = g.X('ra')
            if ra == '0' and not o0: return g.setX('rd', '%s*%s' % (g.X('rn'), g.X('rm')))
            return g.setX('rd', '%s%s%s*%s' % (ra, s, g.X('rn'), g.X('rm')))
        return g.setW('rd', '(u32)%s%s(u32)%s*(u32)%s' % (g.W('ra'), s, g.W('rn'), g.W('rm')))
    if not sf: return None
    if op == 1: return g.setX('rd', '%s%s(u64)((i64)(i32)%s*(i64)(i32)%s)' % (g.X('ra'), s, g.W('rn'), g.W('rm')))
    if op == 5: return g.setX('rd', '%s%s(u64)(u32)%s*(u64)(u32)%s' % (g.X('ra'), s, g.W('rn'), g.W('rm')))
    if op == 2 and not o0: return g.setX('rd', '(u64)smulh64((i64)%s,(i64)%s)' % (g.X('rn'), g.X('rm')))
    if op == 6 and not o0: return g.setX('rd', 'umulh64(%s,%s)' % (g.X('rn'), g.X('rm')))
    return None


# ------------------------------------------------------------------ scalar fp
def fsrc(g, reg, sz):
    return ('c->v[%s].df[0]' if sz else 'c->v[%s].f[0]') % g.f(reg)


def fset(g, reg, sz, e):
    return ('SETD(%s,%s);' if sz else 'SETS(%s,%s);') % (g.f(reg), e)


@ins('FP2', '0 0 0 11110 xx 1 xxxxx xxxx 10 xxxxx xxxxx', spec=('ftype', 'fop2'))
def _(g):
    ft, op = g.v('ftype'), g.v('fop2')
    if ft > 1 or op > 8: return None
    sz = ft
    a, b = fsrc(g, 'rn', sz), fsrc(g, 'rm', sz)
    T = 64 if sz else 32
    e = {0: '%s*%s', 1: '%s/%s', 2: '%s+%s', 3: '%s-%s', 4: 'fp_max%d(%%s,%%s)' % T, 5: 'fp_min%d(%%s,%%s)' % T,
         6: 'fp_maxnm%d(%%s,%%s)' % T, 7: 'fp_minnm%d(%%s,%%s)' % T, 8: 'FNEG%d(%%s*%%s)' % T}[op] % (a, b)
    return fset(g, 'rd', sz, e)


@ins('FP1', '0 0 0 11110 xx 1 xxxxxx 10000 xxxxx xxxxx', spec=('ftype', 'fop1'))
def _(g):
    ft, op = g.v('ftype'), g.v('fop1')
    n, d = g.f('rn'), g.f('rd')
    if ft == 3:          # from f16
        if op == 4: return 'SETS(%s,f16_to_f32(c->v[%s].h[0]));' % (d, n)
        if op == 5: return 'SETD(%s,(f64)f16_to_f32(c->v[%s].h[0]));' % (d, n)
        return None
    if ft > 1: return None
    sz = ft; a = fsrc(g, 'rn', sz)
    B = 'd[0]' if sz else 's[0]'
    if op == 0: return ('SETDB(%s,c->v[%s].d[0]);' if sz else 'SETSB(%s,c->v[%s].s[0]);') % (d, n)
    if op == 1: return ('SETDB(%s,c->v[%s].d[0]&0x7FFFFFFFFFFFFFFFull);' if sz else 'SETSB(%s,c->v[%s].s[0]&0x7FFFFFFFu);') % (d, n)
    if op == 2: return ('SETDB(%s,c->v[%s].d[0]^0x8000000000000000ull);' if sz else 'SETSB(%s,c->v[%s].s[0]^0x80000000u);') % (d, n)
    if op == 3: return fset(g, 'rd', sz, 'fp_sqrt%d(%s)' % (64 if sz else 32, a))
    if op == 4: return 'SETS(%s,(f32)%s);' % (d, a) if sz else None
    if op == 5: return 'SETD(%s,(f64)%s);' % (d, a) if not sz else None
    if op == 7: return 'SETH(%s,%s(%s));' % (d, 'f64_to_f16' if sz else 'f32_to_f16', a)
    if 8 <= op <= 15 and op != 13:
        rm = {8: '0', 9: '1', 10: '2', 11: '3', 12: '4', 14: 'FPRM', 15: 'FPRM'}[op]
        if sz: return fset(g, 'rd', 1, 'fp_round(%s,%s)' % (a, rm))
        return fset(g, 'rd', 0, 'fp_round32(%s,%s)' % (a, rm))
    return None


@ins('FCMP', '0 0 0 11110 xx 1 xxxxx 00 1000 xxxxx xx 000', spec=('ftype', 'fcmpop'))
def _(g):
    ft, op = g.v('ftype'), g.v('fcmpop')
    if ft > 1: return None
    a = fsrc(g, 'rn', ft)
    b = '0.0' if op & 1 else fsrc(g, 'rm', ft)
    return 'fcmp_(c,%s,%s);' % (a, b)


@ins('FCCMP', '0 0 0 11110 xx 1 xxxxx xxxx 01 xxxxx x xxxx', spec=('ftype',))
def _(g):
    ft = g.v('ftype')
    if ft > 1: return None
    return 'if(%s) fcmp_(c,%s,%s); else set_nzcv(c,%s);' % (cond_expr(g, 'cond'), fsrc(g, 'rn', ft), fsrc(g, 'rm', ft), g.f('nzcv'))


@ins('FCSEL', '0 0 0 11110 xx 1 xxxxx xxxx 11 xxxxx xxxxx', spec=('ftype',))
def _(g):
    ft = g.v('ftype')
    if ft > 1: return None
    if ft: return 'SETDB(%s,%s? c->v[%s].d[0] : c->v[%s].d[0]);' % (g.f('rd'), cond_expr(g, 'cond'), g.f('rn'), g.f('rm'))
    return 'SETSB(%s,%s? c->v[%s].s[0] : c->v[%s].s[0]);' % (g.f('rd'), cond_expr(g, 'cond'), g.f('rn'), g.f('rm'))


def vfp_imm(imm8, sz):
    s = imm8 >> 7; b6 = (imm8 >> 6) & 1; fr = imm8 & 15; e2 = (imm8 >> 4) & 3
    if sz:
        exp = ((b6 ^ 1) << 10) | ((0xFF if b6 else 0) << 2) | e2
        return (s << 63) | (exp << 52) | (fr << 48)
    exp = ((b6 ^ 1) << 7) | ((0x1F if b6 else 0) << 2) | e2
    return (s << 31) | (exp << 23) | (fr << 19)


@ins('FMOV_IMM', '0 0 0 11110 xx 1 xxxxxxxx 100 00000 xxxxx', spec=('ftype',))
def _(g):
    ft = g.v('ftype')
    if ft > 1: return None
    if g.static:
        v = vfp_imm(g.v('imm8'), ft)
        return ('SETDB(%s,%s);' if ft else 'SETSB(%s,%s);') % (g.f('rd'), lit(v))
    return ('SETDB(%s,vfp_imm64(%s));' if ft else 'SETSB(%s,vfp_imm32(%s));') % (g.f('rd'), g.f('imm8'))


@ins('FP3', '0 0 0 11111 xx x xxxxx x xxxxx xxxxx xxxxx', spec=('ftype', 'o1', 'o0'))
def _(g):
    ft, o1, o0 = g.v('ftype'), g.v('o1'), g.v('o0')
    if ft > 1: return None
    a, n, m = fsrc(g, 'ra', ft), fsrc(g, 'rn', ft), fsrc(g, 'rm', ft)
    T = 64 if ft else 32
    # FNEG32/64: the negation flips a NaN's sign as on the console (TCC's -x leaves it)
    if o1: a = 'FNEG%d(%s)' % (T, a)
    if o0 ^ o1: n = 'FNEG%d(%s)' % (T, n)
    return fset(g, 'rd', ft, 'fp_fma%d(%s,%s,%s)' % (T, n, m, a))


@ins('FCVT_INT', 'x 0 0 11110 xx 1 xx xxx 000000 xxxxx xxxxx', spec=('sf', 'ftype', 'rmode', 'fop'))
def _(g):
    sf, ft, rm, op = g.v('sf'), g.v('ftype'), g.v('rmode'), g.v('fop')
    n, d = g.f('rn'), g.f('rd')
    if op == 6 and rm == 0:          # FMOV gen <- fp
        if ft == 0 and not sf: return g.setX('rd', 'c->v[%s].s[0]' % n)
        if ft == 1 and sf: return g.setX('rd', 'c->v[%s].d[0]' % n)
        if ft == 3: return g.setX('rd', 'c->v[%s].h[0]' % n)
        return None
    if op == 7 and rm == 0:          # FMOV fp <- gen
        if ft == 0 and not sf: return 'SETSB(%s,%s);' % (d, g.W('rn'))
        if ft == 1 and sf: return 'SETDB(%s,%s);' % (d, g.X('rn'))
        if ft == 3: return 'SETHB(%s,%s);' % (d, g.W('rn'))
        return None
    if ft == 2 and sf and rm == 1:
        if op == 6: return g.setX('rd', 'c->v[%s].d[1]' % n)
        if op == 7: return 'c->v[%s].d[1]=%s;' % (d, g.X('rn'))
        return None
    if ft > 1: return None
    if op in (2, 3):
        if rm: return None
        src = (g.X('rn') if sf else g.W('rn'))
        if op == 2: src = '(i64)' + src if sf else '(i32)' + src
        return fset(g, 'rd', ft, '(%s)%s' % ('f64' if ft else 'f32', src))
    if op in (0, 1, 4, 5):
        if op in (4, 5):
            if rm: return None
            mode = '4'
        else: mode = str([0, 1, 2, 3][rm])
        a = fsrc(g, 'rn', ft)
        uns = op & 1
        if mode == '3':
            fn = ('fcvtzu64' if uns else 'fcvtzs64') if sf else ('fcvtzu32' if uns else 'fcvtzs32')
            e = '%s(%s)' % (fn, a)
        else:
            fn = ('fcvt_u64' if uns else 'fcvt_s64') if sf else ('fcvt_u32' if uns else 'fcvt_s32')
            e = '%s(%s,%s)' % (fn, a, mode)
        return (g.setX if sf else g.setW)('rd', '(u64)%s' % e if sf else '(u32)%s' % e)
    return None


@ins('FCVT_FIX', 'x 0 0 11110 xx 0 xx xxx xxxxxx xxxxx xxxxx', spec=('sf', 'ftype', 'rmode', 'fop'))
def _(g):
    sf, ft, rm, op = g.v('sf'), g.v('ftype'), g.v('rmode'), g.v('fop')
    if ft > 1: return None
    fb = '(64-%s)' % g.f('scale')
    if g.static:
        sc = g.v('scale')
        if not sf and sc < 32: return None
        fb = str(64 - sc)
    scale = 'fp_pow2(%s)' % fb
    if g.static: scale = repr(float(2 ** (64 - g.v('scale'))))
    if rm == 3 and op in (0, 1):
        a = fsrc(g, 'rn', ft)
        fn = ('fcvtzu64' if op else 'fcvtzs64') if sf else ('fcvtzu32' if op else 'fcvtzs32')
        e = '%s((f64)%s*%s)' % (fn, a, scale)
        return (g.setX if sf else g.setW)('rd', e)
    if rm == 0 and op in (2, 3):
        src = (g.X('rn') if sf else g.W('rn'))
        if op == 2: src = '(i64)' + src if sf else '(i32)' + src
        return fset(g, 'rd', ft, '(%s)((f64)%s/%s)' % ('f64' if ft else 'f32', src, scale))
    return None


# ------------------------------------------------------------------ AdvSIMD
def simd_fallback(g):
    if g.static: return 'if(!swr_simd(c,M,%s)) UNDEF();' % lit(g.w)
    return 'if(!swr_simd(c,M,w)) UNDEF();'


# FABS / FNEG on half-precision lanes (ARMv8.2 FP16, Switch 2 code): only the sign bit changes, NaNs included
@ins('FP16_ABSNEG', '0 x x 01110 1 1111 00 01111 10 xxxxx xxxxx', spec=('Q', 'S'))
def _(g):
    op = '^=0x8000' if g.v('S') else '&=0x7FFF'
    clear = '' if g.v('Q') else ' r_.d[1]=0;'
    return '{ V128 r_=c->v[%s]; for(int i_=0;i_<%d;i_++) r_.h[i_]%s;%s c->v[%s]=r_; }' % (
        g.f('rn'), 8 if g.v('Q') else 4, op, clear, g.f('rd'))


# structure ld/st and the whole "data processing - SIMD" group
def fast_ld1(g):
    """LD1/ST1 (multiple structures, 1-4 registers), offset and post-index: contiguous bytes, so 64 bit moves
    (little endian: the element size doesn't change the layout). Orbitals' hottest loops use the 2 register form"""
    w = g.w
    Q = (w >> 30) & 1; L = (w >> 22) & 1; post = (w >> 23) & 1
    rm, rn, rt = (w >> 16) & 31, (w >> 5) & 31, w & 31
    rpt = {7: 1, 10: 2, 6: 3, 2: 4}.get((w >> 12) & 15)
    if rpt is None or (w >> 24) & 1: return None
    nb = 16 if Q else 8
    s = '{ u64 a_=c->x[%d]; ' % rn
    for r in range(rpt):
        t = (rt + r) & 31; off = r * nb
        if L:
            s += 'c->v[%d].d[0]=RD64(a_+%d); c->v[%d].d[1]=%s; ' % (t, off, t, 'RD64(a_+%d)' % (off + 8) if Q else '0')
        else:
            s += 'WR64(a_+%d,c->v[%d].d[0]); ' % (off, t)
            if Q: s += 'WR64(a_+%d,c->v[%d].d[1]); ' % (off + 8, t)
    if post:
        s += 'c->x[%d]=a_+%s; ' % (rn, str(rpt * nb) if rm == 31 else 'c->x[%d]' % rm)
    return s + '}'


@ins('SIMD_LDST', '0 x 0011 0 0x x xxxxxx xxxx xx xxxxx xxxxx')
def _(g):
    if g.static:
        f = fast_ld1(g)
        if f: return f
    return simd_fallback(g)


def fast_ld1_lane(g):
    """LD1/ST1 (single structure, one register) to or from one lane, and LD1R, offset and post-index. Bink 2's decoder
    (Orbitals' cutscenes) loads its coefficients and pixels a lane at a time: 552 of the 724 swr_simd calls of its hottest
    function. The other lanes keep their values (LD1R: all lanes, the top half cleared for a 64 bit register)"""
    w = g.w
    Q = (w >> 30) & 1; post = (w >> 23) & 1; L = (w >> 22) & 1; R = (w >> 21) & 1
    rm, rn, rt = (w >> 16) & 31, (w >> 5) & 31, w & 31
    opc = (w >> 13) & 7; S = (w >> 12) & 1; size = (w >> 10) & 3
    if R or (opc & 1) or (not post and rm): return None
    if opc == 6:                                         # LD1R
        if not L or S: return None
        eb = 8 << size; n = (128 if Q else 64) // eb
        s = '{ u64 a_=c->x[%d]; %s e_=RD%d(a_); V128 r_; r_.d[1]=0; ' % (rn, _UC[eb], eb)
        for i in range(n): s += 'r_.%s[%d]=e_; ' % (_UT[eb], i)
        s += 'c->v[%d]=r_; ' % rt
    else:
        if opc == 0: eb = 8; idx = (Q << 3) | (S << 2) | size
        elif opc == 2:
            if size & 1: return None
            eb = 16; idx = (Q << 2) | (S << 1) | (size >> 1)
        elif size == 0: eb = 32; idx = (Q << 1) | S
        elif size == 1 and not S: eb = 64; idx = Q
        else: return None
        if L: s = '{ u64 a_=c->x[%d]; c->v[%d].%s[%d]=RD%d(a_); ' % (rn, rt, _UT[eb], idx, eb)
        else: s = '{ u64 a_=c->x[%d]; WR%d(a_,c->v[%d].%s[%d]); ' % (rn, eb, rt, _UT[eb], idx)
    if post:
        s += 'c->x[%d]=a_+%s; ' % (rn, str(eb // 8) if rm == 31 else 'c->x[%d]' % rm)   # one element's bytes
    return s + '}'


@ins('SIMD_LDST1', '0 x 0011 0 1x x xxxxxx xxxx xx xxxxx xxxxx')
def _(g):
    if g.static and _NO_INLINE_SIMD != '1':
        f = fast_ld1_lane(g)
        if f: return f
    return simd_fallback(g)


_UT = {8: 'b', 16: 'h', 32: 's', 64: 'd'}
_ST = {8: 'sb', 16: 'sh', 32: 'ss', 64: 'sd'}
_UC = {8: 'u8', 16: 'u16', 32: 'u32', 64: 'u64'}
_QC = 'c->fpsr|=1u<<27;'


def fast_simd_int(g):
    """integer AdvSIMD the Bink 2 decoder lives on (Orbitals' cutscenes): shifts by immediate, long/wide arithmetic,
    saturating narrows, halving adds, min/max/absolute difference and compares. Same formulas as cpu_helpers.c
    (simd_shimm, simd_3diff, simd_2misc, simd_3same), checked by tests/a64/simd_inline_diff.py"""
    w = g.w
    Q = (w >> 30) & 1; U = (w >> 29) & 1
    rd, rn, rm = w & 31, (w >> 5) & 31, (w >> 16) & 31
    # ---- modified immediate: MOVI / MVNI / ORR / BIC (8, 16, 32 bit lanes, shifted or MSL; MOVI 64 bit). FMOV stays in swr_simd
    if (w & 0x9FF80400) == 0x0F000400:
        op = U; cmode = (w >> 12) & 15; o2 = (w >> 11) & 1
        imm8 = (((w >> 16) & 7) << 5) | ((w >> 5) & 31)
        if o2: return None
        if cmode == 15:                                  # FMOV (vector, immediate): a constant, the bits of VFPExpandImm
            a_, b_, cd, efgh = (imm8 >> 7) & 1, (imm8 >> 6) & 1, (imm8 >> 4) & 3, imm8 & 15
            if not op:
                f32 = (a_ << 31) | ((b_ ^ 1) << 30) | ((0x1F if b_ else 0) << 25) | (cd << 23) | (efgh << 19); imm64 = f32 | (f32 << 32)
            elif Q: imm64 = (a_ << 63) | ((b_ ^ 1) << 62) | ((0xFF if b_ else 0) << 54) | (cd << 52) | (efgh << 48)
            else: return None
            return 'c->v[%d].d[0]=0x%016xull; c->v[%d].d[1]=%s;' % (rd, imm64, rd, ('0x%016xull' % imm64) if Q else '0')
        k = cmode >> 1
        if k <= 3: imm = imm8 << (8 * k); imm64 = imm | (imm << 32)
        elif k <= 5: imm = imm8 << (8 * (k - 4)); imm64 = imm * 0x0001000100010001
        elif k == 6:
            imm = ((imm8 << 8) | 0xFF) if not (cmode & 1) else ((imm8 << 16) | 0xFFFF); imm64 = imm | (imm << 32)
        elif op == 0: imm64 = imm8 * 0x0101010101010101
        else:
            if not Q and False: pass
            imm64 = 0
            for b in range(8):
                if (imm8 >> b) & 1: imm64 |= 0xFF << (8 * b)
        logic = cmode < 12 and (cmode & 1)              # ORR / BIC (cmode 0xx1, 10x1)
        if logic:
            if op: return '{ V128 r_=c->v[%d]; r_.d[0]&=0x%016xull; r_.d[1]=%s; c->v[%d]=r_; }' % (rd, ~imm64 & (2**64 - 1), ('r_.d[1]&0x%016xull' % (~imm64 & (2**64 - 1))) if Q else '0', rd)
            return '{ V128 r_=c->v[%d]; r_.d[0]|=0x%016xull; r_.d[1]=%s; c->v[%d]=r_; }' % (rd, imm64, ('r_.d[1]|0x%016xull' % imm64) if Q else '0', rd)
        if op and cmode != 14: imm64 = ~imm64 & (2**64 - 1)   # MVNI
        return 'c->v[%d].d[0]=0x%016xull; c->v[%d].d[1]=%s;' % (rd, imm64, rd, ('0x%016xull' % imm64) if Q else '0')
    # ---- integer MLA / MLS / MUL by element (16 and 32 bit lanes): Bink 2's inverse transform (the rest of its hottest function's swr_simd calls)
    if (w & 0x9F000400) == 0x0F000000:
        size = (w >> 22) & 3; op = (w >> 12) & 15
        if (U, op) in ((1, 0), (1, 4), (0, 8)) and size in (1, 2):
            L = (w >> 21) & 1; M = (w >> 20) & 1; H = (w >> 11) & 1
            if size == 1: idx = (H << 2) | (L << 1) | M; rmv = (w >> 16) & 15
            else: idx = (H << 1) | L; rmv = (w >> 16) & 31
            eb = 8 << size; T = _UT[eb]; n = (128 if Q else 64) // eb
            s = '{ V128 a=c->v[%d], z=c->v[%d], r; r.d[1]=0; u32 e_=c->v[%d].%s[%d]; ' % (rn, rd, rmv, T, idx)
            for i in range(n):
                p = '((u32)a.%s[%d]*e_)' % (T, i)
                e = {8: p, 0: '((u32)z.%s[%d]+%s)' % (T, i, p), 4: '((u32)z.%s[%d]-%s)' % (T, i, p)}[op]
                s += 'r.%s[%d]=(%s)%s; ' % (T, i, _UC[eb], e)
            return s + 'c->v[%d]=r; }' % rd
    # ---- across lanes: ADDV, (S|U)ADDLV, (S|U)MAXV, (S|U)MINV; the scalar result zero-extended into rd
    if (w & 0x9F3E0C00) == 0x0E300800 and ((w >> 12) & 31) in (0x03, 0x0A, 0x1A, 0x1B):
        size = (w >> 22) & 3; op = (w >> 12) & 31
        if size == 3 or (size == 2 and not Q) or (op == 0x1B and U): return None
        eb = 8 << size; n = (128 if Q else 64) // eb
        x = ['(%s)a.%s[%d]' % ('u64' if U else 'i64', _UT[eb] if U else _ST[eb], i) for i in range(n)]
        s = '{ V128 a=c->v[%d]; %s r_=%s; ' % (rn, 'u64' if U else 'i64', x[0])
        for e in x[1:]:
            if op in (0x03, 0x1B): s += 'r_+=%s; ' % e
            elif op == 0x0A: s += 'if(%s>r_) r_=%s; ' % (e, e)
            else: s += 'if(%s<r_) r_=%s; ' % (e, e)
        ob = eb * 2 if op == 0x03 else eb
        return s + 'c->v[%d].d[0]=(u64)r_&0x%xull; c->v[%d].d[1]=0; }' % (rd, (1 << ob) - 1, rd)
    # ---- BSL / BIT / BIF (bitwise selects; AND ORR EOR... are in fast_simd's logical template)
    if (w & 0xBF20FC00) == 0x2E201C00 and (w >> 22) & 3:
        sel = (w >> 22) & 3
        e = {1: 'm_^((m_^n_)&d_)', 2: 'd_^((d_^n_)&m_)', 3: 'd_^((d_^n_)&~m_)'}[sel]
        s = '{ '
        for k in range(2 if Q else 1):
            s += '{ u64 d_=c->v[%d].d[%d], n_=c->v[%d].d[%d], m_=c->v[%d].d[%d]; c->v[%d].d[%d]=%s; } ' % (rd, k, rn, k, rm, k, rd, k, e)
        if not Q: s += 'c->v[%d].d[1]=0; ' % rd
        return s + '}'
    # ---- SQDMULH / SQRDMULH (vector, 16 and 32 bit lanes): the doubled product's high half, saturated (QC)
    if (w & 0x9F20FC00) == 0x0E20B400 and (w >> 22) & 3 in (1, 2):
        size = (w >> 22) & 3
        if size == 1:
            return 'v_qdmulh16(c,%d,%d,%d,%d,%d);' % (rd, rn, rm, Q, U)
        eb = 32; T = _ST[eb]; n = (128 if Q else 64) // eb; mx = (1 << (eb - 1)) - 1
        s = '{ V128 a=c->v[%d], b=c->v[%d], r; r.d[1]=0; ' % (rn, rm)
        for i in range(n):
            # (2ab + r) >> eb as (ab + r/2) >> (eb-1): 2ab overflows i64 for two 32 bit -2^31
            s += '{ i64 p_=((i64)a.%s[%d]*(i64)b.%s[%d]%s)>>%d; if(p_>%d){ %s p_=%d; } r.%s[%d]=(%s)p_; } ' % (
                T, i, T, i, '+%dll' % (1 << (eb - 2)) if U else '', eb - 1, mx, _QC, mx, _UT[eb], i, _UC[eb])
        return s + 'c->v[%d]=r; }' % rd
    # ---- SADDLP / UADDLP (pairs added into lanes twice as wide), SHLL (2) (shift left long by the lane size)
    if (w & 0x9F3E0C00) == 0x0E200800 and ((w >> 12) & 31) in (0x02, 0x13):
        size = (w >> 22) & 3; op = (w >> 12) & 31
        if size == 3: return None
        eb = 8 << size; wb = eb * 2
        if op == 0x02:
            n = (128 if Q else 64) // wb
            s = '{ V128 a=c->v[%d], r; r.d[1]=0; ' % rn
            for i in range(n):
                if U: x, y = '(u64)a.%s[%d]' % (_UT[eb], 2 * i), '(u64)a.%s[%d]' % (_UT[eb], 2 * i + 1)
                else: x, y = '(i64)a.%s[%d]' % (_ST[eb], 2 * i), '(i64)a.%s[%d]' % (_ST[eb], 2 * i + 1)
                s += 'r.%s[%d]=(%s)(u64)(%s+%s); ' % (_UT[wb], i, _UC[wb], x, y)
            return s + 'c->v[%d]=r; }' % rd
        if U:                                            # SHLL / SHLL2
            m = 64 // eb; off = m if Q else 0
            s = '{ V128 a=c->v[%d], r; ' % rn
            for i in range(m): s += 'r.%s[%d]=(%s)((u64)a.%s[%d]<<%d); ' % (_UT[wb], i, _UC[wb], _UT[eb], i + off, eb)
            return s + 'c->v[%d]=r; }' % rd
        return None
    # ---- shift by immediate, vector
    if (w & 0x9F800400) == 0x0F000400 and (w >> 19) & 15:
        immh = (w >> 19) & 15; immb = (w >> 16) & 7; op = (w >> 11) & 31
        size = 3
        while not (immh >> size) & 1: size -= 1
        eb = 8 << size; imm = (immh << 3) | immb; shr = 2 * eb - imm; shl = imm - eb
        if op == 0x14:                                    # SSHLL/USHLL(2)
            if size == 3: return None
            m = 64 // eb; off = m if Q else 0; wb = eb * 2
            s = '{ V128 a=c->v[%d], r; ' % rn
            for i in range(m):
                src = '(u64)a.%s[%d]' % (_UT[eb], i + off) if U else '(u64)((i64)a.%s[%d])' % (_ST[eb], i + off)
                s += 'r.%s[%d]=(%s)(%s<<%d); ' % (_UT[wb], i, _UC[wb], src, shl)
            return s + 'c->v[%d]=r; }' % rd
        if 0x10 <= op <= 0x13:                           # SHRN RSHRN SQ(R)SHRUN SQ(R)SHRN UQ(R)SHRN (2)
            if size == 3: return None
            wb = eb * 2; m = 64 // eb; off = m if Q else 0; rnd = op & 1; T = _UT[eb]
            s = '{ V128 a=c->v[%d], o; ' % rn + ('o=c->v[%d]; ' % rd if Q else 'o.d[0]=0; ')
            mx = (1 << eb) - 1; smax = (1 << (eb - 1)) - 1; smin = -(1 << (eb - 1))
            for i in range(m):
                xu = '(u64)a.%s[%d]' % (_UT[wb], i); xs = '(i64)a.%s[%d]' % (_ST[wb], i)
                if op == 0x10 and not U: e = 'o.%s[%d]=(%s)(%s>>%d); ' % (T, i + off, _UC[eb], xu, shr)
                elif op == 0x11 and not U: e = 'o.%s[%d]=(%s)((%s+%du)>>%d); ' % (T, i + off, _UC[eb], xu, 1 << (shr - 1), shr)
                elif U and op >= 0x12:                     # UQSHRN / UQRSHRN
                    v = '(%s>>%d)' % (xu, shr) + ('+((%s>>%d)&1)' % (xu, shr - 1) if rnd else '')
                    e = '{ u64 v_=%s; if(v_>%du){ %s v_=%du; } o.%s[%d]=(%s)v_; } ' % (v, mx, _QC, mx, T, i + off, _UC[eb])
                else:                                      # SQSHRUN/SQRSHRUN (U) or SQSHRN/SQRSHRN
                    v = '(%s>>%d)' % (xs, shr) + ('+((%s>>%d)&1)' % (xs, shr - 1) if rnd else '')
                    lo, hi = (0, mx) if U else (smin, smax)
                    e = '{ i64 v_=%s; if(v_<(%d)){ %s v_=(%d); } else if(v_>(%d)){ %s v_=(%d); } o.%s[%d]=(%s)v_; } ' % (
                        v, lo, _QC, lo, hi, _QC, hi, T, i + off, _UC[eb])
                s += e
            if not Q: s += 'o.d[1]=0; '
            return s + 'c->v[%d]=o; }' % rd
        if U and op in (0x08, 0x0A):                      # SRI / SLI: the shifted value over the bits it covers, the rest of rd kept
            if size == 3 and not Q: return None
            n = (128 if Q else 64) // eb; T = _UT[eb]; full = (1 << eb) - 1
            s = '{ V128 a=c->v[%d], z=c->v[%d], r; r.d[1]=0; ' % (rn, rd)
            for i in range(n):
                if op == 0x0A: m = (full << shl) & full; v = '(((u64)a.%s[%d]<<%d)&0x%xull)' % (T, i, shl, m)
                elif shr < eb: m = full >> shr; v = '(((u64)a.%s[%d]>>%d)&0x%xull)' % (T, i, shr, m)
                else: m = 0; v = '0'
                s += 'r.%s[%d]=(%s)(%s|((u64)z.%s[%d]&0x%xull)); ' % (T, i, _UC[eb], v, T, i, ~m & full)
            return s + 'c->v[%d]=r; }' % rd
        if op in (0x00, 0x02, 0x04, 0x06, 0x0A):
            if size == 3 and not Q: return None
            if op == 0x0A and U: return None              # SLI
            n = (128 if Q else 64) // eb; T = _UT[eb]
            acc = op in (0x02, 0x06); rnd = (op >> 2) & 1
            s = '{ V128 a=c->v[%d], z=c->v[%d], r; r.d[1]=0; ' % (rn, rd)
            for i in range(n):
                if op == 0x0A:
                    v = '((u64)a.%s[%d]<<%d)' % (T, i, shl)
                elif U:
                    u = '(u64)a.%s[%d]' % (T, i)
                    if shr >= 64: v = ('(%s>>63)' % u) if rnd else '0'
                    else: v = '((%s>>%d)%s)' % (u, shr, ('+((%s>>%d)&1)' % (u, shr - 1)) if rnd else '')
                else:
                    sv = '(i64)a.%s[%d]' % (_ST[eb], i)
                    if shr >= 64: v = '0' if rnd else '(u64)((%s)<0?-1:0)' % sv
                    else: v = '(u64)((%s>>%d)%s)' % (sv, shr, ('+((%s>>%d)&1)' % (sv, shr - 1)) if rnd else '')
                if acc: v = '((u64)z.%s[%d]+%s)' % (T, i, v)
                s += 'r.%s[%d]=(%s)(%s); ' % (T, i, _UC[eb], v)
            return s + 'c->v[%d]=r; }' % rd
        return None
    # ---- three different: (S|U)ADDL/ADDW/SUBL/SUBW/ABAL/ABDL/MLAL/MLSL/MULL (2)
    if (w & 0x9F200C00) == 0x0E200000:
        size = (w >> 22) & 3; op = (w >> 12) & 15
        if size == 3 or op not in (0, 1, 2, 3, 5, 7, 8, 10, 12): return None
        eb = 8 << size; wb = eb * 2; m = 64 // eb; off = m if Q else 0
        s = '{ V128 a=c->v[%d], b=c->v[%d], d=c->v[%d], r; ' % (rn, rm, rd)
        for i in range(m):
            if U:
                xa = ('(u64)a.%s[%d]' % (_UT[wb], i)) if op in (1, 3) else ('(u64)a.%s[%d]' % (_UT[eb], i + off))
                xb = '(u64)b.%s[%d]' % (_UT[eb], i + off)
            else:
                xa = ('(i64)a.%s[%d]' % (_ST[wb], i)) if op in (1, 3) else ('(i64)a.%s[%d]' % (_ST[eb], i + off))
                xb = '(i64)b.%s[%d]' % (_ST[eb], i + off)
            z = '(u64)d.%s[%d]' % (_UT[wb], i)
            ad = '(%s>%s?%s-%s:%s-%s)' % (xa, xb, xa, xb, xb, xa)
            e = {0: '%s+%s' % (xa, xb), 1: '%s+%s' % (xa, xb), 2: '%s-%s' % (xa, xb), 3: '%s-%s' % (xa, xb),
                 5: '%s+(u64)%s' % (z, ad), 7: '(u64)%s' % ad, 8: '%s+(u64)(%s*%s)' % (z, xa, xb),
                 10: '%s-(u64)(%s*%s)' % (z, xa, xb), 12: '%s*%s' % (xa, xb)}[op]
            s += 'r.%s[%d]=(%s)(u64)(%s); ' % (_UT[wb], i, _UC[wb], e)
        return s + 'c->v[%d]=r; }' % rd
    # ---- two-register misc: XTN SQXTUN SQXTN UQXTN (2)
    if (w & 0x9F3E0C00) == 0x0E200800:
        size = (w >> 22) & 3; op = (w >> 12) & 31
        if op not in (0x12, 0x14) or size == 3: return None
        eb = 8 << size; wb = eb * 2; m = 64 // eb; off = m if Q else 0; T = _UT[eb]
        mx = (1 << eb) - 1; smax = (1 << (eb - 1)) - 1; smin = -(1 << (eb - 1))
        s = '{ V128 a=c->v[%d], o; ' % rn + ('o=c->v[%d]; ' % rd if Q else 'o.d[0]=0; ')
        for i in range(m):
            xu = '(u64)a.%s[%d]' % (_UT[wb], i); xs = '(i64)a.%s[%d]' % (_ST[wb], i)
            if op == 0x12 and not U: e = 'o.%s[%d]=(%s)%s; ' % (T, i + off, _UC[eb], xu)
            elif op == 0x14 and U:
                e = '{ u64 v_=%s; if(v_>%du){ %s v_=%du; } o.%s[%d]=(%s)v_; } ' % (xu, mx, _QC, mx, T, i + off, _UC[eb])
            else:
                lo, hi = (0, mx) if op == 0x12 else (smin, smax)
                e = '{ i64 v_=%s; if(v_<(%d)){ %s v_=(%d); } else if(v_>(%d)){ %s v_=(%d); } o.%s[%d]=(%s)v_; } ' % (
                    xs, lo, _QC, lo, hi, _QC, hi, T, i + off, _UC[eb])
            s += e
        if not Q: s += 'o.d[1]=0; '
        return s + 'c->v[%d]=o; }' % rd
    # ---- three same integer: halving adds, compares, max/min, absolute difference
    if (w & 0x9F200400) == 0x0E200400:
        size = (w >> 22) & 3; op = (w >> 11) & 31
        if op not in (0x00, 0x02, 0x06, 0x07, 0x0C, 0x0D, 0x0E, 0x0F, 0x11): return None
        if size == 3 and (op != 0x11 and op not in (0x06, 0x07) or not Q): return None
        eb = 8 << size; n = (128 if Q else 64) // eb; T = _UT[eb]
        s = '{ V128 a=c->v[%d], b=c->v[%d], z=c->v[%d], r; r.d[1]=0; ' % (rn, rm, rd)
        for i in range(n):
            if U: x, y = '(u64)a.%s[%d]' % (T, i), '(u64)b.%s[%d]' % (T, i)
            else: x, y = '(i64)a.%s[%d]' % (_ST[eb], i), '(i64)b.%s[%d]' % (_ST[eb], i)
            ad = '(%s>%s?%s-%s:%s-%s)' % (x, y, x, y, y, x)
            e = {0x00: '(u64)((%s+%s)>>1)' % (x, y), 0x02: '(u64)((%s+%s+1)>>1)' % (x, y),
                 0x06: '(%s>%s)?~0ull:0' % (x, y), 0x07: '(%s>=%s)?~0ull:0' % (x, y),
                 0x0C: '(u64)(%s>%s?%s:%s)' % (x, y, x, y), 0x0D: '(u64)(%s<%s?%s:%s)' % (x, y, x, y),
                 0x0E: '(u64)%s' % ad, 0x0F: '(u64)z.%s[%d]+(u64)%s' % (T, i, ad),
                 0x11: ('(%s==%s)?~0ull:0' % (x, y)) if U else '((u64)a.%s[%d]&(u64)b.%s[%d])?~0ull:0' % (T, i, T, i)}[op]
            s += 'r.%s[%d]=(%s)(%s); ' % (T, i, _UC[eb], e)
        return s + 'c->v[%d]=r; }' % rd
    return None


def fp_2misc(w, Q, U, size, op, rn, rd):
    """two-register misc on single / double lanes, as swr_simd's simd_2misc does them, lane by lane with the same functions (cpu_helpers.c
    swr_fcvt_* / swr_frecpe_32 / swr_fcmz_*, fcvt_*, fp_recpe64...) and the same casts: FCVT{N,M,A,P,Z}{S,U}, SCVTF, UCVTF, FRECPE,
    FRSQRTE, FCVTL(2), FCVTN(2) from double, FCM{GT,EQ,LT,GE,LE} #0. The co-op profile's hottest swr_simd calls (Unreal's vector maths)"""
    hi = size >> 1; sz = size & 1
    lanes = 2 if sz else (4 if Q else 2); T = 'df' if sz else 'f'; I = 'd' if sz else 's'; W = '64' if sz else '32'
    tail = '' if Q else 'r.d[1]=0; '
    if 0x0C <= op <= 0x0E and hi:
        if sz and not Q: return None
        k = {0x0C: 1 if U else 2, 0x0D: 5 if U else 0, 0x0E: -1 if U else 6}[op]
        if k < 0: return None
        s = '{ V128 a=c->v[%d], r; ' % rn
        for i in range(lanes): s += 'r.%s[%d]=swr_fcmz_%s(%d,a.%s[%d]); ' % (I, i, W, k, T, i)
        return s + tail + 'c->v[%d]=r; }' % rd
    if op == 0x16 and not hi and not U and sz:    # FCVTN / FCVTN2 (double to single): the other half kept for FCVTN2
        off = 2 if Q else 0
        s = '{ V128 a=c->v[%d], r=%s; ' % (rn, 'c->v[%d]' % rd if Q else '{0}')
        for i in range(2): s += 'r.f[%d]=(f32)a.df[%d]; ' % (i + off, i)
        return s + ('' if Q else 'r.d[1]=0; ') + 'c->v[%d]=r; }' % rd
    if op == 0x17 and not hi and not U and sz:    # FCVTL / FCVTL2 (single to double)
        off = 2 if Q else 0
        s = '{ V128 a=c->v[%d], r; ' % rn
        for i in range(2): s += 'r.df[%d]=(f64)a.f[%d]; ' % (i, i + off)
        return s + 'c->v[%d]=r; }' % rd
    if op < 0x18 or (sz and not Q): return None
    k = (U << 6) | (hi << 5) | op
    s = '{ V128 a=c->v[%d], r; ' % rn
    if k in (0x1A, 0x3A, 0x1B, 0x3B, 0x1C, 0x5A, 0x7A, 0x5B, 0x7B, 0x5C):
        rm = 4 if op == 0x1C else ((1 if hi else 0) if op == 0x1A else (3 if hi else 2))
        for i in range(lanes): s += 'r.%s[%d]=swr_fcvt_%s(a.%s[%d],%d,%d); ' % (I, i, W, T, i, rm, U)
    elif k == 0x1D:   # SCVTF
        for i in range(lanes): s += ('r.df[%d]=(f64)(i64)a.d[%d]; ' if sz else 'r.f[%d]=(f32)(i32)a.s[%d]; ') % (i, i)
    elif k == 0x5D:   # UCVTF
        for i in range(lanes): s += ('r.df[%d]=(f64)a.d[%d]; ' if sz else 'r.f[%d]=(f32)a.s[%d]; ') % (i, i)
    elif k == 0x3D:   # FRECPE
        for i in range(lanes): s += ('r.df[%d]=fp_recpe64(a.df[%d]); ' if sz else 'r.f[%d]=swr_frecpe_32(a.f[%d]); ') % (i, i)
    elif k == 0x7D:   # FRSQRTE
        for i in range(lanes): s += ('r.df[%d]=fp_rsqrte64(a.df[%d]); ' if sz else 'r.f[%d]=swr_frsqrte_32(a.f[%d]); ') % (i, i)
    else: return None
    return s + tail + 'c->v[%d]=r; }' % rd


def fast_simd(g):
    """inline templates for the most used AdvSIMD instructions (static mode only)"""
    f = fast_simd_int(g)
    if f: return f
    w = g.w
    Q = (w >> 30) & 1; U = (w >> 29) & 1; size = (w >> 22) & 3
    rd, rn, rm = w & 31, (w >> 5) & 31, (w >> 16) & 31
    LT = {8: 'b', 16: 'h', 32: 's', 64: 'd'}
    # UZP1/UZP2/TRN1/TRN2/ZIP1/ZIP2 (the profile's hottest swr_simd calls in co-op gameplay: ZIP1/ZIP2 .8H)
    if (w & 0xBF208C00) == 0x0E000800:
        op = (w >> 12) & 7
        if op in (0, 4) or (size == 3 and not Q): return None
        eb = 8 << size; n = (128 if Q else 64) // eb; T = LT[eb]; part = op >> 2; kind = op & 3
        s = '{ V128 a=c->v[%d], b=c->v[%d], r; r.d[1]=0; ' % (rn, rm)
        for i in range(n):
            if kind == 3:     # ZIP
                e = '%s.%s[%d]' % ('a' if i % 2 == 0 else 'b', T, i // 2 + (n // 2 if part else 0))
            elif kind == 1:   # UZP
                k = 2 * i + part; e = ('a.%s[%d]' % (T, k)) if k < n else ('b.%s[%d]' % (T, k - n))
            else:             # TRN
                e = '%s.%s[%d]' % ('a' if i % 2 == 0 else 'b', T, (i // 2) * 2 + part)
            s += 'r.%s[%d]=%s; ' % (T, i, e)
        return s + 'c->v[%d]=r; }' % rd
    # EXT
    if (w & 0xBFE08400) == 0x2E000000:
        imm4 = (w >> 11) & 15
        if not Q and imm4 & 8: return None
        nb = 16 if Q else 8
        return ('{ u8 t_[32]; memcpy(t_,&c->v[%d],16); memcpy(t_+%d,&c->v[%d],16); V128 r; r.d[1]=0; memcpy(&r,t_+%d,%d); '
                'c->v[%d]=r; }') % (rn, nb, rm, imm4, nb, rd)
    # two-register misc, vector: FABS/FNEG (sign bit only, NaNs included, as FPAbs/FPNeg), NOT, REV64
    if (w & 0x9F3E0C00) == 0x0E200800:
        op = (w >> 12) & 31
        if op == 0x0F and size >= 2:
            sz = size & 1
            if sz and not Q: return None
            m = '0x8000000000000000ull' if sz else '0x8000000080000000ull'
            e = ('%s^' + m) if U else ('%s&~' + m)
            return '{ u64 a0=c->v[%d].d[0], a1=c->v[%d].d[1]; c->v[%d].d[0]=%s; c->v[%d].d[1]=%s; }' % (
                rn, rn, rd, e % 'a0', rd, (e % 'a1') if Q else '0')
        if op == 0x05 and U and size == 0:
            return '{ u64 a0=c->v[%d].d[0], a1=c->v[%d].d[1]; c->v[%d].d[0]=~a0; c->v[%d].d[1]=%s; }' % (rn, rn, rd, rd, '~a1' if Q else '0')
        if op == 0x00 and not U and size < 3:
            eb = 8 << size; per = 64 // eb; n = (128 if Q else 64) // eb; T = LT[eb]
            s = '{ V128 a=c->v[%d], r; r.d[1]=0; ' % rn
            for i in range(n):
                base = (i // per) * per
                s += 'r.%s[%d]=a.%s[%d]; ' % (T, i, T, base + per - 1 - (i - base))
            return s + 'c->v[%d]=r; }' % rd
        f = fp_2misc(w, Q, U, size, op, rn, rd)
        if f: return f
        return None
    # three same, vector
    if (w & 0x9F200400) == 0x0E200400:
        op = (w >> 11) & 31
        if op == 0x13 and not U and size < 3:   # MUL (vector)
            eb = 8 << size; n = (128 if Q else 64) // eb; T = LT[eb]; ct = {8: 'u8', 16: 'u16', 32: 'u32'}[eb]
            s = '{ V128 a=c->v[%d], b=c->v[%d], r; r.d[1]=0; ' % (rn, rm)
            for i in range(n): s += 'r.%s[%d]=(%s)((u32)a.%s[%d]*(u32)b.%s[%d]); ' % (T, i, ct, T, i, T, i)
            return s + 'c->v[%d]=r; }' % rd
        if op == 0x1C:   # FCMEQ / FCMGE / FCMGT (register): IEEE compares, NaN gives 0
            sz = size & 1; hi = size >> 1
            cmpop = {(0, 0): '==', (1, 0): '>=', (1, 1): '>'}.get((U, hi))
            if cmpop is None or (sz and not Q): return None
            lanes = 2 if sz else (4 if Q else 2); T = 'df' if sz else 'f'; I = 'd' if sz else 's'
            ones = '~0ull' if sz else '0xFFFFFFFFu'
            s = '{ V128 a=c->v[%d], b=c->v[%d], r; r.d[1]=0; ' % (rn, rm)
            for i in range(lanes): s += 'r.%s[%d]=(a.%s[%d]%sb.%s[%d])? %s : 0; ' % (I, i, T, i, cmpop, T, i, ones)
            return s + 'c->v[%d]=r; }' % rd
        if op == 3:
            if U == 0 and size == 2 and rn == rm:   # MOV v
                return 'c->v[%d].d[0]=c->v[%d].d[0]; c->v[%d].d[1]=%s;' % (rd, rn, rd, 'c->v[%d].d[1]' % rn if Q else '0')
            ops = {(0, 0): '%s&%s', (0, 1): '%s&~%s', (0, 2): '%s|%s', (0, 3): '%s|~%s', (1, 0): '%s^%s'}
            if (U, size) in ops:
                e = ops[(U, size)]
                s = '{ u64 a0=c->v[%d].d[0],a1=c->v[%d].d[1],b0=c->v[%d].d[0],b1=c->v[%d].d[1]; c->v[%d].d[0]=%s; c->v[%d].d[1]=%s; }' % (
                    rn, rn, rm, rm, rd, e % ('a0', 'b0'), rd, (e % ('a1', 'b1')) if Q else '0')
                return s
            return None
        if op >= 0x18:
            sz = size & 1; hi = size >> 1
            if sz and not Q: return None
            lanes = 2 if sz else (4 if Q else 2); T = 'df' if sz else 'f'
            fe = None; acc = None
            if U == 0 and hi == 0 and op == 0x1A: fe = 'a.%s[%%d]+b.%s[%%d]'
            elif U == 0 and hi == 1 and op == 0x1A: fe = 'a.%s[%%d]-b.%s[%%d]'
            elif U == 1 and hi == 0 and op == 0x1B: fe = 'a.%s[%%d]*b.%s[%%d]'
            elif U == 1 and hi == 0 and op == 0x1F: fe = 'a.%s[%%d]/b.%s[%%d]'
            elif U == 0 and op == 0x19: acc = '-' if hi else '+'
            if acc and not sz:
                return 'v_fmla32(c,%d,%d,%d,%d,%d);' % (rd, rn, rm, Q, hi)
            if fe is None and acc is None:
                # FMAXNM FMINNM FMAX FMIN FRECPS FRSQRTS FABD FMULX: swr_simd's own lane function (cpu_helpers.c swr_fop2_*), its decode left out
                sel = {(0, 0, 0x18): 6, (0, 1, 0x18): 7, (0, 0, 0x1E): 4, (0, 1, 0x1E): 5, (0, 0, 0x1F): 10, (0, 1, 0x1F): 11,
                       (1, 1, 0x1A): 8, (0, 0, 0x1B): 9}.get((U, hi, op))
                if sel is None: return None
                W = '64' if sz else '32'
                s = '{ V128 a=c->v[%d], b=c->v[%d], r; ' % (rn, rm)
                for i in range(lanes): s += 'r.%s[%d]=swr_fop2_%s(%d,a.%s[%d],b.%s[%d]); ' % (T, i, W, sel, T, i, T, i)
                if not Q: s += 'r.d[1]=0; '
                return s + 'c->v[%d]=r; }' % rd
            s = '{ V128 a=c->v[%d], b=c->v[%d], r; ' % (rn, rm)
            if acc: s = '{ V128 a=c->v[%d], b=c->v[%d], r=c->v[%d]; ' % (rn, rm, rd)
            for i in range(lanes):
                # FNAN*: ARM's NaN when the lane comes out NaN (x86's default NaN is negative, sNaNs stay signalling)
                W = '64' if sz else '32'
                if acc:
                    d_, a_, b_ = 'r.%s[%d]' % (T, i), '%sa.%s[%d]' % ('-' if acc == '-' else '', T, i), 'b.%s[%d]' % (T, i)
                    s += '%s=FNAN3_%s(FMLA%s(%s,%s,%s),%s,%s,%s); ' % (d_, W, W, d_, a_, b_, d_, a_, b_)
                else:
                    s += 'r.%s[%d]=FNAN2_%s(%s,a.%s[%d],b.%s[%d]); ' % (T, i, W, (fe % (T, T)) % (i, i), T, i, T, i)
            if not Q: s += 'r.d[1]=0; '
            return s + 'c->v[%d]=r; }' % rd
        if op == 0x10 and (Q or size < 3):   # integer ADD/SUB
            eb = 8 << size; lanes = (128 if Q else 64) // eb; T = {8: 'b', 16: 'h', 32: 's', 64: 'd'}[eb]
            s = '{ V128 a=c->v[%d], b=c->v[%d], r; ' % (rn, rm)
            for i in range(lanes): s += 'r.%s[%d]=a.%s[%d]%sb.%s[%d]; ' % (T, i, T, i, '-' if U else '+', T, i)
            if not Q: s += 'r.d[1]=0; '
            return s + 'c->v[%d]=r; }' % rd
        return None
    # FMUL/FMLA/FMLS by element, vector + scalar
    if (w & 0x9F000400) == 0x0F000000 or (w & 0xDF000400) == 0x5F000000:
        scalar = (w >> 28) & 1
        op = (w >> 12) & 15
        if U or op not in (1, 5, 9) or size < 2: return None
        sz = size & 1; L = (w >> 21) & 1; H = (w >> 11) & 1; Mb = (w >> 20) & 1
        if sz and L: return None
        idx = H if sz else (H << 1) | L; m = (Mb << 4) | (w >> 16) & 15
        if scalar: lanes = 1
        else:
            if sz and not Q: return None
            lanes = 2 if sz else (4 if Q else 2)
        T = 'df' if sz else 'f'
        s = '{ V128 a=c->v[%d], r=c->v[%d]; %s e=c->v[%d].%s[%d]; ' % (rn, rd, 'f64' if sz else 'f32', m, T, idx)
        if scalar or op == 9: s = '{ V128 a=c->v[%d], r; r.d[0]=0; r.d[1]=0; %s e=c->v[%d].%s[%d]; ' % (rn, 'f64' if sz else 'f32', m, T, idx)
        if scalar and op != 9: s = '{ V128 a=c->v[%d], r; %s d0=c->v[%d].%s[0]; r.d[0]=0; r.d[1]=0; %s e=c->v[%d].%s[%d]; ' % (
            rn, 'f64' if sz else 'f32', rd, T, 'f64' if sz else 'f32', m, T, idx)
        for i in range(lanes):
            prev = 'd0' if scalar else 'r.%s[%d]' % (T, i)
            W = '64' if sz else '32'; a_ = '%sa.%s[%d]' % ('-' if op == 5 else '', T, i)
            if op == 9: s += 'r.%s[%d]=FNAN2_%s(a.%s[%d]*e,a.%s[%d],e); ' % (T, i, W, T, i, T, i)
            else: s += 'r.%s[%d]=FNAN3_%s(FMLA%s(%s,%s,e),%s,%s,e); ' % (T, i, W, W, prev, a_, prev, a_)
        if not Q and not scalar: s += 'r.d[1]=0; '
        return s + 'c->v[%d]=r; }' % rd
    # DUP / INS / UMOV
    if (w & 0x9FE08400) == 0x0E000400:
        imm5 = (w >> 16) & 31; imm4 = (w >> 11) & 15; op = U
        if not imm5 & 15 and not imm5 & 16: return None
        sz = (imm5 & -imm5).bit_length() - 1
        if sz > 3: return None
        idx = imm5 >> (sz + 1); T = 'bhsd'[sz]; lanes = (128 if Q else 64) >> (3 + sz)
        if op == 0 and imm4 == 7 and ((sz == 3) == bool(Q)):
            return g.setX('rd', 'c->v[%d].%s[%d]' % (rn, T, idx))
        if op == 0 and imm4 == 3 and Q:
            return 'c->v[%d].%s[%d]=%s;' % (rd, T, idx, 'c->x[%d]' % rn if rn != 31 else '0')
        if op == 1 and Q:
            return 'c->v[%d].%s[%d]=c->v[%d].%s[%d];' % (rd, T, idx, rn, T, (imm4 >> sz))
        if op == 0 and imm4 in (0, 1) and not (sz == 3 and not Q):
            src = 'c->v[%d].%s[%d]' % (rn, T, idx) if imm4 == 0 else ('(%s)%s' % (['u8', 'u16', 'u32', 'u64'][sz], '0' if rn == 31 else 'c->x[%d]' % rn))
            s = '{ V128 r; %s e=%s; ' % (['u8', 'u16', 'u32', 'u64'][sz], src)
            for i in range(lanes): s += 'r.%s[%d]=e; ' % (T, i)
            if not Q: s += 'r.d[1]=0; '
            return s + 'c->v[%d]=r; }' % rd
        return None
    # MOVI d/2d #0 (by far the common case)
    if (w & 0x9FF80400) == 0x0F000400 and (w & 0xFFFFFFE0) in (0x2F00E400, 0x6F00E400):
        return 'c->v[%d].d[0]=0; c->v[%d].d[1]=0;' % (rd, rd)
    return None


# tests: SWR_A64_NO_INLINE_SIMD=1 sends every AdvSIMD data op through swr_simd; =float keeps the integer templates
# (fast_simd_int: Bink 2's decoder, its speed) and sends only the others (floating point among them) through swr_simd
_NO_INLINE_SIMD = __import__('os').environ.get('SWR_A64_NO_INLINE_SIMD', '')


@ins('SIMD_DP', '0 x x 0 111 x xxxxxxxxxxxxxxxxxxxxxxxx')
def _(g):
    if g.static and _NO_INLINE_SIMD != '1':
        f = fast_simd_int(g) if _NO_INLINE_SIMD == 'float' else fast_simd(g)
        if f: return f
    return simd_fallback(g)


@ins('SIMD_DP2', '0 1 x 1 111 x xxxxxxxxxxxxxxxxxxxxxxxx')
def _(g):
    w = g.w
    # DUP (element, scalar) = MOV Bd/Hd/Sd/Dd, Vn.T[i]: the element zero-extended into rd
    if g.static and _NO_INLINE_SIMD != '1' and (w & 0xFFE0FC00) == 0x5E000400 and (w >> 16) & 15:
        imm5 = (w >> 16) & 31; size = 0
        while not (imm5 >> size) & 1: size += 1
        eb = 8 << size; idx = imm5 >> (size + 1)
        return '{ u64 e_=c->v[%d].%s[%d]; c->v[%d].d[0]=e_; c->v[%d].d[1]=0; }' % ((w >> 5) & 31, _UT[eb], idx, w & 31, w & 31)
    return simd_fallback(g)


# ARMv8.2 SHA3 / SHA512 (EOR3, BCAX, RAX1, XAR, SHA512H/H2/SU0/SU1): the 0xCE crypto group, done by swr_simd
@ins('SIMD_CRYPTO3', '11001110 xxx xxxxx x xxxxx xxxxx xxxxx')
def _(g):
    return simd_fallback(g)


# LDRAA / LDRAB (ARMv8.3): a 64 bit load from Xn|SP + (S:imm9) * 8 after authenticating Xn. nothing signs pointers here,
# so it's the plain load; W: pre-index writeback
@ins('LDRA', '11111000 x x 1 xxxxxxxxx x 1 xxxxx xxxxx', spec=('pacW',))
def _(g):
    if g.static:
        v = (g.v('pacS') << 9) | g.v('pacimm9')
        if v >> 9: v -= 1 << 10
        off = '(u64)(i64)(%d)' % (v * 8)
    else:
        off = '((u64)(i64)((i32)((u32)((%s<<9)|%s)<<22)>>22)*8)' % (g.f('pacS'), g.f('pacimm9'))
    load = g.setX('rt', 'v_')
    if g.v('pacW'):
        return '{ u64 a_=%s+%s; u64 v_=RD64(a_); %s %s }' % (g.XS('rn'), off, g.setXS('rn', 'a_'), load)
    return '{ u64 v_=RD64(%s+%s); %s }' % (g.XS('rn'), off, load)


# ADDG / SUBG (memory tagging): Xd|SP = Xn|SP +- uimm6 * 16 with allocation tag 0 in bits 56-59 (tag access off, as
# the ARM pseudocode gives without MTE enabled; STG and LDG above keep tags at 0 too)
@ins('ADDG', '1001000110 xxxxxx 00 xxxx xxxxx xxxxx')
def _(g):
    return g.setXS('rd', '(%s+(u64)%s*16)&~(15ull<<56)' % (g.XS('rn'), g.f('uimm6')))


@ins('SUBG', '1101000110 xxxxxx 00 xxxx xxxxx xxxxx')
def _(g):
    return g.setXS('rd', '(%s-(u64)%s*16)&~(15ull<<56)' % (g.XS('rn'), g.f('uimm6')))


# RMIF (ARMv8.4 flag manipulation): Xn rotated right by imm6, its low four bits go into the NZCV bits picked by mask
@ins('RMIF', '10111010000 xxxxxx 00001 xxxxx 0 xxxx')
def _(g):
    x = g.X('rn'); sh = g.f('rmif_imm6'); msk = g.f('nzcv')
    return ('{ u64 x_=%s; unsigned s_=(unsigned)(%s); u64 t_= s_? ((x_>>s_)|(x_<<(64-s_))) : x_; u32 m_=%s; '
            'if(m_&8) c->n=(u32)(t_>>3)&1; if(m_&4) c->z=(u32)(t_>>2)&1; '
            'if(m_&2) c->cf=(u32)(t_>>1)&1; if(m_&1) c->vf=(u32)t_&1; }') % (x, sh, msk)


# ======================================================================= decode
# bucketed on the top 11 bits, most specific pattern first
BUCKET_BITS = 21     # w>>21


def build_buckets():
    b = []
    for top in range(1 << 11):
        wv = top << BUCKET_BITS; wm = 0x7FF << BUCKET_BITS
        lst = []
        for i, (name, m, v, spec, fn) in enumerate(TABLE):
            mm = m & wm
            if (wv & mm) == (v & mm):
                lst.append(i)
        b.append(lst)
    return b


BUCKETS = None


def decode(w):
    global BUCKETS
    if BUCKETS is None: BUCKETS = build_buckets()
    for i in BUCKETS[w >> BUCKET_BITS]:
        name, m, v, spec, fn = TABLE[i]
        if (w & m) == v: return i
    return -1


_EC = {}   # encoding -> C, only for pc-independent instructions


def emit_static(w, pc):
    """-> str (plain C), tuple (control flow) or None (undefined)"""
    r = _EC.get(w, _EC)
    if r is not _EC: return r
    i = decode(w)
    if i < 0:
        _EC[w] = None; return None
    g = G(True, w, pc)
    r = TABLE[i][4](g)
    if not g.pcused: _EC[w] = r   # pc-independent, reusable
    return r


def gen_interp_cases():
    """interpreter C: switch on the top 11 bits, specialized by fields"""
    import itertools
    out = []
    bodies = {}
    for i, (name, m, v, spec, fn) in enumerate(TABLE):
        cases = []
        for combo in itertools.product(*[range(1 << FIELDS[s][1]) for s in spec]):
            sp = dict(zip(spec, combo))
            g = G(False, spec=sp)
            try:
                r = fn(g)
            except KeyError as e:
                raise RuntimeError('%s: %s' % (name, e))
            decl = ''.join(_field_decl(n) for n in sorted(g.used))
            cases.append((combo, decl, r))
        bodies[i] = cases
    return bodies


def _field_decl(n):
    f = FIELDS[n]
    lo, wd = f[0], f[1]
    if len(f) > 2:
        return 'const i64 f_%s=(i64)((i32)(w<<%d)>>%d); ' % (n, 32 - lo - wd, 32 - wd)
    return 'const u32 f_%s=(w>>%d)&%d; ' % (n, lo, (1 << wd) - 1)


def spec_index_expr(spec):
    """C that computes the specialization index from w."""
    parts = []; sh = 0
    for s in reversed(spec):
        lo, wd = FIELDS[s][0], FIELDS[s][1]
        parts.append('(((w>>%d)&%d)<<%d)' % (lo, (1 << wd) - 1, sh)); sh += wd
    return '|'.join(parts) or '0'
