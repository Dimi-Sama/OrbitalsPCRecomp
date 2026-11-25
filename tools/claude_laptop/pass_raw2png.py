"""Thumbnails of NXRT_VK_DUMP_AT_S pass dumps (<log>.pass-<frame>-<n>-c<slot>-ser<serial>-<format>-<w>x<h>.raw), standard library only.

usage: python pass_raw2png.py RUN_DIR [--width 320] [--out DIR]
Writes DIR/pass-<frame>-<n>-c<slot>-ser<serial>-<fmt>.png (default DIR = RUN_DIR/passes) and prints, per pass, the mean colour and
the fraction of pixels that differ from the previous dump of the same target (what that pass drew).
"""
import argparse, array, glob, math, os, re, struct, zlib

ap = argparse.ArgumentParser(); ap.add_argument('run'); ap.add_argument('--width', type=int, default=320); ap.add_argument('--out'); ap.add_argument('--frame', help='only this frame'); ap.add_argument('--float-only', action='store_true')
a = ap.parse_args()
out = a.out or os.path.join(a.run, 'passes'); os.makedirs(out, exist_ok=True)
rx = re.compile(r'\.pass-(\d+)-(\d+)-c(\d+)-ser(\d+)-([\w]+)-(\d+)x(\d+)\.raw$')


def half(h):
    return struct.unpack('<e', struct.pack('<H', h))[0]


def px(raw, at, fmt, size):
    if fmt == 'RGBA16F':
        v = [half(x) for x in struct.unpack_from('<3H', raw, at)]
        return tuple(int(255 * max(0.0, min(1.0, c if math.isfinite(c) else 0)) ** (1 / 2.2)) for c in v)
    if fmt == 'RGB10A2':
        v, = struct.unpack_from('<I', raw, at); return tuple(((v >> b) & 1023) * 255 // 1023 for b in (0, 10, 20))
    if fmt == 'R11G11B10F':
        v, = struct.unpack_from('<I', raw, at)
        def f(bits, mb):   # unsigned small float: mb mantissa bits, 5 exponent bits above them
            m, e = bits & ((1 << mb) - 1), bits >> mb
            return (m / (1 << mb)) * 2.0 ** -14 if e == 0 else (2.0 ** (e - 15)) * (1 + m / (1 << mb)) if e < 31 else 0.0
        c = (f(v & 0x7ff, 6), f((v >> 11) & 0x7ff, 6), f((v >> 22) & 0x3ff, 5))
        return tuple(int(255 * max(0.0, min(1.0, x)) ** (1 / 2.2)) for x in c)
    if fmt == 'BGRA8': return raw[at + 2], raw[at + 1], raw[at]
    if size == 1: return (raw[at],) * 3
    if size == 2: return raw[at], raw[at + 1], 0
    return raw[at], raw[at + 1], raw[at + 2]


def png(path, w, h, rows):
    def chunk(t, d): return struct.pack('>I', len(d)) + t + d + struct.pack('>I', zlib.crc32(t + d) & 0xffffffff)
    data = b''.join(b'\0' + bytes(r) for r in rows)
    with open(path, 'wb') as f:
        f.write(b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', struct.pack('>IIBBBBB', w, h, 8, 2, 0, 0, 0)) + chunk(b'IDAT', zlib.compress(data, 6)) + chunk(b'IEND', b''))


prev = {}
files = sorted(glob.glob(os.path.join(a.run, '*.pass-*.raw')), key=lambda p: tuple(int(x) for x in rx.search(p).groups()[:2]) if rx.search(p) else (0, 0))
for p in files:
    m = rx.search(p)
    if not m: continue
    frame, n, slot, ser, fmt, w, h = m.groups(); w, h = int(w), int(h)
    if (a.frame and frame != a.frame) or (a.float_only and fmt not in ('RGBA16F', 'R11G11B10F')): continue
    raw = open(p, 'rb').read(); size = len(raw) // (w * h) if w * h else 0
    if not size: continue
    tw = min(a.width, w); th = max(1, h * tw // w)
    rows = []; tot = [0, 0, 0]; thumb = []
    for y in range(th):
        r = []
        for x in range(tw):
            c = px(raw, ((y * h // th) * w + x * w // tw) * size, fmt, size); r += c; thumb.append(c)
            for i in range(3): tot[i] += c[i]
        rows.append(r)
    key = (slot, ser); changed = ''
    if key in prev and len(prev[key]) == len(thumb):
        d = sum(1 for u, v in zip(prev[key], thumb) if max(abs(u[i] - v[i]) for i in range(3)) > 8) / len(thumb)
        changed = ' changed %.1f%%' % (100 * d)
    prev[key] = thumb
    name = 'pass-%s-%04d-c%s-ser%s-%s.png' % (frame, int(n), slot, ser, fmt)
    png(os.path.join(out, name), tw, th, rows)
    k = tw * th
    bad = ''
    if fmt == 'RGBA16F':   # NaN / Inf over the whole image, colour channels only
        hw = array.array('H'); hw.frombytes(raw[:len(raw) // 2 * 2]); nn = ni = 0
        for i in range(0, len(hw), 4):
            for c in (hw[i], hw[i + 1], hw[i + 2]):
                if c & 0x7c00 == 0x7c00:
                    if c & 0x3ff: nn += 1
                    else: ni += 1
        bad = ' NaN %d Inf %d' % (nn, ni) if nn or ni else ''
    elif fmt == 'R11G11B10F':
        dw = array.array('I'); dw.frombytes(raw[:len(raw) // 4 * 4]); nn = 0
        for v in dw:
            if (v & 0x7c0) == 0x7c0 or (v & 0x3e0000) == 0x3e0000 or (v & 0xf8000000) == 0xf8000000: nn += 1
        bad = ' NaN/Inf %d' % nn if nn else ''
    print('%s %dx%d mean %d,%d,%d%s%s' % (name, w, h, tot[0] // k, tot[1] // k, tot[2] // k, changed, bad))
