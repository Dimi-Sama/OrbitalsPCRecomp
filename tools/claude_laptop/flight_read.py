"""Read a flight recording (runtime/nvn/vk/vk_flight.c: <exe folder>/flight/<time>_<label>/ with index.txt, frames.rgba, rows.bin).

  flight_read.py scan DIR [--step 4]                 per frame shown: strongly red / blue pixels and those of them in neither neighbour
  flight_read.py png DIR I OUT.png [--crop x0 y0 x1 y1]  frame shown number I (0 = oldest) as a PNG
  flight_read.py rows DIR FRAME                      the draws and dispatches of a frame (present number), grouped by shader pair
  flight_read.py diff DIR FRAME_A FRAME_B            draws whose count or instances differ between two frames
  flight_read.py tiles PV_DIR [--frame F] [--png OUTDIR] what each pass / dispatch wrote (gamectl passview: tiles.txt, tiles.rgba), with the share of
                                                     strongly red and blue pixels of each thumbnail; --png writes the thumbnails of those frames

Frames shown are the presented image scaled to 1280x720 in the swapchain's format (44: B8G8R8A8). Rows: vkf_row (vk_flight.h), 96 bytes.
"""
import argparse, collections, struct, sys, zlib
from pathlib import Path

FL = {1: 'drawn', 2: 'indexed', 4: 'indirect', 8: 'mdi', 16: 'mesh', 32: 'rc_skip', 64: 'hidden', 128: 'mdi_cut', 256: 'dispatch'}
ROW = struct.Struct('<QQ8I5II6I')


class Flight:
    def __init__(self, d):
        self.d = Path(d); self.images = []; self.frames = []
        for line in (self.d / 'index.txt').read_text().splitlines():
            t = line.split()
            if t[0] == 'image':
                self.w, self.h, self.fmt, self.row_bytes = int(t[1]), int(t[2]), int(t[4]), int(t[6])
            elif t[0] == 'i':
                self.images.append((int(t[2]), int(t[3])))           # present number, time
            elif t[0] == 'f':
                self.frames.append((int(t[1]), int(t[2]), int(t[3])))  # frame, first row, rows
        self.size = self.w * self.h * 4

    def rgb(self, i):
        with open(self.d / 'frames.rgba', 'rb') as f:
            f.seek(i * self.size); px = f.read(self.size)
        if self.fmt == 44:   # BGRA
            return px[2::4], px[1::4], px[0::4]
        return px[0::4], px[1::4], px[2::4]

    def rows(self, frame):
        for fr, first, n in self.frames:
            if fr == frame:
                with open(self.d / 'rows.bin', 'rb') as f:
                    f.seek(first * self.row_bytes); data = f.read(n * self.row_bytes)
                return [ROW.unpack_from(data, k * self.row_bytes) for k in range(n)]
        return None


def classes(fl, i, step):
    r, g, b = fl.rgb(i); out = []
    for y in range(0, fl.h, step):
        o = y * fl.w
        rr, gg, bb = r[o:o + fl.w:step], g[o:o + fl.w:step], b[o:o + fl.w:step]
        out.append(bytes(1 if x > 140 and x - yv > 100 and x - z > 80 else 2 if z > 140 and z - x > 90 and z - yv > 60 else 0 for x, yv, z in zip(rr, gg, bb)))
    return out


def scan(a):
    fl = Flight(a.dir); cl = [classes(fl, i, a.step) for i in range(len(fl.images))]; res = []
    for i in range(len(cl)):
        n = [0, 0, 0]; f = [0, 0, 0]; box = [fl.w, fl.h, -1, -1]
        for y, row in enumerate(cl[i]):
            pr = cl[i - 1][y] if i else None; nr = cl[i + 1][y] if i + 1 < len(cl) else None
            for x, v in enumerate(row):
                if v:
                    n[v] += 1
                    if (pr is None or pr[x] != v) and (nr is None or nr[x] != v):
                        f[v] += 1; X, Y = x * a.step, y * a.step; box = [min(box[0], X), min(box[1], Y), max(box[2], X), max(box[3], Y)]
        res.append({'i': i, 'present': fl.images[i][0], 'red': n[1], 'blue': n[2], 'flash_red': f[1], 'flash_blue': f[2], 'box': box if box[2] >= 0 else None})
    for x in res:
        if x['flash_red'] + x['flash_blue'] >= a.min:
            print(x)
    print(f'{len(res)} frames; flagged {sum(1 for x in res if x["flash_red"] + x["flash_blue"] >= a.min)} (min {a.min})')


def write_png(path, w, h, rgb_rows):
    raw = b''.join(b'\0' + row for row in rgb_rows)
    def chunk(t, d): return struct.pack('>I', len(d)) + t + d + struct.pack('>I', zlib.crc32(t + d) & 0xffffffff)
    Path(path).write_bytes(b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', struct.pack('>IIBBBBB', w, h, 8, 2, 0, 0, 0)) + chunk(b'IDAT', zlib.compress(raw, 6)) + chunk(b'IEND', b''))


def png(a):
    fl = Flight(a.dir); r, g, b = fl.rgb(a.index)
    x0, y0, x1, y1 = a.crop or (0, 0, fl.w, fl.h); rows = []
    for y in range(y0, y1):
        o = y * fl.w; line = bytearray((x1 - x0) * 3)
        line[0::3], line[1::3], line[2::3] = r[o + x0:o + x1], g[o + x0:o + x1], b[o + x0:o + x1]
        rows.append(bytes(line))
    write_png(a.out, x1 - x0, y1 - y0, rows); print(a.out, 'present', fl.images[a.index][0])


def key_of(row):
    vs, ps, pas, flags = row[0], row[1], row[2], row[3]
    kind = 'dispatch' if flags & 256 else 'draw'
    return (kind, f'{vs:016x}', f'{ps:016x}' if kind == 'draw' else '')


def describe(row):
    vs, ps, pas, flags, rt, mdi_i, mdi_cnt, binst, args_i, pad, *rest = row
    a, g = rest[0:5], rest[6:12]
    return f'pass {pas} flags {"|".join(v for k, v in FL.items() if flags & k)} a {list(a)}' + (f' gpu {list(g)}' if args_i else '')


def rows(a):
    fl = Flight(a.dir); rs = fl.rows(a.frame)
    if rs is None:
        sys.exit(f'frame {a.frame} not in the recording ({fl.frames[0][0]}..{fl.frames[-1][0]})')
    groups = collections.OrderedDict()
    for r in rs:
        groups.setdefault(key_of(r), []).append(r)
    for k, v in groups.items():
        print(len(v), *k, describe(v[0]))


def diff(a):
    fl = Flight(a.dir)
    def summary(fr):
        return collections.Counter(key_of(r) for r in fl.rows(fr))
    A, B = summary(a.frame_a), summary(a.frame_b)
    for k in sorted(set(A) | set(B)):
        if A[k] != B[k]:
            print(A[k], B[k], *k)


def tiles(a):
    d = Path(a.dir); lines = (d / 'tiles.txt').read_text().splitlines()
    tw, th = map(int, lines[0].split()[1:3]); size = tw * th * 4
    with open(d / 'tiles.rgba', 'rb') as f:
        for i, line in enumerate(lines[1:]):
            t = line.split(); frame = int(t[0])
            if a.frame is not None and frame != a.frame:
                continue
            f.seek(i * size); px = f.read(size); r, g, b = px[0::4], px[1::4], px[2::4]
            red = sum(1 for x, y, z in zip(r, g, b) if x > 140 and x - y > 100 and x - z > 80) / (tw * th)
            blue = sum(1 for x, y, z in zip(r, g, b) if z > 140 and z - x > 90 and z - y > 60) / (tw * th)
            print(f'{i:5d} frame {frame} pass {t[1]} {"cs" if t[2] == "1" else "gfx"} slot {t[3]} ser {t[4]} key {t[5]} {t[6]} {t[9]}  red {red:.3f} blue {blue:.3f}')
            if a.png:
                Path(a.png).mkdir(parents=True, exist_ok=True); rows = []
                for y in range(th):
                    o = y * tw; line_ = bytearray(tw * 3); line_[0::3], line_[1::3], line_[2::3] = r[o:o + tw], g[o:o + tw], b[o:o + tw]; rows.append(bytes(line_))
                write_png(Path(a.png) / f'{frame}-{i:05d}-p{t[1]}-s{t[3]}-{t[5]}.png', tw, th, rows)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter); sub = ap.add_subparsers(dest='cmd', required=True)
    s = sub.add_parser('scan'); s.add_argument('dir'); s.add_argument('--step', type=int, default=4); s.add_argument('--min', type=int, default=30); s.set_defaults(fn=scan)
    p = sub.add_parser('png'); p.add_argument('dir'); p.add_argument('index', type=int); p.add_argument('out'); p.add_argument('--crop', type=int, nargs=4); p.set_defaults(fn=png)
    r = sub.add_parser('rows'); r.add_argument('dir'); r.add_argument('frame', type=int); r.set_defaults(fn=rows)
    d = sub.add_parser('diff'); d.add_argument('dir'); d.add_argument('frame_a', type=int); d.add_argument('frame_b', type=int); d.set_defaults(fn=diff)
    t = sub.add_parser('tiles'); t.add_argument('dir'); t.add_argument('--frame', type=int); t.add_argument('--png'); t.set_defaults(fn=tiles)
    a = ap.parse_args(); a.fn(a)


if __name__ == '__main__':
    main()
