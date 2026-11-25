"""Move the game's hot functions into code_hot*.c, as mkw-recomp / Hookshot do (their nx2/split_hot.py, A64_HOT_CHUNK).

    python tools/steamdeck/split_hot.py <generated dir> <hot list> <out dir> [--pieces N]

<generated dir> is a code generation (code_*.c, module.c, ...); <hot list> one symbol per line, hottest first (from perf on the
Deck: `perf report --dsos Orbitals_code.so -s sym`); <out dir> gets a copy of the generation where each hot function's definition
has moved from its chunk into one of N code_hot*.c files (by heat, hottest first), with the prototypes of its chunk.
Two effects: the ~1000 functions that hold 95 % of the game code's time sit together in the module instead of across 390 MB
(i-cache, iTLB), and a hot callee's body is in the same translation unit as its hot callers, so the compiler can inline it.
Nothing else changes: the same C, the same flags; names that are not lifted functions (the runtime's helpers) are skipped.
"""
import argparse
import os
import re
import shutil

cli = argparse.ArgumentParser()
cli.add_argument("generated")
cli.add_argument("hot")
cli.add_argument("out")
cli.add_argument("--pieces", type=int, default=4)
cli.add_argument("--max", type=int, default=1200, help="at most this many hot functions")
a = cli.parse_args()

hot = [l.strip() for l in open(a.hot) if l.strip().startswith("F_")][:a.max]
rank = {n: i for i, n in enumerate(hot)}
os.makedirs(a.out, exist_ok=True)
head = re.compile(r"^void (F_[0-9A-F]+)\(CPU\* RESTRICT c, u64 e\)\{\s*$")
moved = {}   # name -> (definition text, prototypes of its chunk)
names = sorted(os.listdir(a.generated))
for name in names:
    src = os.path.join(a.generated, name)
    if not os.path.isfile(src):
        continue
    if not (name.startswith("code_") and name.endswith(".c")) or name.startswith("code_hot"):
        if name.endswith((".c", ".h")):
            shutil.copy2(src, os.path.join(a.out, name))
        continue
    lines = open(src, encoding="utf-8", errors="surrogateescape").read().split("\n")
    protos = [l for l in lines if l.startswith("void F_") and l.endswith(";")]
    keep, i, took = [], 0, 0
    while i < len(lines):
        m = head.match(lines[i])
        if m and m.group(1) in rank:
            j = i
            while lines[j] != "}":
                j += 1
            moved[m.group(1)] = ("\n".join(lines[i:j + 1]), protos)
            i = j + 1; took += 1
            continue
        keep.append(lines[i]); i += 1
    dst = os.path.join(a.out, name)
    text = "\n".join(keep)
    if not os.path.exists(dst) or open(dst, encoding="utf-8", errors="surrogateescape").read() != text:
        open(dst, "w", encoding="utf-8", errors="surrogateescape", newline="\n").write(text)

order = sorted(moved, key=lambda n: rank[n])
per = (len(order) + a.pieces - 1) // max(a.pieces, 1)
for k in range(a.pieces):
    part = order[k * per:(k + 1) * per]
    protos = []
    seen = set()
    for n in part:
        for p in moved[n][1]:
            if p not in seen:
                seen.add(p); protos.append(p)
    body = ['#include "cpu.h"'] + protos + [moved[n][0] for n in part]
    path = os.path.join(a.out, "code_hot%d.c" % k)
    text = "\n".join(body) + "\n"
    if not os.path.exists(path) or open(path, encoding="utf-8", errors="surrogateescape").read() != text:
        open(path, "w", encoding="utf-8", errors="surrogateescape", newline="\n").write(text)
missing = [n for n in hot if n not in moved]
print("moved %d hot functions into %d pieces; %d names not found in the chunks" % (len(moved), a.pieces, len(missing)))
