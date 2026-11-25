"""Drive a game held open by flash_repro.py --hold: send one input step, wait until the runtime's script clock has played it, capture.

  drive_step.py OUT NAME --p1 SCRIPT --p2 SCRIPT [--ms N] [--no-shot]

SCRIPT is the runtime's --script format (ms:hexmask[/hold_ms],...): button bits 0 A, 1 B, 2 X, 3 Y ... and the sticks as buttons, 40/42 left
stick x-/x+, 43/41 y-/y+, 44/46 right stick x-/x+, 47/45 y-/y+ (backend_win32.c). --ms: how much of the step's script clock to wait for
(default: the last event plus its hold). The capture goes to OUT/drive/NNNN-NAME.png and its path is printed. quit: touch OUT/quit.
"""
import argparse, os, re, sys, time
from pathlib import Path


def last_ms(script):
    end = 0
    for ev in filter(None, script.split(',')):
        t, _, rest = ev.partition(':'); hold = int(rest.split('/')[1]) if '/' in rest else 100
        end = max(end, int(t) + hold)
    return end


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('out', type=Path); ap.add_argument('name')
    ap.add_argument('--p1', default=''); ap.add_argument('--p2', default=''); ap.add_argument('--ms', type=int); ap.add_argument('--no-shot', action='store_true')
    a = ap.parse_args(); a.out = a.out.resolve()   # the runtime writes captures relative to its own folder
    run = json_game(a.out)
    log = Path(run) / 'Orbitals.log'
    step = a.out / 'step-input.txt'; tmp = step.with_suffix('.tmp')
    tmp.write_text(f'{a.name}\n{a.p1}\n{a.p2}\n'); os.replace(tmp, step)
    want = a.ms if a.ms is not None else max(last_ms(a.p1), last_ms(a.p2))
    t0 = time.time()
    while want and time.time() - t0 < 120 + want / 1000:   # no input to play: capture at once
        tail = log.read_bytes()[-200000:].decode('utf-8', 'replace')
        st = re.findall(r"input script file: step \d+ '([^']*)'", tail); ms = re.findall(r'input test: (\d+) ms', tail)
        if st and st[-1] == a.name and ms and int(ms[-1]) >= want:
            break
        time.sleep(0.2)
    if a.no_shot:
        return
    d = a.out / 'drive'; d.mkdir(exist_ok=True)
    n = len(list(d.glob('*.png'))) + 1; p = d / f'{n:04d}-{a.name}.png'
    req = a.out / 'shot-request.txt'; tmp = req.with_suffix('.tmp'); tmp.write_text(str(p)); os.replace(tmp, req)
    t = time.time()
    while (req.exists() or not p.exists()) and time.time() - t < 60:
        time.sleep(0.1)
    time.sleep(0.5)
    print(p)


def json_game(out):
    import json
    return str(Path(json.loads((out / 'run.json').read_text())['game']))


if __name__ == '__main__':
    main()
