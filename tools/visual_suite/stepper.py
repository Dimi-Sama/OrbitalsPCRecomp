#!/usr/bin/env python3
"""Scripted test inputs in steps, each sent when the game shows the screen it expects (a first session pauses for shaders: fixed times drift).

The runtime reads the steps from a file (--script_file, backend_win32.c script_file_poll): a step name, then player 1's and player 2's
scripts in the --script format (ms:hexmask[/hold_ms],...), timed from the moment the step is read, on a clock that leaves out the renderer's
waits for shaders. This harness asks the runtime for captures (NXRT_VK_SHOT_FILE, holding the path to write), recognises the screen by
comparing a coarse grey grid of the capture with signatures taken from known captures (normalised correlation: a darker or brighter
picture of the same screen still matches), and writes the next step when its gate matches.

  stepper.py sig  --out sigs.json --name title shot.png [--crop x0 y0 x1 y1]   make or update a signature (crop in 0..1 of the picture)
  stepper.py classify --sigs sigs.json shot.png ...                           scores of each signature (to choose thresholds)
  stepper.py run  --scenario s.json --sigs sigs.json --script-file F --shot-file F --log Orbitals.log --out DIR [--timeout S]
  stepper.py compare A.png B.png [--views 2]                                   brightness and correlation per view (corridor checks)

Signatures are derived from the game's pictures: keep them with the local test data, not in the repository. Standard library only.
"""
import argparse, json, math, os, re, struct, sys, time, zlib

GW, GH = 48, 27


def read_png(path):
    data = open(path, 'rb').read()
    if data[:8] != b'\x89PNG\r\n\x1a\n':
        raise ValueError(f'{path}: not a PNG')
    pos, idat, w = 8, [], 0
    while pos + 8 <= len(data):
        n = int.from_bytes(data[pos:pos + 4], 'big'); t = data[pos + 4:pos + 8]; c = data[pos + 8:pos + 8 + n]; pos += 12 + n
        if t == b'IHDR':
            w, h = struct.unpack('>II', c[:8]); depth, ctype = c[8], c[9]
            if depth != 8 or ctype not in (2, 6):
                raise ValueError(f'{path}: only 8-bit RGB / RGBA')
        elif t == b'IDAT':
            idat.append(c)
        elif t == b'IEND':
            break
    raw = bytearray(zlib.decompress(b''.join(idat))); bpp = 4 if ctype == 6 else 3; stride = w * bpp + 1
    if any(raw[y * stride] for y in range(h)):   # filtered rows (other writers): undo them (slow, pure Python)
        prev = bytearray(w * bpp)
        for y in range(h):
            f = raw[y * stride]; row = raw[y * stride + 1:(y + 1) * stride]
            for i in range(len(row)):
                a = row[i - bpp] if i >= bpp else 0; b = prev[i]; cc = prev[i - bpp] if i >= bpp else 0
                if f == 1: row[i] = (row[i] + a) & 255
                elif f == 2: row[i] = (row[i] + b) & 255
                elif f == 3: row[i] = (row[i] + (a + b) // 2) & 255
                elif f == 4:
                    p = a + b - cc; pa, pb, pc = abs(p - a), abs(p - b), abs(p - cc)
                    row[i] = (row[i] + (a if pa <= pb and pa <= pc else b if pb <= pc else cc)) & 255
            raw[y * stride] = 0; raw[y * stride + 1:(y + 1) * stride] = row; prev = row
    return w, h, bpp, stride, raw


def grid(img, crop=(0, 0, 1, 1), gw=GW, gh=GH):
    w, h, bpp, stride, raw = img
    x0, y0, x1, y1 = crop; out = []
    for gy in range(gh):
        for gx in range(gw):
            s = 0
            for sy in (0.25, 0.5, 0.75):
                y = min(h - 1, int((y0 + (y1 - y0) * (gy + sy) / gh) * h))
                for sx in (0.25, 0.5, 0.75):
                    x = min(w - 1, int((x0 + (x1 - x0) * (gx + sx) / gw) * w)); o = y * stride + 1 + x * bpp
                    s += raw[o] * 299 + raw[o + 1] * 587 + raw[o + 2] * 114
            out.append(s / 9000.0)
    return out


def ncc(a, b):
    n = len(a); ma = sum(a) / n; mb = sum(b) / n
    va = sum((x - ma) ** 2 for x in a); vb = sum((x - mb) ** 2 for x in b)
    if va < n or vb < n:   # flat (a black screen): equal only to another flat one of about the same level
        return 1.0 if va < n and vb < n and abs(ma - mb) < 12 else 0.0
    return sum((x - ma) * (y - mb) for x, y in zip(a, b)) / math.sqrt(va * vb)


def mean(v):
    return sum(v) / len(v)


def scores(img, sigs):
    return {k: ncc(grid(img, tuple(s['crop'])), s['grid']) for k, s in sigs.items()}


def wait_file(path, timeout=20.0):
    t0 = time.time(); last = -1
    while time.time() - t0 < timeout:
        try:
            n = os.path.getsize(path)
        except OSError:
            n = -1
        if n > 0 and n == last:
            return True
        last = n; time.sleep(0.25)
    return False


class Run:
    def __init__(self, a):
        self.a = a; self.sigs = json.load(open(a.sigs, encoding='utf-8-sig')); self.sc = json.load(open(a.scenario, encoding='utf-8-sig'))
        os.makedirs(a.out, exist_ok=True); self.n = 0; self.t0 = time.time(); self.events = []

    def note(self, **kw):
        kw['t'] = round(time.time() - self.t0, 2); self.events.append(kw)
        print(json.dumps(kw, ensure_ascii=False), flush=True)
        json.dump({'scenario': self.a.scenario, 'events': self.events}, open(os.path.join(self.a.out, 'stepper.json'), 'w'), indent=1, ensure_ascii=False)

    def shot(self, name):
        self.n += 1; p = os.path.join(self.a.out, f'{self.n:04d}-{name}.png')
        with open(self.a.shot_file, 'w') as f:
            f.write(p)
        t = time.time()
        while os.path.exists(self.a.shot_file):   # taken at the next present (none while the game is paused for shaders)
            if time.time() - t > 60:
                return None
            time.sleep(0.1)
        return p if wait_file(p) else None

    def send(self, step):
        tmp = self.a.script_file + '.tmp'
        with open(tmp, 'w') as f:
            f.write(f"{step['name']}\n{step.get('p1', '')}\n{step.get('p2', '')}\n")
        os.replace(tmp, self.a.script_file)
        self.note(event='step', step=step['name'])

    def log_clock(self):   # the script clock of the latest input change (backend_win32.c "input test: N ms")
        try:
            tail = open(self.a.log, 'rb').read()[-200000:].decode('utf-8', 'replace')
        except OSError:
            return None, None
        st = re.findall(r"input script file: step \d+ '([^']*)'", tail)
        ms = re.findall(r'input test: (\d+) ms', tail)
        return (st[-1] if st else None), (int(ms[-1]) if ms else None)

    def gate(self, step, prev=None):
        """Until the step's screen shows. A previous step whose input the game missed (its screen still shows after `retry` seconds,
        default 25; a menu can show before it takes input) is sent again, at most 3 times."""
        g = step.get('gate')
        if not g:
            return True
        deadline = time.time() + g.get('timeout', self.a.timeout); keep_every = 10.0; kept = 0.0
        retry = g.get('retry', 25); last_send = time.time(); resent = 0
        pg = (prev or {}).get('gate') or {}
        can_resend = retry > 0 and prev is not None and 'any' in pg and ('p1' in prev or 'p2' in prev)
        while time.time() < deadline:
            p = self.shot(step['name'] + '-gate')
            if not p:
                self.note(event='no-capture', step=step['name']); continue
            img = read_png(p)
            if 'leave' in g:   # until the game no longer shows any of these screens
                s = scores(img, {k: self.sigs[k] for k in g['leave']}); best = max(s, key=s.get); ok = s[best] < g.get('max', 0.4)
            else:
                s = scores(img, {k: self.sigs[k] for k in g['any']}); best = max(s, key=s.get); ok = s[best] >= g.get('min', 0.8)
            if ok:
                self.note(event='gate', step=step['name'], matched=best, score=round(s[best], 3), shot=os.path.basename(p))
                return True
            if can_resend and resent < 3 and time.time() - last_send >= retry:
                ps = scores(img, {k: self.sigs[k] for k in pg['any']})
                if max(ps.values()) >= pg.get('resend_min', pg.get('min', 0.8)):   # resend_min: the screen may look less like its signature once the input half-landed
                    resent += 1; last_send = time.time()
                    self.note(event='resend', step=prev['name'], waiting_for=step['name'], count=resent)
                    self.send(prev)
            if time.time() - kept >= keep_every:
                kept = time.time()   # one capture kept every 10 s while waiting: the record of what the game showed
            else:
                os.remove(p)
            time.sleep(g.get('poll', 1.0))
        self.note(event='timeout', step=step['name']); return False

    def run(self):
        prev = None
        for step in self.sc['steps']:
            if not self.gate(step, prev):
                return 1
            prev = step
            if step.get('delay'):
                time.sleep(step['delay'])
            if 'p1' in step or 'p2' in step:
                self.send(step)
            if step.get('wait_script_ms'):   # until the script clock passes this point of the step (inputs done, shader pauses left out)
                t = time.time()
                while True:
                    name, ms = self.log_clock()
                    if name == step['name'] and ms is not None and ms >= step['wait_script_ms']:
                        break
                    if time.time() - t > self.a.timeout:
                        self.note(event='timeout', step=step['name'], waiting='script'); return 1
                    time.sleep(0.5)
                self.note(event='script-done', step=step['name'], ms=ms)
            for c in step.get('captures', []):
                time.sleep(c.get('after', 0)); p = self.shot(c['name'])
                self.note(event='capture', step=step['name'], name=c['name'], shot=os.path.basename(p) if p else None)
        self.note(event='done'); return 0


def views(img, n):
    w = 1.0 / n
    return [(i * w, 0, (i + 1) * w, 1) for i in range(n)]


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter); sub = ap.add_subparsers(dest='cmd', required=True)
    s = sub.add_parser('sig'); s.add_argument('--out', required=True); s.add_argument('--name', required=True); s.add_argument('png'); s.add_argument('--crop', nargs=4, type=float, default=[0, 0, 1, 1])
    c = sub.add_parser('classify'); c.add_argument('--sigs', required=True); c.add_argument('png', nargs='+')
    r = sub.add_parser('run')
    for k in ('scenario', 'sigs', 'script-file', 'shot-file', 'log', 'out'):
        r.add_argument('--' + k, required=True)
    r.add_argument('--timeout', type=float, default=900)
    m = sub.add_parser('compare'); m.add_argument('a'); m.add_argument('b'); m.add_argument('--views', type=int, default=1)
    a = ap.parse_args()
    if a.cmd == 'sig':
        sigs = json.load(open(a.out)) if os.path.exists(a.out) else {}
        sigs[a.name] = {'crop': a.crop, 'grid': [round(v, 1) for v in grid(read_png(a.png), tuple(a.crop))], 'from': os.path.basename(a.png)}
        json.dump(sigs, open(a.out, 'w'), indent=0); print(f'{a.name}: {len(sigs[a.name]["grid"])} cells, mean {mean(sigs[a.name]["grid"]):.1f}')
    elif a.cmd == 'classify':
        sigs = json.load(open(a.sigs))
        for p in a.png:
            s = scores(read_png(p), sigs); print(os.path.basename(p), ' '.join(f'{k}={v:.2f}' for k, v in sorted(s.items(), key=lambda kv: -kv[1])))
    elif a.cmd == 'run':
        sys.exit(Run(a).run())
    elif a.cmd == 'compare':
        ia, ib = read_png(a.a), read_png(a.b); out = []
        for i, v in enumerate(views(ia, a.views)):
            ga, gb = grid(ia, v), grid(ib, v)
            out.append({'view': i + 1, 'luma_a': round(mean(ga), 1), 'luma_b': round(mean(gb), 1), 'ratio': round(mean(ga) / max(mean(gb), 0.1), 3), 'correlation': round(ncc(ga, gb), 3),
                        'mean_abs_diff': round(mean([abs(x - y) for x, y in zip(ga, gb)]), 1)})
        print(json.dumps(out, indent=1))


if __name__ == '__main__':
    main()
