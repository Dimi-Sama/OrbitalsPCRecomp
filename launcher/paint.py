# Orbitals PC Recomp, a work based on SwitchRecomp by MZ Labs. GNU AGPL v3.0 with the additional terms of NOTICE.txt (LICENSE.txt).
"""Flat shapes with smooth edges, which Tk's own do not have: leaning bars, the diagonal, screentone, sparkles, small icons. Each is made
once, at the screen's scale, and kept as a picture. No gradients and no glows: one colour each, like the title card they are for."""
import base64
import math
import struct
import tkinter as tk
import zlib
from functools import lru_cache
from pathlib import Path

from . import look

ASSETS = Path(__file__).with_name("assets")
_root, _kept, _large = None, {}, {}   # a picture belongs to the Tk application it was made in


def use(root):
    """Make the pictures for this window."""
    global _root
    if root is not _root:
        _root = root
        _kept.clear()
        _large.clear()


def rgb(colour):
    return tuple(int(colour[i:i + 2], 16) for i in (1, 3, 5))


def png(w, h, rows):
    """A PNG of rows of RGBA bytes."""
    def chunk(kind, data):
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data))

    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 6, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(b"".join(b"\0" + row for row in rows), 1)) + chunk(b"IEND", b""))


def picture(key, make):
    if key not in _kept:
        _kept[key] = tk.PhotoImage(master=_root, data=base64.b64encode(make()))
    return _kept[key]


def logotype(room):
    """The largest drawing of the logotype for this screen that fits in `room` pixels, and its scale."""
    for scale in (200, 150, 125, 100, 75):
        if scale <= look.SCALE * 100 + 1 or scale == 75:
            key = f"logotype-{scale}"
            if key not in _kept:
                _kept[key] = tk.PhotoImage(master=_root, file=str(ASSETS / f"{key}.png"))
            if _kept[key].width() <= room or scale == 75:
                return _kept[key], scale / 100


def _cut(x):
    return 0.0 if x < 0 else 1.0 if x > 1 else x


def _rgba(colour, alpha):
    return bytes((*rgb(colour), round(_cut(alpha) * 255)))


@lru_cache(maxsize=256)
def _leaning(w, h, slant, colour, slab, slab_colour):
    rise = math.hypot(1, slant / h)
    first, main = rgb(slab_colour or colour), rgb(colour)
    rows = []
    for y in range(h):
        t = (y + 0.5) / h
        left, right = slant * (1 - t), w - slant * t

        def pixel(x):
            alpha = _cut(0.5 + min((x + 0.5 - left) / rise, (right - x - 0.5) / rise))
            share = _cut(0.5 + (x + 0.5 - left - slab) / rise) if slab else 1.0
            return bytes((*(round(a + (b - a) * share) for a, b in zip(first, main)), round(alpha * 255)))

        low, high = int(left + slab) + 3, int(right) - 2
        rows.append(b"".join(pixel(x) for x in range(min(low, w))) + bytes((*main, 255)) * max(0, high - low)
                    + b"".join(pixel(x) for x in range(max(low, high), w)))
    return png(w, h, rows)


def leaning(w, h, slant, colour, slab=0, slab_colour=None):
    """A bar that leans: its top is `slant` pixels further right than its bottom. slab: how much of its left is of another colour."""
    args = (int(w), int(h), int(slant), colour, int(slab), slab_colour)
    return picture(("leaning", *args), lambda: _leaning(*args))


@lru_cache(maxsize=64)
def _shape(kind, size, colour, scale=4):
    """Small shapes: how much of each pixel they cover, from `scale` x `scale` points in it."""
    inside = {"dot": lambda x, y: x * x + y * y <= 1,
              "sparkle": lambda x, y: abs(x) ** 0.52 + abs(y) ** 0.52 <= 1,
              "next": lambda x, y: -0.62 <= x and abs(y) <= (0.86 - x) * 0.60,
              "before": lambda x, y: x <= 0.62 and abs(y) <= (0.86 + x) * 0.60,
              "ring": lambda x, y: 0.50 <= x * x + y * y <= 1}[kind]
    rows = []
    for py in range(size):
        row = b""
        for px_ in range(size):
            hits = sum(inside(((px_ + (i + 0.5) / scale) / size) * 2 - 1, ((py + (j + 0.5) / scale) / size) * 2 - 1)
                       for i in range(scale) for j in range(scale))
            row += _rgba(colour, hits / scale ** 2)
        rows.append(row)
    return png(size, size, rows)


def shape(kind, size, colour):
    """A dot, a ring, a sparkle, a pointer (next, before), `size` pixels wide."""
    args = (kind, max(1, round(size)), colour)
    return picture(("shape", *args), lambda: _shape(*args))


PARTS = 8   # the places between two pixels a row of the diagonal can start from


def diagonal(w, h, at, bands):
    """A picture of w x h whose rows are the same bands of colour, moved to at(y). bands: [(from, to, colour)] in pixels right of the
    diagonal; the last one may go on to the edge (to: None)."""
    def strip(part):
        out = bytearray(8 * w)
        for start, end, colour in bands:
            end = w if end is None else end
            first, last = max(-w, math.floor(start + part)), min(w, math.ceil(end + part))
            r, g, b = rgb(colour)
            for x in range(first, last):
                share = _cut(min(x + 1, end + part) - max(x, start + part))
                i = (x + w) * 4
                have = out[i + 3] / 255
                alpha = share + have * (1 - share)
                if alpha:
                    for k, c in enumerate((r, g, b)):
                        out[i + k] = round((c * share + out[i + k] * have * (1 - share)) / alpha)
                    out[i + 3] = round(alpha * 255)
        return bytes(out)

    strips = [strip(part / PARTS) for part in range(PARTS)]
    rows = []
    for y in range(h):
        place = at(y + 0.5)
        whole = math.floor(place)
        rows.append(strips[int((place - whole) * PARTS)][(w - whole) * 4:(2 * w - whole) * 4])
    return tk.PhotoImage(master=_root, data=base64.b64encode(png(w, h, rows)))


def _dot_rows(size):
    """A dot's rows: how much of each pixel it covers, as bytes."""
    r = size / 2
    return [bytes(round(255 * _cut(r + 0.5 - math.hypot(x + 0.5 - r, y + 0.5 - r))) for x in range(size)) for y in range(size)]


def screentone(left, top, w, h, size_at, colour, pitch=10):
    """Dots on a turned grid, as printed, for the part of a canvas at (left, top): size_at(x, y) gives how large one is, 0 to 1. They are
    laid in two layers, in which none touches another, and the layers joined."""
    pitch = look.px(pitch) // 2 * 2
    dots = {}
    layers = [bytearray(w * h), bytearray(w * h)]
    for row, y in enumerate(range(-(top % pitch), h + pitch, pitch // 2)):
        for x in range(-(left % pitch) + pitch // 2 * (row % 2), w + pitch, pitch):
            size = min(pitch, round(size_at(left + x, top + y) * pitch))
            if size < 2:
                continue
            x0, y0 = x - size // 2, y - size // 2
            if x0 < 0 or x0 + size > w:
                continue
            if size not in dots:
                dots[size] = _dot_rows(size)
            for line, cover in enumerate(dots[size], y0):
                if 0 <= line < h:
                    layers[row % 2][line * w + x0:line * w + x0 + size] = cover
    joined = (int.from_bytes(layers[0], "big") | int.from_bytes(layers[1], "big")).to_bytes(w * h, "big")
    blank = bytearray(bytes((*rgb(colour), 0)) * w)
    rows = []
    for y in range(h):
        blank[3::4] = joined[y * w:(y + 1) * w]
        rows.append(bytes(blank))
    return tk.PhotoImage(master=_root, data=base64.b64encode(png(w, h, rows)))


def large(key, make):
    """The large pictures of the last size of a screen: kept while it does not change."""
    if _large.get("key") != key:
        _large.clear()
        _large.update(key=key, made=make())
    return _large["made"]


def arc(cx, cy, r, start, end, steps=10):
    return [(cx + r * math.cos(math.radians(start + (end - start) * i / steps)), cy + r * math.sin(math.radians(start + (end - start) * i / steps)))
            for i in range(steps + 1)]


# the icons' lines, on a square of 24
ICONS = {
    "pad": [[(7.4, 7.4), (16.6, 7.4), *arc(16.6, 11.4, 4.0, -90, 10, 8), (21.6, 15.8), *arc(19.6, 16.4, 2.1, -10, 140, 7), (15.4, 14.8),
             (8.6, 14.8), (6.0, 17.8), *arc(4.4, 16.4, 2.1, 40, 190, 7), (3.4, 12.1), *arc(7.4, 11.4, 4.0, 170, 270, 8)],
            [(7.6, 9.8), (7.6, 12.6)], [(6.2, 11.2), (9.0, 11.2)], arc(15.4, 10.2, 0.35, 0, 360, 8), arc(17.1, 12.0, 0.35, 0, 360, 8)],
}


@lru_cache(maxsize=128)
def _icon(name, size, colour, width):
    scale = size / 24
    lines = [[(x * scale, y * scale) for x, y in path] for path in ICONS[name]]
    rows = []
    for y in range(size):
        row = b""
        for x in range(size):
            best = 1e9
            for path in lines:
                for (ax, ay), (bx, by) in zip(path, path[1:]):
                    dx, dy = bx - ax, by - ay
                    t = _cut(((x + 0.5 - ax) * dx + (y + 0.5 - ay) * dy) / max(1e-9, dx * dx + dy * dy))
                    best = min(best, (x + 0.5 - ax - t * dx) ** 2 + (y + 0.5 - ay - t * dy) ** 2)
            row += _rgba(colour, width * scale / 2 + 0.5 - math.sqrt(best))
        rows.append(row)
    return png(size, size, rows)


def icon(name, colour, size=20, width=2.0):
    args = (name, look.px(size), colour, width)
    return picture(("icon", *args), lambda: _icon(*args))
