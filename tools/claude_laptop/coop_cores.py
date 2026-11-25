"""Measure Windows CPU affinity in a fixed co-op scene using the visual stepper."""

import argparse
import ctypes
from ctypes import wintypes
import json
import os
from pathlib import Path
import re
import statistics
import struct
import subprocess
import sys
import time


def topology(kernel, allowed):
    size = wintypes.DWORD()
    kernel.GetLogicalProcessorInformationEx(0, None, ctypes.byref(size))
    data = ctypes.create_string_buffer(size.value)
    if not kernel.GetLogicalProcessorInformationEx(0, data, ctypes.byref(size)):
        raise ctypes.WinError(ctypes.get_last_error())
    cores = []
    offset = 0
    while offset < size.value:
        relation, step = struct.unpack_from('<II', data, offset)
        if relation != 0 or step < 48 or offset + step > size.value:
            raise RuntimeError('invalid processor topology record')
        mask, group = struct.unpack_from('<QH', data, offset + 32)
        if group == 0 and mask & allowed:
            cores.append((data.raw[offset + 9], mask & allowed))
        offset += step
    best = max(c[0] for c in cores)
    logical = sorted(mask & -mask for kind, mask in cores if kind == best)
    if len(logical) < 6:
        raise RuntimeError('the benchmark needs six allowed performance cores in processor group zero')
    return {str(n): sum(logical[:n]) for n in (2, 4, 6)} | {'full': allowed}


def cpu_seconds(kernel, handle):
    times = (wintypes.FILETIME * 4)()
    if not kernel.GetProcessTimes(handle, *(ctypes.byref(t) for t in times)):
        raise ctypes.WinError(ctypes.get_last_error())
    return sum((t.dwHighDateTime << 32) + t.dwLowDateTime for t in times[2:]) / 10_000_000


def capture_frame(out, log, name):
    request = out / 'shot-request.txt'
    temp = request.with_suffix('.tmp')
    temp.write_text(str(out / f'{name}.png'), encoding='utf-8')
    temp.replace(request)
    pattern = re.compile(r'^\[\s*([0-9.]+)\] \[vk\] screenshot: present (\d+)[^\n]*' + re.escape(name) + r'\.png', re.M)
    until = time.monotonic() + 30
    while time.monotonic() < until:
        with log.open('rb') as stream:
            stream.seek(max(0, log.stat().st_size - 32768))
            match = pattern.search(stream.read().decode('utf-8', 'replace'))
        if match and not request.exists():
            return (int(match[2]), float(match[1]))
        time.sleep(0.05)
    raise RuntimeError(f'measured scene stopped presenting at {name}')



def game_process(kernel, executable):
    """Use the Vulkan control pipe to identify the process doing the rendering."""
    kernel.CreateFileW.argtypes = (wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, ctypes.c_void_p,
                                  wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE)
    kernel.CreateFileW.restype = wintypes.HANDLE
    kernel.GetNamedPipeServerProcessId.argtypes = (wintypes.HANDLE, ctypes.POINTER(wintypes.ULONG))
    kernel.OpenProcess.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
    kernel.OpenProcess.restype = wintypes.HANDLE
    kernel.QueryFullProcessImageNameW.argtypes = (wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR,
                                                  ctypes.POINTER(wintypes.DWORD))
    kernel.CloseHandle.argtypes = (wintypes.HANDLE,)
    for _ in range(20):
        pipe = kernel.CreateFileW(r'\\.\pipe\swr_ctl', 0xC0000000, 0, None, 3, 0, None)
        if pipe != ctypes.c_void_p(-1).value:
            break
        time.sleep(0.1)
    else:
        raise RuntimeError('the game control pipe did not open')
    pid = wintypes.ULONG()
    try:
        if not kernel.GetNamedPipeServerProcessId(pipe, ctypes.byref(pid)):
            raise ctypes.WinError(ctypes.get_last_error())
    finally:
        kernel.CloseHandle(pipe)
    # PROCESS_QUERY_INFORMATION | PROCESS_SET_INFORMATION
    handle = kernel.OpenProcess(0x0600, False, pid.value)
    if not handle:
        raise ctypes.WinError(ctypes.get_last_error())
    path = ctypes.create_unicode_buffer(32768)
    length = wintypes.DWORD(len(path))
    try:
        if not kernel.QueryFullProcessImageNameW(handle, 0, path, ctypes.byref(length)):
            raise ctypes.WinError(ctypes.get_last_error())
        if not os.path.samefile(executable, path.value):
            raise RuntimeError('the control pipe belongs to another launch')
    except BaseException:
        kernel.CloseHandle(handle)
        raise
    return pid.value, handle

def close_window(pid):
    user32 = ctypes.windll.user32
    callback = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    user32.GetWindowThreadProcessId.argtypes = (wintypes.HWND, ctypes.POINTER(wintypes.DWORD))
    user32.PostMessageW.argtypes = (wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM)

    @callback
    def close(hwnd, unused):
        owner = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(owner))
        if owner.value == pid:
            user32.PostMessageW(hwnd, 0x0010, 0, 0)
        return True

    user32.EnumWindows(close, 0)


def summarize(windows, frame_path):
    frames = {int(m[2]): float(m[1]) for m in re.finditer(rb'([0-9]+\.[0-9]+),\d+,\d+,(\d+),\d+,\d+\r?\n', frame_path.read_bytes())}
    for window in windows:
        first, last = window['first_present'] + 4, window['last_present'] - 4
        samples = [frames[n + 1] - frames[n] for n in range(first, last) if n in frames and n + 1 in frames]
        if len(samples) < 30:
            raise RuntimeError(f'not enough present intervals in {window["name"]}')
        q = statistics.quantiles(samples, n=100, method='inclusive')
        window.update(intervals=len(samples), fps=1000 * len(samples) / sum(samples), p50_ms=q[49], p95_ms=q[94], p99_ms=q[98])
    return windows


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    for name in ('game', 'scenario', 'sigs', 'out'):
        ap.add_argument(f'--{name}', type=Path, required=True)
    ap.add_argument('--seconds', default=12, type=float)
    ap.add_argument('--modes', nargs='+', choices=('2', '4', '6', 'full'), default=('2', '4', '6', 'full', 'full', '6', '4', '2'))
    ap.add_argument('--env', action='append', default=[], metavar='KEY=VALUE')
    args = ap.parse_args()
    if os.name != 'nt' or struct.calcsize('P') != 8 or args.seconds < 4:
        ap.error('requires 64-bit Windows and at least four seconds per sample')
    game, out = args.game.resolve(), args.out.resolve()
    out.mkdir(parents=True, exist_ok=False)
    stepper = Path(__file__).resolve().parents[1] / 'visual_suite' / 'stepper.py'
    log = game / 'Orbitals.log'
    tc = game.parent / 'toolchain'
    env = os.environ.copy()
    env.update(SWR_GPU='nvn', NXRT_GFX='vulkan', NXRT_VK_WB_GPU='1', SWR_WINDOW_SIZE='1280x720', SWR_AUDIO_MUTE='1',
               SWR_PYTHON=sys.executable, DOTNET_ROOT=str(tc / 'dotnet10'), NXSHADER_TOOLS=str(tc / 'vulkan-bin'),
               NXRT_VK_SHOT_FILE=str(out / 'shot-request.txt'))
    env['PATH'] = os.pathsep.join((env['DOTNET_ROOT'], env['NXSHADER_TOOLS'], env['PATH']))
    env.update(pair.split('=', 1) for pair in args.env)
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.GetProcessAffinityMask.argtypes = (wintypes.HANDLE, ctypes.POINTER(ctypes.c_size_t), ctypes.POINTER(ctypes.c_size_t))
    kernel.SetProcessAffinityMask.argtypes = (wintypes.HANDLE, ctypes.c_size_t)
    kernel.GetProcessTimes.argtypes = (wintypes.HANDLE,) + (ctypes.POINTER(wintypes.FILETIME),) * 4
    windows = []
    with (out / 'console.log').open('wb') as console:
        proc = subprocess.Popen([str(game / 'Orbitals.exe'), '--renderer=vulkan', '--fullscreen=0', '--docked=1',
                                 f'--script_file={out / "step-input.txt"}'], cwd=game, env=env, stdout=console, stderr=subprocess.STDOUT)
        pid, handle = proc.pid, None
        try:
            subprocess.run([sys.executable, '-B', str(stepper), 'run', '--scenario', str(args.scenario.resolve()),
                            '--sigs', str(args.sigs.resolve()), '--script-file', str(out / 'step-input.txt'),
                            '--shot-file', str(out / 'shot-request.txt'), '--log', str(log), '--out', str(out / 'steps'),
                            '--timeout', '170'], check=True, timeout=480)
            pid, handle = game_process(kernel, game / 'Orbitals.exe')
            print(f'Rendering PID {pid}; launch PID {proc.pid}', flush=True)
            allowed, system = ctypes.c_size_t(), ctypes.c_size_t()
            if not kernel.GetProcessAffinityMask(handle, ctypes.byref(allowed), ctypes.byref(system)):
                raise ctypes.WinError(ctypes.get_last_error())
            masks = topology(kernel, allowed.value)
            print('CPU masks:', {name: hex(mask) for name, mask in masks.items()}, flush=True)
            for index, mode in enumerate(args.modes, 1):
                name = f'{index:02d}-{mode}'
                if not kernel.SetProcessAffinityMask(handle, masks[mode]):
                    raise ctypes.WinError(ctypes.get_last_error())
                time.sleep(2)
                first, begin = capture_frame(out, log, name + '-start')
                start_cpu = cpu_seconds(kernel, handle)
                time.sleep(args.seconds)
                last, end = capture_frame(out, log, name + '-end')
                win = {'name': name, 'mode': mode, 'mask': hex(masks[mode]), 'start_s': begin, 'end_s': end,
                       'first_present': first, 'last_present': last, 'cpu_ms_per_present': 1000 * (cpu_seconds(kernel, handle) - start_cpu) / (last - first)}
                windows.append(win)
                print(json.dumps(win), flush=True)
        finally:
            if proc.poll() is None:
                if handle is None:
                    try:
                        pid, handle = game_process(kernel, game / 'Orbitals.exe')
                    except (OSError, RuntimeError):
                        pass
                close_window(pid)
                try:
                    proc.wait(12)
                except subprocess.TimeoutExpired:
                    proc.kill()
                    proc.wait(10)
            if handle:
                kernel.CloseHandle(handle)
    # A relaunched address space leaves the started process's child running the game: close every instance of this kit's runtime
    from flash_repro import stop_game
    if stop_game(game / 'Orbitals.exe'):
        print('an instance of the kit was still running after the run: ended', flush=True)
    # After a relaunch the started process is only the launcher (its status says nothing of the game): the windows were measured on the
    # rendering process found through the control pipe
    if proc.returncode != 0 and pid == proc.pid:
        raise RuntimeError(f'game exited with status {proc.returncode}')
    (out / 'matrix.json').write_text(json.dumps(summarize(windows, game / 'frames.csv'), indent=2) + '\n')


if __name__ == '__main__':
    main()
