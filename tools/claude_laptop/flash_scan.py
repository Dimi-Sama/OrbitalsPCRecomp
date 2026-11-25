"""Find short red or blue flashes in a sequence of captures (flash_repro.py burst): pixels strongly red or blue in one capture and in
neither neighbour, at the same place (a flash, not a red or blue object of the scene, which stays from capture to capture).

  flash_scan.py <burst dir> [--step 4] [--top 20] [--json out.json]

Per capture: red / blue = pixels strongly red / blue; flash_red / flash_blue = those of them that are not so in the captures before and
after; box = the bounding box (in pixels of the capture) of the flash pixels. Standard library only (PNGs written by the runtime are
unfiltered, so decoding is a zlib inflate).
"""
import argparse, json, os, sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'visual_suite'))
from stepper import read_png


def classes(path, step):
    w, h, bpp, stride, raw = read_png(path)
    rows = []
    for y in range(0, h, step):
        o = y * stride + 1
        line = raw[o:o + w * bpp]
        r, g, b = line[0::bpp * step], line[1::bpp * step], line[2::bpp * step]
        # 1: strongly red (fire is orange-yellow: G high too), 2: strongly blue/magenta-blue
        rows.append(bytes(1 if rr > 140 and rr - gg > 100 and rr - bb > 80 else 2 if bb > 140 and bb - rr > 90 and bb - gg > 60 else 0
                          for rr, gg, bb in zip(r, g, b)))
    return w, h, rows


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('dir', type=Path)
    ap.add_argument('--step', type=int, default=4)
    ap.add_argument('--top', type=int, default=20)
    ap.add_argument('--json', type=Path)
    a = ap.parse_args()
    files = sorted(p for p in a.dir.glob('*.png'))
    if len(files) < 3:
        sys.exit('fewer than three captures')
    cl = []
    for p in files:
        try:
            cl.append(classes(p, a.step))
        except Exception as e:   # a capture cut short
            cl.append(None); print(f'{p.name}: {e}', file=sys.stderr)
    out = []
    for i, p in enumerate(files):
        c = cl[i]
        if c is None:
            continue
        w, h, rows = c
        prev, nxt = cl[i - 1] if i else None, cl[i + 1] if i + 1 < len(cl) else None
        n = {1: 0, 2: 0}; f = {1: 0, 2: 0}; box = [w, h, -1, -1]
        for y, row in enumerate(rows):
            pr = prev[2][y] if prev else None; nr = nxt[2][y] if nxt else None
            for x, v in enumerate(row):
                if not v:
                    continue
                n[v] += 1
                if (pr is None or pr[x] != v) and (nr is None or nr[x] != v):
                    f[v] += 1
                    X, Y = x * a.step, y * a.step
                    box = [min(box[0], X), min(box[1], Y), max(box[2], X), max(box[3], Y)]
        out.append({'file': p.name, 'red': n[1], 'blue': n[2], 'flash_red': f[1], 'flash_blue': f[2], 'box': box if box[2] >= 0 else None})
    if a.json:
        a.json.write_text(json.dumps(out))
    print(f'{len(out)} captures; median red {sorted(o["red"] for o in out)[len(out) // 2]}, blue {sorted(o["blue"] for o in out)[len(out) // 2]}')
    for o in sorted(out, key=lambda o: -(o['flash_red'] + o['flash_blue']))[:a.top]:
        print(o)


if __name__ == '__main__':
    main()
