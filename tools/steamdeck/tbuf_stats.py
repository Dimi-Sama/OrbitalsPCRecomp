# Orbitals PC Recomp, a work based on SwitchRecomp by MZ Labs. GNU AGPL v3.0 with the additional terms of NOTICE.txt (LICENSE.txt).
"""The texel buffers dumped by NXRT_VK_TBUF_DUMP (vk_replay.c tbuf_dump), summed up per file: element count, NaN, infinities, huge
values (|x| > 1e6), denormals, zeros, min / max / median of the finite values. Two folders (a Deck run and a PC run of the same
moment) are compared key by key, so a buffer that only the AMD run fills with garbage stands out.

    python tools/steamdeck/tbuf_stats.py DIR [DIR2]
"""
import math
import re
import struct
import sys
from pathlib import Path

NAME = re.compile(r"(?P<key>[0-9a-f]{16})-st(?P<st>\d+)-b(?P<b>\d+)-(?P<fmt>[^-]+)-(?P<n>\d+)\.bin$")
FLOAT_FORMATS = {"R32F": ("f", 4), "RG32F": ("f", 4), "RGBA32F": ("f", 4), "RGB32F": ("f", 4),
                 "R16F": ("e", 2), "RG16F": ("e", 2), "RGBA16F": ("e", 2)}


def stats(path, fmt):
    data = path.read_bytes()
    code, size = FLOAT_FORMATS.get(fmt.upper().replace("_", ""), ("I", 4))
    count = len(data) // size
    values = struct.unpack(f"<{count}{code}", data[:count * size])
    out = {"elements": count}
    if code == "I":   # integer formats: zeros, the largest value, how many look like float bits of NaN
        out.update(zeros=sum(1 for v in values if v == 0), max=max(values, default=0),
                   nan_bits=sum(1 for v in values if (v & 0x7f800000) == 0x7f800000 and v & 0x7fffff))
        return out
    finite = [v for v in values if math.isfinite(v)]
    tiny = 1.17549435e-38 if size == 4 else 6.1e-5
    finite_sorted = sorted(finite)
    out.update(nan=sum(1 for v in values if v != v), inf=sum(1 for v in values if v in (math.inf, -math.inf)),
               huge=sum(1 for v in finite if abs(v) > 1e6), denormal=sum(1 for v in finite if v and abs(v) < tiny),
               zeros=sum(1 for v in finite if v == 0), min=finite_sorted[0] if finite else None,
               max=finite_sorted[-1] if finite else None, median=finite_sorted[len(finite) // 2] if finite else None)
    return out


def table(folder):
    rows = {}
    for path in sorted(Path(folder).glob("*.bin")):
        m = NAME.search(path.name)
        if m:
            rows[(m["key"], int(m["st"]), int(m["b"]), m["fmt"], int(m["n"]))] = stats(path, m["fmt"])
    return rows


def line(s):
    if "nan" in s:
        fmt = lambda v: "-" if v is None else f"{v:.4g}"
        return (f"{s['elements']:>8} el  nan {s['nan']:>6}  inf {s['inf']:>5}  huge {s['huge']:>5}  denorm {s['denormal']:>5}  "
                f"zero {s['zeros']:>7}  min {fmt(s['min']):>10}  med {fmt(s['median']):>10}  max {fmt(s['max']):>10}")
    return f"{s['elements']:>8} el  (integer)  zero {s['zeros']:>7}  max {s['max']:#x}  NaN-like bits {s['nan_bits']}"


def main(argv):
    if not argv:
        print(__doc__); return 2
    tables = [table(d) for d in argv[:2]]
    keys = sorted(set().union(*tables))
    for k in keys:
        name = f"{k[0]} st{k[1]} b{k[2]} {k[3]} #{k[4]}"
        for label, t in zip(("A", "B"), tables):
            if k in t:
                print(f"{name:<44} {label if len(tables) > 1 else ''} {line(t[k])}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
