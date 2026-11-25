"""Reach a scene with the visual stepper, then capture every present for a while (frame-by-frame evidence of short artefacts).

  flash_repro.py --game <kit>/Orbitals --scenario s.json --sigs sigs.json --out <new dir> [--burst 25] [--env K=V ...]

The scenario's last step gates on the scene; once the stepper is done, each present is captured (the runtime takes one capture at the
next present when NXRT_VK_SHOT_FILE exists, then deletes it: the next request is written at once) to <out>/burst/NNNNN.png, with the
present number of each in <out>/burst.json. With --flight N instead, the game runs at its own pace and the flight recorder (vk_flight.c: the last
frames as shown, 1280x720, and the draws of each) is written every N seconds through the control channel, after asking it which of those frames
flashed (gamectl flashes): <kit>/flight/<time>_scene-K, listed in <out>/flight.json. The game is then closed through its window, and the kit's log
and frame times copied.
"""
import argparse, ctypes, json, os, re, shutil, subprocess, sys, time
from ctypes import wintypes
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from coop_cores import close_window
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from gamectl import ctl


def exe_pids(exe):
    """The processes running this executable (the loader can start the game again as another process: closing the first one is not enough)."""
    k = ctypes.WinDLL('kernel32', use_last_error=True); pids = (wintypes.DWORD * 4096)(); got = wintypes.DWORD()
    ctypes.WinDLL('psapi').EnumProcesses(pids, ctypes.sizeof(pids), ctypes.byref(got)); out = []
    for pid in pids[:got.value // 4]:
        h = k.OpenProcess(0x1000, False, pid)   # PROCESS_QUERY_LIMITED_INFORMATION
        if not h:
            continue
        buf = ctypes.create_unicode_buffer(1024); n = wintypes.DWORD(1024)
        if k.QueryFullProcessImageNameW(h, 0, buf, ctypes.byref(n)) and os.path.normcase(buf.value) == os.path.normcase(str(exe)):
            out.append(pid)
        k.CloseHandle(h)
    return out


def stop_game(exe):
    """Closes every instance of the kit's runtime through its window, then ends those still there after 20 s. Returns how many had to be ended."""
    for pid in exe_pids(exe):
        close_window(pid)
    t = time.monotonic()
    while exe_pids(exe) and time.monotonic() - t < 20:
        time.sleep(0.5)
    left = exe_pids(exe)
    for pid in left:
        subprocess.run(['taskkill', '/F', '/PID', str(pid)], capture_output=True)
    return len(left)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    for name in ('game', 'scenario', 'sigs', 'out'):
        ap.add_argument(f'--{name}', type=Path, required=True)
    ap.add_argument('--burst', type=float, default=25)
    ap.add_argument('--ctl', default='', help="control commands sent in order once the scene shows, ';'-separated (e.g. 'passview 40;flight a')")
    ap.add_argument('--hold', type=float, default=0, help='then keep the game running up to this many seconds, until <out>/quit exists (drive_step.py drives it)')
    ap.add_argument('--flight', type=float, default=0, help='seconds between flight recordings (0: PNG captures of every present)')
    ap.add_argument('--timeout', type=float, default=1500, help='seconds for the stepper to reach the scene')
    ap.add_argument('--env', action='append', default=[], metavar='KEY=VALUE')
    ap.add_argument('--args', default='--renderer=vulkan --fullscreen=0 --docked=1')
    a = ap.parse_args()
    game, out = a.game.resolve(), a.out.resolve()
    if any(exe_pids(x) for x in [game / 'Orbitals.exe']) or subprocess.run(['tasklist', '/FI', 'IMAGENAME eq Orbitals.exe'], capture_output=True, text=True).stdout.count('Orbitals.exe'):
        sys.exit('an Orbitals instance is already running: one instance at a time')
    out.mkdir(parents=True, exist_ok=False)
    burst = out / 'burst'; burst.mkdir()
    log = game / 'Orbitals.log'
    tc = game.parent / 'toolchain'
    shot = out / 'shot-request.txt'
    env = os.environ.copy()
    env.update(SWR_GPU='nvn', NXRT_GFX='vulkan', NXRT_VK_WB_GPU='1', SWR_WINDOW_SIZE='1280x720', SWR_AUDIO_MUTE='1',
               SWR_PYTHON=sys.executable, DOTNET_ROOT=str(tc / 'dotnet10'), NXSHADER_TOOLS=str(tc / 'vulkan-bin'), NXRT_VK_SHOT_FILE=str(shot))
    env['PATH'] = os.pathsep.join((env['DOTNET_ROOT'], env['NXSHADER_TOOLS'], env['PATH']))
    env.update(pair.split('=', 1) for pair in a.env)
    (out / 'run.json').write_text(json.dumps({'game': str(game), 'scenario': str(a.scenario.resolve()), 'env': a.env, 'args': a.args,
                                              'burst_s': a.burst, 'started': time.strftime('%Y-%m-%dT%H:%M:%S')}, indent=1))
    stepper = Path(__file__).resolve().parents[1] / 'visual_suite' / 'stepper.py'
    status = 'ok'
    with (out / 'console.log').open('wb') as console:
        proc = subprocess.Popen([str(game / 'Orbitals.exe'), *a.args.split(), f'--script_file={out / "step-input.txt"}'],
                                cwd=game, env=env, stdout=console, stderr=subprocess.STDOUT)
        (out / 'pid.txt').write_text(str(proc.pid))
        try:
            r = subprocess.run([sys.executable, '-B', str(stepper), 'run', '--scenario', str(a.scenario.resolve()), '--sigs', str(a.sigs.resolve()),
                                '--script-file', str(out / 'step-input.txt'), '--shot-file', str(shot), '--log', str(log),
                                '--out', str(out / 'steps'), '--timeout', '300'], timeout=a.timeout)
            if r.returncode:
                status = 'stepper-failed'
            if not r.returncode and a.ctl:
                replies = []
                for c in filter(None, (x.strip() for x in a.ctl.split(';'))):
                    replies.append({'cmd': c, 't': round(time.monotonic(), 2), 'reply': ctl(c, timeout=300).strip()}); print(replies[-1], flush=True)
                (out / 'ctl.json').write_text(json.dumps(replies, indent=1))
            if r.returncode:
                pass
            elif a.flight:
                recs, t0, k = [], time.monotonic(), 0
                while time.monotonic() - t0 < a.burst and proc.poll() is None:
                    k += 1; t = round(time.monotonic() - t0, 2)
                    fl = ctl('flashes 118 40').strip()
                    where = ctl(f'flight scene-{k}').strip()
                    recs.append({'k': k, 't': t, 'flashes': fl, 'dir': where}); print(recs[-1], flush=True)
                    (out / 'flight.json').write_text(json.dumps(recs, indent=1))
                    time.sleep(max(0.0, a.flight - (time.monotonic() - t0 - t)))
            else:
                frames, n, t0 = [], 0, time.monotonic()
                while time.monotonic() - t0 < a.burst and proc.poll() is None:
                    if not shot.exists():
                        n += 1; p = burst / f'{n:05d}.png'
                        tmp = shot.with_suffix('.tmp'); tmp.write_text(str(p), encoding='utf-8'); tmp.replace(shot)
                        frames.append({'n': n, 't': round(time.monotonic() - t0, 3)})
                    time.sleep(0.002)
                time.sleep(1.0)
                shot.unlink(missing_ok=True)
                # present number of each capture, from the log
                text = log.read_bytes()[-8_000_000:].decode('utf-8', 'replace')
                pres = {int(m[2]): int(m[1]) for m in re.finditer(r'screenshot: present (\d+)[^\n]*?[\\/](\d{5})\.png', text)}
                for f in frames:
                    f['present'] = pres.get(f['n'])
                (out / 'burst.json').write_text(json.dumps(frames))
            if not r.returncode and a.hold:
                (out / 'ready').write_text(str(time.time())); t0 = time.monotonic()
                while time.monotonic() - t0 < a.hold and proc.poll() is None and not (out / 'quit').exists():
                    time.sleep(0.5)
        finally:
            if stop_game(game / 'Orbitals.exe'):
                status += '+killed'
            if proc.poll() is None:
                try:
                    proc.wait(20)
                except subprocess.TimeoutExpired:
                    proc.kill(); proc.wait(10); status += '+killed'
    for name in ('Orbitals.log', 'frames.csv'):
        if (game / name).exists():
            shutil.copy2(game / name, out / name)
    print(f'run={out} status={status} exit={proc.returncode}')


if __name__ == '__main__':
    main()
