#!/usr/bin/env python3
# Orbitals PC Recomp, a work based on SwitchRecomp by MZ Labs. GNU AGPL v3.0 with the additional terms of NOTICE.txt (LICENSE.txt).
"""Which pass of a dumped frame first wrote strongly saturated green or blue pixels (runs on the Steam Deck: no dependency).

  pass_colors.py RUN_DIR [--frame N]

Reads the per-pass colour target copies of NXRT_VK_DUMP_AT_S + NXRT_VK_TD_PASSES (<log>.pass-<frame>-<n>-c<slot>-ser<serial>-<format>-<w>x<h>.raw)
and prints, per pass, the share of pixels that are saturated green (G well above R and B) or saturated blue (B well above R and G, and bright),
sampled on a grid. Formats read: RGBA16F, RGBA8 / BGRA8 (and their sRGB forms), RGB10A2 is skipped.
"""
import argparse, glob, os, re, struct


def pixels(path, fmt, w, h, step):
    data = open(path, 'rb').read()
    if fmt.startswith('RGBA16F'):
        bpp = 8
        for y in range(0, h, step):
            for x in range(0, w, step):
                o = (y * w + x) * bpp
                if o + 8 > len(data): return
                r, g, b, _ = struct.unpack_from('<4e', data, o)
                yield r, g, b
    elif fmt.startswith(('RGBA8', 'BGRA8')):
        bgr = fmt.startswith('BGRA8')
        for y in range(0, h, step):
            for x in range(0, w, step):
                o = (y * w + x) * 4
                if o + 4 > len(data): return
                c0, c1, c2 = data[o] / 255, data[o + 1] / 255, data[o + 2] / 255
                yield (c2, c1, c0) if bgr else (c0, c1, c2)


def main():
    ap = argparse.ArgumentParser(); ap.add_argument('run'); ap.add_argument('--frame'); ap.add_argument('--step', type=int, default=6)
    a = ap.parse_args()
    files = glob.glob(os.path.join(a.run, '*.pass-*.raw'))
    rx = re.compile(r'\.pass-(\d+)-(\d+)-c(\d+)-ser(\d+)-([A-Z0-9_]+)-(\d+)x(\d+)\.raw$')
    rows = []
    for f in files:
        m = rx.search(f)
        if not m or (a.frame and m[1] != a.frame): continue
        rows.append((int(m[1]), int(m[2]), int(m[3]), int(m[4]), m[5], int(m[6]), int(m[7]), f))
    rows.sort()
    seen_ser = {}
    for fr, n, slot, ser, fmt, w, h, f in rows:
        tot = green = blue = 0
        for r, g, b in pixels(f, fmt, w, h, a.step):
            tot += 1
            if g > 0.25 and g > 2.5 * max(r, b, 1e-4): green += 1
            if b > 0.35 and b > 2.5 * max(r, g, 1e-4): blue += 1
        if not tot: continue
        gp, bp = 100.0 * green / tot, 100.0 * blue / tot
        prev = seen_ser.get(ser, (0.0, 0.0)); seen_ser[ser] = (gp, bp)
        mark = ' <-- green up' if gp - prev[0] > 0.2 else ''
        mark += ' <-- blue up' if bp - prev[1] > 0.2 else ''
        print(f'frame {fr} pass {n:4d} c{slot} ser{ser} {fmt:10s} {w}x{h}: green {gp:5.2f} %  blue {bp:5.2f} %{mark}')


if __name__ == '__main__':
    main()
