# Orbitals PC Recomp, a work based on SwitchRecomp by MZ Labs. GNU AGPL v3.0 with the additional terms of NOTICE.txt (LICENSE.txt).
"""Visual regression suite: captures of the scripted path compared between two builds (GRAPHICS_ACCURACY.md).

Standard library only (the runtime writes its PNGs uncompressed-filter RGBA, which decode fast enough in Python).

  python tools/visual_suite/vsuite.py index   <run>                         per capture: time, thumbnail, statistics
  python tools/visual_suite/vsuite.py compare <ref run> <new run> [--out dir] [--scenes tools/visual_suite/scenes.json] [--tol 1.5]
  python tools/visual_suite/vsuite.py sheet   <run> [--out file.html]       contact sheet of one run

A run is a folder made by tools/claude_laptop/run-orbitals.ps1 (or rerun.ps1 / run_suite.ps1): frames/shot-<present>.png and frames.csv (the time of each
present). Captures of two runs are matched by time on the path (the inputs are scripted in real time, so the same time is the same moment of the game,
give or take the frames each build takes; a camera that moved shows as a difference spread over the picture, a missing object as a local one).

Per pair: mean absolute difference (0-255, per channel byte), share of pixels differing by more than 24, the same per screen half (the two co-op views),
and the flags that matter for a release: a black or nearly black view, a view whose content disappeared (most of it flat), a large local difference.
Thresholds are heuristics: a flagged pair is a picture to look at, not a verdict.
"""
import argparse, csv, html, json, os, struct, sys, zlib

THUMB_W = 480


def read_png(path):
    data = open(path, 'rb').read()
    if data[:8] != b'\x89PNG\r\n\x1a\n': raise ValueError(f'{path}: not a PNG')
    pos, idat, w, h, ctype = 8, [], 0, 0, 6
    while pos < len(data):
        n, typ = struct.unpack('>I4s', data[pos:pos + 8])
        body = data[pos + 8:pos + 8 + n]
        if typ == b'IHDR':
            w, h, depth, ctype = struct.unpack('>IIBB', body[:10])
            if depth != 8 or ctype not in (2, 6): raise ValueError(f'{path}: 8-bit RGB/RGBA only')
        elif typ == b'IDAT': idat.append(body)
        pos += 12 + n
    bpp = 4 if ctype == 6 else 3
    raw = zlib.decompress(b''.join(idat)); stride = w * bpp
    rows, prev, i = [], bytes(stride), 0
    for _ in range(h):
        ft = raw[i]; line = raw[i + 1:i + 1 + stride]; i += 1 + stride
        if ft == 0: cur = line
        else:
            cur = bytearray(line)
            if ft == 1:
                for x in range(bpp, stride): cur[x] = (cur[x] + cur[x - bpp]) & 255
            elif ft == 2:
                for x in range(stride): cur[x] = (cur[x] + prev[x]) & 255
            elif ft == 3:
                for x in range(stride): cur[x] = (cur[x] + ((cur[x - bpp] if x >= bpp else 0) + prev[x]) // 2) & 255
            elif ft == 4:
                for x in range(stride):
                    a = cur[x - bpp] if x >= bpp else 0; b = prev[x]; c = prev[x - bpp] if x >= bpp else 0
                    p = a + b - c; pa, pb, pc = abs(p - a), abs(p - b), abs(p - c)
                    cur[x] = (cur[x] + (a if pa <= pb and pa <= pc else b if pb <= pc else c)) & 255
            cur = bytes(cur)
        rows.append(cur); prev = cur
    return w, h, bpp, rows


def write_png(path, w, h, rgb_rows):
    raw = b''.join(b'\0' + r for r in rgb_rows)
    def chunk(t, b): return struct.pack('>I', len(b)) + t + b + struct.pack('>I', zlib.crc32(t + b) & 0xffffffff)
    open(path, 'wb').write(b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', struct.pack('>IIBBBBB', w, h, 8, 2, 0, 0, 0)) + chunk(b'IDAT', zlib.compress(raw, 6)) + chunk(b'IEND', b''))


def present_times(run):
    t = {}
    p = os.path.join(run, 'frames.csv')
    if os.path.exists(p):
        for row in csv.DictReader(open(p)):
            try: t[int(row['n'])] = float(row['ms']) / 1000
            except (KeyError, ValueError): pass
    return t


def shots(run):
    d = os.path.join(run, 'frames'); t = present_times(run); out = []
    for f in sorted(os.listdir(d)) if os.path.isdir(d) else []:
        if f.startswith('shot-') and f.endswith('.png'):
            n = int(f[5:-4]); out.append((t.get(n), n, os.path.join(d, f)))
    return [s for s in out if s[0] is not None]


def sample(img, step=4):
    """RGB samples every step pixels (rows and columns): (w', h', list of rows of RGB bytes)."""
    w, h, bpp, rows = img
    out = []
    for y in range(0, h, step):
        r = rows[y]; out.append(bytes(b for x in range(0, w, step) for b in r[x * bpp:x * bpp + 3]))
    return (w + step - 1) // step, len(out), out


def stats(img):
    sw, sh, s = sample(img, 8)
    half = sw // 2; res = {}
    for name, x0, x1 in (('all', 0, sw), ('left', 0, half), ('right', half, sw)):
        lum, flat, n = 0, 0, 0
        for r in s:
            px = r[x0 * 3:x1 * 3]
            for k in range(0, len(px), 3):
                l = (px[k] * 2 + px[k + 1] * 5 + px[k + 2]) >> 3; lum += l; n += 1
                if l < 6: flat += 1
        res[name] = {'mean_lum': round(lum / max(n, 1), 1), 'black_share': round(flat / max(n, 1), 3)}
    return res


def thumb(img, path):
    w, h, bpp, rows = img
    tw = THUMB_W; th = h * tw // w; out = []
    for y in range(th):
        r = rows[y * h // th]; out.append(bytes(b for x in range(tw) for b in r[(x * w // tw) * bpp:(x * w // tw) * bpp + 3]))
    write_png(path, tw, th, out)


def index(run):
    out = os.path.join(run, 'vsuite'); os.makedirs(out, exist_ok=True)
    ip = os.path.join(out, 'index.json')
    old = json.load(open(ip)) if os.path.exists(ip) else {}
    res = {}
    for t, n, p in shots(run):
        key = os.path.basename(p)
        if key in old and os.path.exists(os.path.join(out, 'thumb-' + key)): res[key] = old[key]; continue
        img = read_png(p); tp = os.path.join(out, 'thumb-' + key); thumb(img, tp)
        res[key] = {'t': round(t, 3), 'present': n, 'size': [img[0], img[1]], 'stats': stats(img)}
        print(f'  {key} t={t:.1f} s  lum {res[key]["stats"]["all"]["mean_lum"]}', flush=True)
    json.dump(res, open(ip, 'w'), indent=1)
    return res


def diff(a, b):
    if a[:2] != b[:2]: return None
    sw, sh, sa = sample(a, 4); _, _, sb = sample(b, 4)
    half = sw // 2; res = {}
    for name, x0, x1 in (('all', 0, sw), ('left', 0, half), ('right', half, sw)):
        tot, big, n = 0, 0, 0
        for ra, rb in zip(sa, sb):
            pa, pb = ra[x0 * 3:x1 * 3], rb[x0 * 3:x1 * 3]
            for k in range(0, len(pa), 3):
                d = max(abs(pa[k] - pb[k]), abs(pa[k + 1] - pb[k + 1]), abs(pa[k + 2] - pb[k + 2]))
                tot += abs(pa[k] - pb[k]) + abs(pa[k + 1] - pb[k + 1]) + abs(pa[k + 2] - pb[k + 2]); n += 1
                if d > 24: big += 1
        res[name] = {'mad': round(tot / max(3 * n, 1), 2), 'changed': round(big / max(n, 1), 4)}
    return res


def load_scenes(path):
    if not path or not os.path.exists(path): return []
    return json.load(open(path))['scenes']


def scene_of(scenes, t):
    for s in scenes:
        if s['from'] <= t <= s['to']: return s['name']
    return ''


def compare(ref, new, out, scenes_path, tol):
    os.makedirs(out, exist_ok=True)
    print(f'indexing {ref}'); ia = index(ref)
    print(f'indexing {new}'); ib = index(new)
    scenes = load_scenes(scenes_path)
    sa = sorted(((v['t'], k) for k, v in ia.items())); sb = sorted(((v['t'], k) for k, v in ib.items()))
    rows = []
    for t, ka in sa:
        best = min(sb, key=lambda x: abs(x[0] - t), default=None)
        if not best or abs(best[0] - t) > tol: rows.append({'t': t, 'ref': ka, 'new': None}); continue
        kb = best[1]
        d = diff(read_png(os.path.join(ref, 'frames', ka)), read_png(os.path.join(new, 'frames', kb)))
        flags = []
        for side in ('left', 'right'):
            sa_, sb_ = ia[ka]['stats'][side], ib[kb]['stats'][side]
            if sb_['black_share'] > 0.9 and sa_['black_share'] < 0.5: flags.append(f'{side} view black (ref not)')
            if sb_['mean_lum'] < sa_['mean_lum'] * 0.5 and sa_['mean_lum'] > 20: flags.append(f'{side} view much darker')
        if d and d['all']['changed'] > 0.25: flags.append('large difference (camera / timing or a real change: look)')
        rows.append({'t': t, 'dt': round(best[0] - t, 2), 'ref': ka, 'new': kb, 'scene': scene_of(scenes, t), 'diff': d, 'flags': flags})
    rep = {'ref': os.path.abspath(ref), 'new': os.path.abspath(new), 'pairs': rows}
    json.dump(rep, open(os.path.join(out, 'compare.json'), 'w'), indent=1)
    # the HTML page: side by side thumbnails (copied next to it), the numbers and the flags
    import shutil
    for run, tag in ((ref, 'a'), (new, 'b')):
        for f in os.listdir(os.path.join(run, 'vsuite')):
            if f.startswith('thumb-'): shutil.copyfile(os.path.join(run, 'vsuite', f), os.path.join(out, f'{tag}-{f[6:]}'))
    h = ['<!doctype html><meta charset=utf-8><title>Visual comparison</title><style>body{font:13px system-ui;background:#111;color:#ddd}'
         'td{vertical-align:top;padding:4px}img{width:360px}.f{color:#f86}</style>',
         f'<h1>Visual comparison</h1><p>ref: {html.escape(ref)}<br>new: {html.escape(new)}</p><table>']
    for r in rows:
        if not r['new']: h.append(f'<tr><td>{r["t"]:.1f} s</td><td><img src="a-{r["ref"]}"></td><td class=f>no capture within {tol} s</td></tr>'); continue
        d = r['diff'] or {}
        num = ' '.join(f'{k}: MAD {v["mad"]} changed {v["changed"] * 100:.1f}%' for k, v in d.items())
        h.append(f'<tr><td>{r["t"]:.1f} s<br>{html.escape(r["scene"])}<br>dt {r["dt"]} s</td><td><img src="a-{r["ref"]}"></td><td><img src="b-{r["new"]}"></td>'
                 f'<td>{num}<br><span class=f>{html.escape("; ".join(r["flags"]))}</span></td></tr>')
    h.append('</table>')
    open(os.path.join(out, 'compare.html'), 'w', encoding='utf-8').write('\n'.join(h))
    flagged = [r for r in rows if r.get('flags') or not r['new']]
    print(f'{len(rows)} captures, {len(flagged)} flagged; report {os.path.join(out, "compare.html")}')
    for r in flagged: print(f'  {r["t"]:.1f} s {r.get("scene", "")}: {"; ".join(r.get("flags") or ["unmatched"])}')
    return rep


def sheet(run, out):
    ix = index(run)
    out = out or os.path.join(run, 'vsuite', 'sheet.html')
    h = ['<!doctype html><meta charset=utf-8><title>Captures</title><style>body{font:12px system-ui;background:#111;color:#ddd}div{display:inline-block;margin:3px}img{width:320px;display:block}</style>']
    for k, v in sorted(ix.items(), key=lambda kv: kv[1]['t']):
        h.append(f'<div><img src="thumb-{k}">{v["t"]:.1f} s · present {v["present"]} · lum {v["stats"]["all"]["mean_lum"]}</div>')
    open(out, 'w', encoding='utf-8').write('\n'.join(h)); print(out)


def main():
    ap = argparse.ArgumentParser(); sub = ap.add_subparsers(dest='cmd', required=True)
    p = sub.add_parser('index'); p.add_argument('run')
    p = sub.add_parser('compare'); p.add_argument('ref'); p.add_argument('new'); p.add_argument('--out'); p.add_argument('--tol', type=float, default=1.5)
    p.add_argument('--scenes', default=os.path.join(os.path.dirname(os.path.abspath(__file__)), 'scenes.json'))
    p = sub.add_parser('sheet'); p.add_argument('run'); p.add_argument('--out')
    a = ap.parse_args()
    if a.cmd == 'index': index(a.run)
    elif a.cmd == 'compare': compare(a.ref, a.new, a.out or os.path.join(a.new, 'vsuite', 'compare'), a.scenes, a.tol)
    else: sheet(a.run, a.out)


if __name__ == '__main__':
    main()
