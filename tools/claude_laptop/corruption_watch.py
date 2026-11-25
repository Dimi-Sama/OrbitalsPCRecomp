"""Pass dump at the first corrupted frames of a running test (standard library only).

usage: python corruption_watch.py RUN_DIR [--region left|right|full] [--dark 32] [--bright 50] [--frames 4] [--max 3]

Follows RUN_DIR/frames/shot-*.png as run-orbitals.ps1 writes them, measures the mean brightness of a region (left half =
player 1 in split screen), and when it drops under --dark right after a capture above --bright (a view that turns black:
the missing / stretched geometry of the 'vertex explosion'), asks the runtime through \\\\.\\pipe\\swr_ctl for a pass dump of
the next --frames frames and requests one capture per present meanwhile (NXRT_VK_SHOT_FILE, RUN_DIR/shot-request.txt).
The vks PNG files are written uncompressed (stored deflate, filter 0), so a few pixels are read straight from the data.
"""
import argparse, glob, os, re, struct, sys, time, zlib

ap = argparse.ArgumentParser(); ap.add_argument('run'); ap.add_argument('--region', default='left')
ap.add_argument('--dark', type=float, default=32); ap.add_argument('--bright', type=float, default=50)
ap.add_argument('--frames', type=int, default=4); ap.add_argument('--cmd', default='passdump', help='passdump (N frames) or texdump (pass copies with NXRT_VK_TD_PASSES=1)'); ap.add_argument('--repeat', type=int, default=1, help='texdump requests per detection, 0.25 s apart'); ap.add_argument('--max', type=int, default=3); ap.add_argument('--timeout', type=float, default=900)
a = ap.parse_args()
frames = os.path.join(a.run, 'frames'); ctl = os.path.join(a.run, 'shot-request.txt'); log = open(os.path.join(a.run, 'corruption-watch.txt'), 'a')


def say(s):
    line = '%s %s' % (time.strftime('%H:%M:%S'), s); print(line, flush=True); log.write(line + '\n'); log.flush()


def brightness(path):
    with open(path, 'rb') as f: b = f.read()
    w, h = struct.unpack('>II', b[16:24]); data = bytearray(); i = 8
    while i < len(b):
        n, t = struct.unpack('>I4s', b[i:i + 8])
        if t == b'IDAT': data += b[i + 8:i + 8 + n]
        i += 12 + n
    raw = zlib.decompress(bytes(data)); bpp = 4; stride = 1 + w * bpp
    x0, x1 = {'left': (0, w // 2), 'right': (w // 2, w), 'full': (0, w)}[a.region]
    s = k = 0
    for y in range(h // 8, h, h // 24):
        row = y * stride + 1
        for x in range(x0, x1, max(1, (x1 - x0) // 48)):
            o = row + x * bpp; s += (raw[o] * 77 + raw[o + 1] * 150 + raw[o + 2] * 29) >> 8; k += 1
    return s / k


def passdump(n):
    try:
        with open(r'\\.\pipe\swr_ctl', 'r+b', buffering=0) as p:
            p.write((b'passdump %d\n' % n) if a.cmd == 'passdump' else (a.cmd.encode() + b'\n'))
            try: return p.read(4096).decode(errors='replace').strip()
            except OSError: return 'sent'
    except OSError as e:
        return 'pipe error: %s' % e


seen = set(); prev = None; fired = 0; last_fire = 0; burst_until = 0; t0 = time.time()
say('watching %s (region %s, dark < %g after bright > %g)' % (frames, a.region, a.dark, a.bright))
while time.time() - t0 < a.timeout and fired <= a.max:
    if time.time() < burst_until and not os.path.exists(ctl):
        open(ctl, 'w').close()
    files = sorted(glob.glob(os.path.join(frames, 'shot-*.png')))
    new = [f for f in files if f not in seen]
    for f in new[:-1] if new else []:   # the newest may still be being written
        seen.add(f)
        try: v = brightness(f)
        except Exception: continue
        n = int(re.search(r'shot-(\d+)', f).group(1))
        if prev is not None and prev > a.bright and v < a.dark and fired < a.max and time.time() - last_fire > 3:
            fired += 1; last_fire = time.time(); burst_until = time.time() + 1.0
            say('present %d: %s %.1f after %.1f -> %s %d: %s' % (n, a.region, v, prev, a.cmd, a.frames, passdump(a.frames)))
            for k in range(a.repeat - 1):
                time.sleep(0.25); say('  again: %s' % passdump(a.frames))
        prev = v
    if fired >= a.max and time.time() > burst_until + 2: break
    if os.path.exists(os.path.join(a.run, 'stderr.txt')): break   # the run is over
    time.sleep(0.03)
say('done, %d dumps' % fired)
