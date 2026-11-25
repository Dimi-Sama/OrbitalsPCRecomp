"""How much of the GPU write-back traffic is the same range recorded again in the same frame (NXRT_VK_WBLOG=<bytes>
NXRT_VK_WBLOG_REC=1 runs): the bytes a per-submission coalescing of write-backs could save at most.

    python tools/steamdeck/wblog_repeats.py RUN_DIR [first_frame]
"""
import collections, re, sys

run = sys.argv[1]; first = int(sys.argv[2]) if len(sys.argv) > 2 else 0
rec = collections.defaultdict(collections.Counter)   # frame -> (addr, len) -> times
kinds = collections.Counter()
for line in open(run + '/stdout.txt', errors='replace'):
    m = re.search(r'wblog: rec frame (\d+) addr (0x[0-9a-f]+) len (0x[0-9a-f]+) kind (\d+)', line)
    if not m: continue
    f = int(m[1])
    if f < first: continue
    rec[f][(int(m[2], 16), int(m[3], 16))] += 1; kinds[m[4]] += 1
if not rec: sys.exit('no wblog rec lines')
frames = sorted(rec)
tot = sum(n * c for f in frames for (a, n), c in rec[f].items())
rep = sum(n * (c - 1) for f in frames for (a, n), c in rec[f].items())
print('frames %d-%d (%d), write-backs recorded %d, kinds %s' % (frames[0], frames[-1], len(frames), sum(kinds.values()), dict(kinds)))
print('per frame: %.1f MB recorded, %.1f MB of it a range already recorded in the same frame (%.0f %%)' % (
    tot / len(frames) / 2**20, rep / len(frames) / 2**20, 100.0 * rep / tot if tot else 0))
big = collections.Counter()
for f in frames:
    for (a, n), c in rec[f].items(): big[(a, n)] += c
print('largest ranges by bytes recorded:')
for (a, n), c in sorted(big.items(), key=lambda kv: -kv[0][1] * kv[1])[:10]:
    print('  %#x + %7.2f MB  %5.1f times a frame' % (a, n / 2**20, c / len(frames)))
