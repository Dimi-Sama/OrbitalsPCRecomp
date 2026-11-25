"""Timing report of a cutscene run (standard library only).

usage: python cine_report.py RUN_DIR [--video-start PRESENT --video-end PRESENT] [--frames 5739 --fps 24]

Reads RUN_DIR/frames.csv (one line per present: ms, interval, ...; n = present index), RUN_DIR/frames-sig.csv
(frame-sig.ps1) and RUN_DIR/Orbitals.log (RomFS opens), and prints:
  * when the .bk2 files were opened;
  * the present rate (p50/p95/p99 of the present interval) over the video;
  * for every run of consecutive captured presents (a burst): new images vs repeats -> effective video fps,
    and the longest hold (frames skipped would show as a hold of 0 with a big jump, repeats as holds > 2);
  * with --video-start/--video-end (first / last present showing the video): on-screen duration and speed.
"""
import argparse, csv, os, re, statistics

ap = argparse.ArgumentParser()
ap.add_argument('run'); ap.add_argument('--video-start', type=int); ap.add_argument('--video-end', type=int)
ap.add_argument('--frames', type=int, default=5739); ap.add_argument('--fps', type=float, default=24.0)
ap.add_argument('--repeat-thresh', type=float, default=0.05, help='mean abs diff under which two captures are the same image')
a = ap.parse_args()

pres = {}
with open(os.path.join(a.run, 'frames.csv')) as f:
    for r in csv.DictReader(f):
        pres[int(r['n'])] = float(r['ms'])
print('presents: %d, last at %.1f s' % (len(pres), max(pres.values()) / 1000 if pres else 0))

log = os.path.join(a.run, 'Orbitals.log')
if os.path.exists(log):
    with open(log, encoding='utf-8', errors='replace') as f:
        for ln in f:
            m = re.match(r'\[\s*([\d.]+)\] romfs: (\S+\.bk2)', ln)
            if m: print('bk2 open at %8.2f s: %s' % (float(m.group(1)), m.group(2).split('/')[-1]))
            if 'FATAL' in ln or 'game crashed' in ln: print('LOG: ' + ln.strip())


def t(n):
    return pres.get(n, float('nan')) / 1000.0


if a.video_start and a.video_end:
    d = t(a.video_end) - t(a.video_start)
    exp = a.frames / a.fps
    print('video on screen: present %d (%.2f s) -> %d (%.2f s) = %.2f s; expected %.2f s -> speed %.3fx' % (
        a.video_start, t(a.video_start), a.video_end, t(a.video_end), d, exp, exp / d if d else 0))
    iv = [pres[n + 1] - pres[n] for n in range(a.video_start, a.video_end) if n in pres and n + 1 in pres]
    if iv:
        iv.sort(); q = lambda p: iv[min(len(iv) - 1, int(p * len(iv)))]
        print('present interval over the video: mean %.2f ms (%.2f/s), p50 %.2f, p95 %.2f, p99 %.2f, max %.1f ms' % (
            statistics.mean(iv), 1000 / statistics.mean(iv), q(.5), q(.95), q(.99), iv[-1]))

sig = os.path.join(a.run, 'frames-sig.csv')
if os.path.exists(sig):
    rows = []
    with open(sig) as f:
        for r in csv.DictReader(f): rows.append((int(r['present']), float(r['luma']), float(r['diff_prev'])))
    # bursts: runs of consecutive present numbers
    bursts = []; cur = []
    for r in rows:
        if cur and r[0] == cur[-1][0] + 1: cur.append(r)
        else:
            if len(cur) >= 8: bursts.append(cur)
            cur = [r]
    if len(cur) >= 8: bursts.append(cur)
    for b in bursts:
        new = sum(1 for r in b[1:] if r[2] > a.repeat_thresh)
        holds = []; h = 1
        for r in b[1:]:
            if r[2] > a.repeat_thresh: holds.append(h); h = 1
            else: h += 1
        holds.append(h)
        # capturing every present stalls the presents (uncompressed PNG writes), so the wall-clock rate inside a burst
        # says nothing; the cadence does: 24 fps on 30 Hz presents = 4 new images out of 5 (holds 1,1,1,2 repeating).
        # A hold > 2 is a repeated (late) video frame; long runs of 1 in a 30 Hz burst mean frames skipped to catch up.
        trans = len(b) - 1
        print('burst %d-%d (%.2f s .. %.2f s): %d presents, %d new images / %d transitions = %.3f (24/30 pulldown = %.3f); '
              'max hold %d; holds %s' % (b[0][0], b[-1][0], t(b[0][0]), t(b[-1][0]), len(b), new, trans, new / trans,
                                         a.fps / 30.0, max(holds), ''.join(str(min(x, 9)) for x in holds)))
