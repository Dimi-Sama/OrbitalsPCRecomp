"""Neighbouring-frame differences of a run's screenshots (the runtime's own PNGs: filter 0, stored deflate; standard library only).

    python tools/steamdeck/frame_diff.py <frames dir>

For a test that changes the rendering every other frame (e.g. NXRT_VK_RT_UNBIND_KEEP=2: odd frames only): if the change shows in the
picture, frames one apart (one with, one without) differ more than frames two apart (both with or both without), although they are
closer in time. Prints the mean absolute difference per channel byte (0-255) of each pair, by screen half (the two co-op views), and
the averages of the one-apart and two-apart pairs.
"""
import os
import struct
import sys
import zlib

STEP = 7   # bytes sampled: every 7th byte of the RGBA rows (all channels over the picture)


def load(path):
    data = open(path, "rb").read()
    assert data[:8] == b"\x89PNG\r\n\x1a\n", path
    pos, w, h, idat = 8, 0, 0, b""
    while pos < len(data):
        n, kind = struct.unpack(">I4s", data[pos:pos + 8])
        body = data[pos + 8:pos + 8 + n]
        if kind == b"IHDR":
            w, h, depth, ctype = struct.unpack(">IIBB", body[:10])
            assert depth == 8 and ctype == 6, "RGBA8 only"
        elif kind == b"IDAT":
            idat += body
        pos += 12 + n
    raw = zlib.decompress(idat)
    stride = 1 + 4 * w
    rows = [raw[y * stride + 1:(y + 1) * stride] for y in range(h)]
    assert all(raw[y * stride] == 0 for y in range(0, h, 97)), "filter 0 only"
    return w, h, rows


def diff(a, b):
    w, h, ra = a
    _, _, rb = b
    half = 2 * w   # bytes of a half row (RGBA)
    s = [0, 0]; n = [0, 0]
    for y in range(0, h, 3):
        x, z = ra[y], rb[y]
        for side in (0, 1):
            xs, zs = x[side * half:(side + 1) * half:STEP], z[side * half:(side + 1) * half:STEP]
            s[side] += sum(abs(p - q) for p, q in zip(xs, zs)); n[side] += len(xs)
    return s[0] / n[0], s[1] / n[1]


def main():
    d = sys.argv[1]
    names = sorted(f for f in os.listdir(d) if f.startswith("shot-") and f.endswith(".png"))
    shots = [(int(f[5:-4]), load(os.path.join(d, f))) for f in names]
    one, two = [], []
    for i in range(len(shots) - 1):
        (fa, a), (fb, b) = shots[i], shots[i + 1]
        l, r = diff(a, b); gap = fb - fa
        print("presents %d-%d (gap %d): left %.2f right %.2f" % (fa, fb, gap, l, r))
        (one if gap % 2 else two).append((l, r))
    for name, v in (("odd gaps (one with, one without)", one), ("even gaps (same setting)", two)):
        if v:
            print("%s: %d pairs, left %.2f right %.2f" % (name, len(v), sum(x for x, _ in v) / len(v), sum(y for _, y in v) / len(v)))


main()
