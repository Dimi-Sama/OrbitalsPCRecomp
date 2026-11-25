"""Table of Steam Deck runs (build/deck-runs/<run>, fetched with tools/steamdeck/pull-run.sh): FPS and frame times in time windows,
plus the 1 Hz telemetry (APU power, GPU clock, CPU use) over the same windows.

    python tools/steamdeck/deck_report.py RUN[:label] ... --window 230:320 [--window 200:290 ...]
"""
import argparse, csv, os, sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from orbitals_perf import frame_times, pct  # noqa: E402


def window(run, a, b):
    ts = [t for t in frame_times(run) if a * 1000 <= t < b * 1000]
    if len(ts) < 2: return None
    iv = [y - x for x, y in zip(ts, ts[1:])]
    out = dict(fps=len(ts) / (b - a), p50=pct(iv, 50), p95=pct(iv, 95), p99=pct(iv, 99), worst=max(iv),
               stutter=sum(1 for v in iv if v > 2 * pct(iv, 50)) / (b - a) * 60)
    tp = os.path.join(run, 'telemetry.csv')
    if os.path.exists(tp):
        rows = [r for r in csv.DictReader(open(tp)) if a <= float(r['t']) < b]
        if rows:
            m = lambda k: sum(float(r[k]) for r in rows) / len(rows)
            out.update(ppt=m('ppt_w'), sclk=m('sclk_mhz'), cpu=m('game_cpu_pct'), gpu=m('gpu_busy'), edge=max(float(r['edge_c']) for r in rows),
                       rss=max(float(r['rss_mb']) for r in rows), gtt=max(float(r['gtt_mb']) for r in rows))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('runs', nargs='+')
    ap.add_argument('--window', action='append', required=True)
    ap.add_argument('--root', default=os.path.join(os.path.dirname(__file__), '..', '..', 'build', 'deck-runs'))
    a = ap.parse_args()
    print('| Run | Window (s) | FPS | p50 ms | p95 ms | p99 ms | worst ms | frames > 2x p50 /min | APU W | GPU MHz | game CPU % | GPU busy % | max edge C | max RSS MB |')
    print('|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|')
    for spec in a.runs:
        name, _, label = spec.partition(':')
        run = name if os.path.isdir(name) else os.path.join(a.root, name)
        for w in a.window:
            x, y = (float(v) for v in w.split(':'))
            r = window(run, x, y)
            if not r: print('| %s | %s | - |' % (label or name, w)); continue
            print('| %s | %s | %.1f | %.1f | %.1f | %.1f | %.0f | %.1f | %s | %s | %s | %s | %s | %s |' % (
                label or name, w, r['fps'], r['p50'], r['p95'], r['p99'], r['worst'], r['stutter'],
                '%.1f' % r['ppt'] if 'ppt' in r else '-', '%.0f' % r['sclk'] if 'sclk' in r else '-',
                '%.0f' % r['cpu'] if 'cpu' in r else '-', '%.0f' % r['gpu'] if 'gpu' in r else '-',
                '%.0f' % r['edge'] if 'edge' in r else '-', '%.0f' % r['rss'] if 'rss' in r else '-'))


if __name__ == '__main__':
    main()
