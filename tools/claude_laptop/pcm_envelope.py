"""RMS envelope of an SWR_AUDIO_DUMP file (raw float32 stereo, 48 kHz), standard library only.

usage: python pcm_envelope.py audio.f32 [--win 0.5] [--csv out.csv] [--from S --to S] [--thresh-db -50]
Prints the envelope and the sound segments (runs above the threshold, gaps < --gap s merged).
"""
import argparse, array, math, sys

ap = argparse.ArgumentParser()
ap.add_argument('dump'); ap.add_argument('--win', type=float, default=0.5); ap.add_argument('--csv')
ap.add_argument('--thresh-db', type=float, default=-50.0); ap.add_argument('--gap', type=float, default=3.0)
ap.add_argument('--from', dest='t0', type=float, default=0.0); ap.add_argument('--to', dest='t1', type=float, default=1e9)
a = ap.parse_args()

RATE = 48000
n = int(RATE * a.win) * 2                       # floats per window (stereo)
env = []
with open(a.dump, 'rb') as f:
    i = 0
    while True:
        b = f.read(n * 4)
        if len(b) < 8: break
        x = array.array('f'); x.frombytes(b[:len(b) // 4 * 4])
        s = math.fsum(v * v for v in x) / len(x)
        env.append((i * a.win, 10 * math.log10(s) if s > 0 else -200.0))
        i += 1
print('duration %.2f s, %d windows of %.2f s' % (len(env) * a.win, len(env), a.win))
if a.csv:
    with open(a.csv, 'w') as fo:
        fo.write('t,rms_db\n'); fo.writelines('%.2f,%.1f\n' % e for e in env)
segs = []; cur = None
for t, db in env:
    if not (a.t0 <= t <= a.t1): continue
    if db > a.thresh_db:
        if cur and t - cur[1] <= a.gap: cur[1] = t + a.win
        else:
            if cur: segs.append(cur)
            cur = [t, t + a.win]
if cur: segs.append(cur)
for s0, s1 in segs:
    print('sound %8.2f -> %8.2f s  (%.2f s)' % (s0, s1, s1 - s0))
