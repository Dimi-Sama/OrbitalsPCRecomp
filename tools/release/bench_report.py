# Orbitals PC Recomp, a work based on SwitchRecomp by MZ Labs. GNU AGPL v3.0 with the additional terms of NOTICE.txt (LICENSE.txt).
"""A local benchmark and diagnostics summary of one Orbitals session, read from its log.

  python -B tools/release/bench_report.py --game-dir games/Orbitals [--run SESSION_DIR] [--from 60 --to 180] [--tag NAME] [--out DIR]

Reads the session's Orbitals.log (the game folder's, or a launcher session folder's with --run), its Orbitals.ini and the session's
Engine.ini overlay if there is one, and this PC's CPU / GPU / Windows version. Writes orbitals-bench-<tag>-<time>.json and .md in --out
(default: <game dir>/reports). Nothing is sent anywhere: share the files yourself if you want to. Local paths, e-mail addresses and
public IP addresses are masked with the launcher's filter.

What it reports, all from lines the runtime writes anyway, except the 3D resolution: start the game with Play-Orbitals.ps1 -Diagnostics
(or NXRT_VK_LOG_RES=1 in the environment) and the runtime logs the viewport sizes the game draws at every 300 frames.
  - runtime release and commit, GPU, Vulkan driver, the recompiled code (size, SHA-256, entry points)
  - output size, swap chain, present mode; the 3D resolution actually drawn (the viewport with the most draws: 2 views in co-op)
  - frame rate and present intervals p50 / p95 / p99 / max per 300 frames, and over the --from/--to window (seconds of the log)
  - game threads blocked waiting for the GPU, the replay thread's CPU time per frame
  - shader cache misses, translation waits, pipelines created, [RED] lines (the runtime's own warnings), Vulkan errors
"""
import argparse, hashlib, json, os, platform, re, sys, time
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))
from launcher.reports import scrub, system_info, gpu_info   # noqa: E402

T = r'^\[\s*([0-9.]+)\]\s'   # every log line starts with its time in seconds


def lines(log, pattern):
    """(time, match) of every line matching pattern (after the time stamp)"""
    rx = re.compile(T + pattern, re.M)
    return [(float(m.group(1)), m) for m in rx.finditer(log)]


def first(log, pattern):
    m = re.search(pattern, log, re.M)
    return m


def pacing(log):
    """the runtime's frame pacing lines: one per 300 frames"""
    out = []
    for t, m in lines(log, r'\[nvn\] frame pacing up to frame (\d+): ([0-9.]+) presents/s; present interval p50 ([0-9.]+) / p95 ([0-9.]+) / p99 ([0-9.]+) / max ([0-9.]+) ms'):
        out.append({'t': t, 'frame': int(m.group(2)), 'fps': float(m.group(3)), 'p50': float(m.group(4)), 'p95': float(m.group(5)),
                    'p99': float(m.group(6)), 'max': float(m.group(7))})
    return out


def window(rows, lo, hi):
    sel = [r for r in rows if (lo is None or r['t'] >= lo) and (hi is None or r['t'] <= hi)]
    if not sel: return None
    # each row covers 300 presents: the mean frame rate is presents over time, i.e. the harmonic mean of the rows' rates
    fps = len(sel) / sum(1 / r['fps'] for r in sel if r['fps'] > 0) if all(r['fps'] > 0 for r in sel) else 0
    med = lambda k: sorted(r[k] for r in sel)[len(sel) // 2]
    return {'from_s': sel[0]['t'], 'to_s': sel[-1]['t'], 'reports': len(sel), 'fps_mean': round(fps, 2), 'p50_ms_median': med('p50'),
            'p95_ms_median': med('p95'), 'p99_ms_median': med('p99'), 'p99_ms_worst': max(r['p99'] for r in sel), 'max_ms': max(r['max'] for r in sel)}


def resolutions(log, lo, hi):
    """the 3D resolution drawn: per NXRT_VK_LOG_RES report, the viewport sizes with the most draws"""
    seen = {}
    for t, m in lines(log, r'\[vk\] draw resolutions, frames \d+-\d+, (\d+) draws \(viewport in attachment\):(.*?) target binds'):
        if (lo is not None and t < lo) or (hi is not None and t > hi): continue
        for vw, vh, tw, th, pct in re.findall(r' (\d+)x(\d+) in (\d+)x(\d+) ([0-9.]+)%;', m.group(3)):
            k = f'{vw}x{vh} in {tw}x{th}'; seen[k] = seen.get(k, 0) + float(pct)
    if not seen: return None
    total = sum(seen.values())
    return [{'viewport_in_target': k, 'share_pct': round(100 * v / total, 1)} for k, v in sorted(seen.items(), key=lambda kv: -kv[1])[:6]]


def code_module(game):
    for name in ('Orbitals_code.dll', 'Orbitals_code.so'):
        p = game / name
        if p.is_file():
            h = hashlib.sha256()
            with open(p, 'rb') as f:
                for b in iter(lambda: f.read(1 << 20), b''): h.update(b)
            return {'file': name, 'bytes': p.stat().st_size, 'sha256': h.hexdigest()}
    return None


def ini_keys(path, keys):
    if not path.is_file(): return {}
    text = path.read_text(errors='replace')
    return {k: m.group(1).strip() for k in keys for m in [re.search(rf'(?m)^{re.escape(k)}=(.*)$', text)] if m}


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--game-dir', required=True); ap.add_argument('--run', help='a launcher session folder (its Orbitals.log) instead of the game folder')
    ap.add_argument('--from', dest='lo', type=float); ap.add_argument('--to', dest='hi', type=float)
    ap.add_argument('--tag', default='session'); ap.add_argument('--out')
    a = ap.parse_args()
    game = Path(a.game_dir).resolve(); src = Path(a.run).resolve() if a.run else game
    logp = src / 'Orbitals.log'
    if not logp.is_file(): raise SystemExit(f'{logp} not found: start the game once, or give the session folder with --run')
    log = logp.read_text(encoding='utf-8', errors='replace')
    hide = [str(game), str(src), str(REPO), str(Path.home())]
    rows = pacing(log)
    r = {}
    m = first(log, r'release (.*)$'); r['runtime'] = m.group(1).strip() if m else None
    m = first(log, r'\[vk\] device: (.*)$'); r['vulkan_device'] = m.group(1).strip() if m else None
    r['vulkan_gpus'] = [m.group(2) for _, m in lines(log, r'\[vk\] GPU \d+: (.*)$')]
    m = first(log, r'code: (\d+) recompiled entry points'); cm = code_module(game)
    r['recompiled_code'] = dict(cm or {}, entry_points=int(m.group(1)) if m else None)
    m = first(log, r'\[vk\] swapchain (.*)$'); r['swapchain'] = m.group(1).strip() if m else None
    m = first(log, r'\[vk\] window (\d+x\d+) pixels'); r['output_size'] = m.group(1) if m else None
    r['game_ini'] = ini_keys(src / 'Orbitals.ini', ('ue_fps', 'scene_resolution', 'fps_limit', 'resolution', 'shadows'))
    eng = src / 'Orbitals_data' / 'romfs_overlay' / 'Orbitals' / 'Saved' / 'Config' / 'Switch2' / 'Engine.ini'
    m = re.search(r'(?m)^r\.SecondaryScreenPercentage\.GameViewport=(.*)$', eng.read_text(errors='replace')) if eng.is_file() else None
    r['scene_percentage_overlay'] = m.group(1).strip() if m else None
    applied = [m.group(2) for _, m in lines(log, r'Orbitals: internal 3D resolution set to (\d+p)')]
    r['scene_resolution_applied'] = applied[-1] if applied else None
    r['docked'] = (lambda m: m.group(1) if m else None)(first(log, r'--docked=(\d)'))
    r['3d_resolution_drawn'] = resolutions(log, a.lo, a.hi) or 'not logged: start with Play-Orbitals.ps1 -Diagnostics (NXRT_VK_LOG_RES=1)'
    r['frame_pacing_window'] = window(rows, a.lo, a.hi)
    r['frame_pacing_all'] = window(rows, None, None)
    r['frame_pacing_reports'] = rows
    w = [float(m.group(2)) for t, m in lines(log, r'\[nvn\] submit CPU time .*?blocked in SyncWait ([0-9.]+) ms a frame') if (a.lo is None or t >= a.lo) and (a.hi is None or t <= a.hi)]
    r['game_threads_waiting_gpu_ms_per_frame'] = round(sum(w) / len(w), 2) if w else None
    c = [float(m.group(2)) for t, m in lines(log, r'\[vk\] replay command walks per frame: [0-9.]+ M (?:TSC )?cycles(?: on the CPU)?, ([0-9.]+) ms') if (a.lo is None or t >= a.lo) and (a.hi is None or t <= a.hi)]
    r['replay_thread_cpu_ms_per_frame'] = round(sum(c) / len(c), 2) if c else None
    r['shader_cache_misses'] = len(re.findall(r'is not in the shader cache', log))
    tw = re.findall(r'(\d+) waits, ([0-9.]+) s in all', log)
    r['shader_translation_waits'] = {'count': int(tw[-1][0]), 'seconds': float(tw[-1][1])} if tw else None
    pm = re.findall(r'(\d+) graphics \+ (\d+) compute pipelines \(([0-9.]+) ms creating, worst ([0-9.]+) ms\)', log)
    r['pipelines'] = {'graphics': int(pm[-1][0]), 'compute': int(pm[-1][1]), 'ms_creating': float(pm[-1][2]), 'worst_ms': float(pm[-1][3])} if pm else None
    red = []
    for _, m in lines(log, r'(?:\[vk\] )?\[RED\] (.*)$'):
        s = m.group(2).strip()[:240]
        if s not in red: red.append(s)
    r['red_lines'] = {'count': len(re.findall(r'\[RED\]', log)), 'distinct_first_50': red[:50]}
    r['vulkan_errors'] = sorted({m.group(0)[:200] for m in re.finditer(r'(?m)^.*(VUID-|VK_ERROR_|device lost|DEVICE_LOST).*$', log)})[:30]
    r['exit'] = (lambda p: p.read_text(errors='replace')[:2000] if p.is_file() else None)(src / 'exit.json')
    r['system'] = {'machine': system_info(), 'gpu': gpu_info(), 'python': platform.python_version()}
    r['log_seconds'] = float(re.findall(T, log, re.M)[-1]) if re.search(T, log, re.M) else None
    r = json.loads(scrub(json.dumps(r, ensure_ascii=False), hide))
    out = Path(a.out).resolve() if a.out else game / 'reports'
    out.mkdir(parents=True, exist_ok=True)
    stem = out / f'orbitals-bench-{re.sub(r"[^A-Za-z0-9._-]", "_", a.tag)}-{time.strftime("%Y%m%d-%H%M%S")}'
    Path(f'{stem}.json').write_text(json.dumps(r, ensure_ascii=False, indent=1) + '\n', encoding='utf-8')
    fw, fa = r['frame_pacing_window'], r['frame_pacing_all']
    md = [f'# Orbitals benchmark: {a.tag}', '',
          f'- Runtime: {r["runtime"]}', f'- Vulkan device: {r["vulkan_device"]}', f'- CPU / system: {r["system"]["machine"]}',
          f'- Recompiled code: {r["recompiled_code"]}', f'- Output: {r["output_size"]}, swap chain {r["swapchain"]}',
          f'- Game settings: {r["game_ini"]}; 3D percentage overlay {r["scene_percentage_overlay"]}; in-game 3D setting {r["scene_resolution_applied"]}',
          f'- 3D resolution drawn: {r["3d_resolution_drawn"]}', '',
          '| Window | Seconds | FPS | p50 ms | p95 ms | p99 ms (median / worst) | max ms |', '|---|---|---:|---:|---:|---:|---:|']
    for name, x in (('chosen', fw), ('whole log', fa)):
        if x: md.append(f'| {name} | {x["from_s"]:.0f}-{x["to_s"]:.0f} | {x["fps_mean"]} | {x["p50_ms_median"]} | {x["p95_ms_median"]} | {x["p99_ms_median"]} / {x["p99_ms_worst"]} | {x["max_ms"]} |')
    md += ['', f'- Game threads waiting for the GPU: {r["game_threads_waiting_gpu_ms_per_frame"]} ms a frame; replay thread CPU: {r["replay_thread_cpu_ms_per_frame"]} ms a frame',
           f'- Shader cache misses: {r["shader_cache_misses"]}; translation waits: {r["shader_translation_waits"]}; pipelines: {r["pipelines"]}',
           f'- [RED] lines: {r["red_lines"]["count"]} ({len(r["red_lines"]["distinct_first_50"])} distinct); Vulkan errors: {len(r["vulkan_errors"])}', '',
           'Distinct [RED] lines:', ''] + [f'- {s}' for s in r['red_lines']['distinct_first_50']]
    Path(f'{stem}.md').write_text('\n'.join(md) + '\n', encoding='utf-8')
    print(f'{stem}.json\n{stem}.md')


if __name__ == '__main__':
    main()
