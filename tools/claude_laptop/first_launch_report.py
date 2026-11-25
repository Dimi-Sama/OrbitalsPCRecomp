"""Compare first launches (flash_repro.py runs): shader cache misses, translation waits, slow frames and pipeline builds, frame times.

  first_launch_report.py RUN_DIR [RUN_DIR ...]

Reads <run>/Orbitals.log (the runtime log), <run>/frames.csv (present times, ms, first column) and <run>/steps/stepper.json (gates).
Frame times: every present interval from the first gate on (the title screen), and those after the last scripted step (the route)."""
import json, os, re, sys


def pct(v, p):
    if not v: return 0.0
    v = sorted(v); return v[min(len(v) - 1, int(p / 100 * len(v)))]


def report(run):
    log = open(os.path.join(run, 'Orbitals.log'), encoding='utf-8', errors='replace').read()
    misses = len(re.findall(r'is not in the shader cache', log))
    waits = [float(x) for x in re.findall(r'waited ([0-9.]+) s for \d+ shaders? being translated', log)]
    total = re.findall(r'(\d+) waits, ([0-9.]+) s in all', log)
    n_wait, t_wait = (int(total[-1][0]), float(total[-1][1])) if total else (len(waits), sum(waits))
    slow = re.findall(r'slow frame \d+: (\d+) ms: .*?pipelines (\d+) ms', log)
    pipe_frames = [(int(a), int(b)) for a, b in slow]
    made = re.findall(r'(\d+) graphics \+ (\d+) compute pipelines \(([0-9.]+) ms creating, worst ([0-9.]+) ms\)', log)
    t = []
    for line in open(os.path.join(run, 'frames.csv')):
        try: t.append(float(line.split(',')[0]))
        except ValueError: pass
    ev = json.load(open(os.path.join(run, 'steps', 'stepper.json'))).get('events', []) if os.path.exists(os.path.join(run, 'steps', 'stepper.json')) else []
    gates = {e['step']: e['t'] for e in ev if e.get('event') == 'gate'}
    dt = [b - a for a, b in zip(t, t[1:])]
    out = {'run': os.path.basename(run.rstrip('/\\')), 'shader misses': misses, 'translation waits': n_wait, 'seconds waited': round(t_wait, 1),
           'slow frames': len(pipe_frames), 'slow frames with pipeline builds': sum(1 for a, b in pipe_frames if b > 0),
           'pipeline ms in slow frames': sum(b for _, b in pipe_frames)}
    if made: g, c, ms, worst = made[-1]; out.update({'pipelines made': int(g) + int(c), 'ms creating pipelines': float(ms), 'worst pipeline ms': float(worst)})
    for name, sel in (('all', dt), ('last 60 s', [d for d, x in zip(dt, t[1:]) if x >= t[-1] - 60000] if t else [])):
        out[f'frames ({name})'] = len(sel)
        out[f'p50 ms ({name})'] = round(pct(sel, 50), 1); out[f'p95 ms ({name})'] = round(pct(sel, 95), 1)
        out[f'p99 ms ({name})'] = round(pct(sel, 99), 1); out[f'max ms ({name})'] = round(max(sel) if sel else 0, 1)
        out[f'frames > 100 ms ({name})'] = sum(1 for d in sel if d > 100); out[f'frames > 500 ms ({name})'] = sum(1 for d in sel if d > 500)
    out['gates (s)'] = {k: round(v, 1) for k, v in gates.items()}
    return out


def main():
    rows = [report(r) for r in sys.argv[1:]]
    keys = [k for k in rows[0] if k != 'gates (s)']
    w = max(len(k) for k in keys)
    print(' ' * w + ' | ' + ' | '.join(f'{r["run"]:>14}' for r in rows))
    for k in keys[1:]:
        print(f'{k:<{w}} | ' + ' | '.join(f'{str(r.get(k, "-")):>14}' for r in rows))
    for r in rows: print(r['run'], 'gates', r['gates (s)'])


if __name__ == '__main__':
    main()
