"""Frame statistics of one or more runs over a time window (for A/B comparisons on the same scripted path).

  python ab_stats.py [--from 190] [--to 238] <run dir> [<run dir> ...]

Per run: presents per second in the window (frames.csv, present times), frame-interval p50/p95/p99, and the NVN
translation thread's CPU ms a frame (the '[nvn] translation thread up to frame' lines logged inside the window).
"""
import csv, os, re, sys, statistics

def pct(v, p):
    v = sorted(v); return v[min(len(v) - 1, int(p / 100 * len(v)))] if v else float("nan")

def run_stats(run, t0, t1):
    ts = []
    with open(os.path.join(run, "frames.csv")) as f:
        for row in csv.DictReader(f):
            t = float(row["ms"]) / 1000
            if t0 <= t <= t1: ts.append(t)
    iv = [(b - a) * 1000 for a, b in zip(ts, ts[1:])]
    fps = (len(ts) - 1) / (ts[-1] - ts[0]) if len(ts) > 1 else float("nan")
    tr = []
    rx = re.compile(r"^\[\s*([0-9.]+)\] \[nvn\] translation thread up to frame \d+: ([0-9.]+) ms a frame translating \(CPU ([0-9.]+) ms\)")
    for line in open(os.path.join(run, "Orbitals.log"), errors="replace"):
        m = rx.match(line)
        if m and t0 <= float(m.group(1)) <= t1: tr.append(float(m.group(3)))
    return fps, pct(iv, 50), pct(iv, 95), pct(iv, 99), (statistics.mean(tr) if tr else float("nan")), len(ts)

def main():
    a = sys.argv[1:]; t0, t1 = 190.0, 238.0
    if "--from" in a: i = a.index("--from"); t0 = float(a[i + 1]); del a[i:i + 2]
    if "--to" in a: i = a.index("--to"); t1 = float(a[i + 1]); del a[i:i + 2]
    print(f"window {t0:.0f}-{t1:.0f} s")
    print(f"{'run':48} {'FPS':>7} {'p50':>7} {'p95':>7} {'p99':>7} {'transl.CPU':>10} {'frames':>7}")
    for run in a:
        fps, p50, p95, p99, tr, n = run_stats(run, t0, t1)
        print(f"{os.path.basename(run.rstrip('/\\')):48} {fps:7.2f} {p50:7.2f} {p95:7.2f} {p99:7.2f} {tr:10.2f} {n:7d}")

if __name__ == "__main__":
    main()
