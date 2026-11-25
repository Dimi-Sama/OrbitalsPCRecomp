# Orbitals PC Recomp, a work based on SwitchRecomp by MZ Labs. GNU AGPL v3.0 with the additional terms of NOTICE.txt (LICENSE.txt).
"""What a graphics setting did in a run: frame rate, GPU time of one frame, the 3D resolution the draws used, memory.

  python tools/visual_suite/gfx_report.py [--from 200 --to 245] <run> [<run> ...]

Needs a run made with NXRT_VK_LOG_RES=1 (the "draw resolutions" lines) and NXRT_VK_GPUTIME_AT_S=<s> (one frame's GPU time by pass).
Columns: presents/s and p95 in the window (frames.csv), the GPU frame (first to last mark) with its passes / dispatches split, the most
used viewport during co-op (the per-player 3D view), the overlay files the game read, the [RED] lines beyond the usual ones.
"""
import csv, os, re, sys

USUAL = ('nvnWindowBuilderGetPresentInterval', 'buffer texture in a slot', 'e2cd2d78c70fdd98', 'RGBA_DXT5', 'shader corpus needs')


def stats(run, t0, t1):
    ts = [float(r['ms']) / 1000 for r in csv.DictReader(open(os.path.join(run, 'frames.csv')))]
    ts = [t for t in ts if t0 <= t <= t1]
    iv = sorted((b - a) * 1000 for a, b in zip(ts, ts[1:]))
    fps = (len(ts) - 1) / (ts[-1] - ts[0]) if len(ts) > 1 else 0
    return fps, iv[int(0.95 * len(iv))] if iv else 0, iv[int(0.99 * len(iv))] if iv else 0


def main():
    a = sys.argv[1:]; t0, t1 = 200.0, 245.0
    if '--from' in a: i = a.index('--from'); t0 = float(a[i + 1]); del a[i:i + 2]
    if '--to' in a: i = a.index('--to'); t1 = float(a[i + 1]); del a[i:i + 2]
    print(f'| run | FPS | p95 ms | p99 ms | GPU frame ms (passes / dispatches) | main 3D viewport (share of draws) | overlay | new [RED] |')
    print('|---|---:|---:|---:|---|---|---|---|')
    for run in a:
        fps, p95, p99 = stats(run, t0, t1)
        gpu, vp, ovl, red = '-', '-', [], set()
        for line in open(os.path.join(run, 'Orbitals.log'), errors='replace'):
            m = re.search(r'gputime: ([0-9.]+) ms from the first mark to the last; passes ([0-9.]+) \((\d+)\), dispatches ([0-9.]+) \((\d+)\)', line)
            if m: gpu = f'{m.group(1)} ({m.group(2)} in {m.group(3)} / {m.group(4)} in {m.group(5)})'
            m = re.match(r'\[\s*([0-9.]+)\] \[vk\] draw resolutions, frames \d+-\d+, \d+ draws \(viewport in attachment\): (\S+ in \S+) ([0-9.]+%)', line)
            if m and t0 - 60 <= float(m.group(1)) <= t1 + 60: vp = f'{m.group(2)} ({m.group(3)})'
            m = re.search(r'RomFS overlay: (\S+)', line)
            if m: ovl.append(m.group(1).rsplit('/', 1)[-1])
            if '[RED]' in line and not any(u in line for u in USUAL): red.add(re.sub(r'^\[[ 0-9.]+\] ', '', line.strip())[:90])
        print(f'| {os.path.basename(run.rstrip("/"))} | {fps:.1f} | {p95:.1f} | {p99:.1f} | {gpu} | {vp} | {",".join(ovl) or "-"} | {"; ".join(sorted(red)) or "-"} |')


if __name__ == '__main__':
    main()
