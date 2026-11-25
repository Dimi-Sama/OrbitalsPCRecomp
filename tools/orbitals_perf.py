"""Orbitals run analysis: frame times per present window (frames.csv) and the CPU profile of the recompiled game DLL.

  python tools/orbitals_perf.py frames RUN [first:last ...]     p50/p95/p99 frame time and FPS per present window
  python tools/orbitals_perf.py frames RUN --seconds 190:238  use elapsed time instead of present indices
  python tools/orbitals_perf.py profile RUN SYMS [t0 t1] [top]  hottest DLL functions over profile-<s>.txt windows

SYMS is `nm -n Orbitals_code.dll` output (only T/t lines are used). RUN is a run folder made with
SWR_PROF_WINDOWS=8000 (one profile-<milliseconds>ms.txt and .dll.txt per 8-second window)."""
import bisect, csv, glob, os, re, sys


def frame_times(run):
    rows = list(csv.reader(open(os.path.join(run, 'frames.csv'))))[1:]
    return [float(r[0]) for r in rows]


def pct(v, p):
    v = sorted(v)
    if not v: return 0.0
    k = (len(v) - 1) * p / 100.0
    i = int(k)
    return v[i] if i + 1 >= len(v) else v[i] + (v[i + 1] - v[i]) * (k - i)


def window_stats(ts, a, b):
    d = [ts[i] - ts[i - 1] for i in range(max(a, 1), min(b, len(ts)))]
    if not d: return None
    span = (ts[min(b, len(ts)) - 1] - ts[max(a, 1) - 1]) / 1000.0
    return dict(n=len(d), fps=len(d) / span if span else 0, p50=pct(d, 50), p95=pct(d, 95), p99=pct(d, 99),
                worst=max(d), t0=ts[max(a, 1) - 1] / 1000.0, t1=ts[min(b, len(ts)) - 1] / 1000.0)


def cmd_frames(run, specs):
    ts = frame_times(run)
    if specs and specs[0] == '--seconds':
        if len(specs) < 2:
            raise SystemExit('Specify at least one elapsed-time window, e.g. 190:238')
        print('time (s)           presents    FPS    p50 ms  p95 ms  p99 ms  worst')
        for spec in specs[1:]:
            start, end = (float(part) for part in spec.split(':'))
            if not start < end:
                raise SystemExit(f'Invalid elapsed-time window: {spec}')
            window = [ms for ms in ts if start * 1000 <= ms < end * 1000]
            if len(window) < 2:
                print(f'{spec}: fewer than two presents')
                continue
            intervals = [end_ms - start_ms for start_ms, end_ms in zip(window, window[1:])]
            print('%7.1f-%-7.1f  %8d  %6.2f  %6.2f  %6.2f  %6.2f  %7.1f' %
                  (start, end, len(window), len(window) / (end - start),
                   pct(intervals, 50), pct(intervals, 95), pct(intervals, 99), max(intervals)))
        return
    if not specs:
        specs = ['%d:%d' % (a, a + 300) for a in range(0, len(ts), 300)]
    print('presents        time (s)        FPS    p50 ms  p95 ms  p99 ms  worst')
    for s in specs:
        a, b = (int(x) for x in s.split(':'))
        w = window_stats(ts, a, b)
        if w:
            print('%5d-%-5d  %7.1f-%-7.1f  %6.2f  %6.2f  %6.2f  %6.2f  %7.1f' % (a, b, w['t0'], w['t1'], w['fps'], w['p50'], w['p95'], w['p99'], w['worst']))


def load_syms(path):
    addrs, names = [], []
    for line in open(path):
        p = line.split()
        if len(p) >= 3 and p[1] in ('T', 't'):
            addrs.append(int(p[0], 16)); names.append(p[2])
    return addrs, names


def profile_time(path):
    value, unit = re.search(r'profile-(\d+)(ms)?\.txt', path).groups()
    return int(value) / 1000 if unit else int(value)


def cmd_profile(run, syms, t0=0, t1=1e9, top=40):
    addrs, names = load_syms(syms)
    # the DLL is loaded at its preferred base in these builds; offsets in the profile are from the module base
    base = None
    for line in open(syms):
        pass
    # .text VMA - 0x1000 (objdump -h); ORBITALS_DLL_BASE overrides it for another build of the DLL
    image_base = int(os.environ.get('ORBITALS_DLL_BASE', '2E2900000'), 16)
    files = sorted(glob.glob(os.path.join(run, 'profile-*.txt.dll.txt')))
    hist, active, dll = {}, 0, 0
    used = []
    for f in files:
        sec = profile_time(f)
        if not (t0 <= sec <= t1): continue
        used.append(sec)
        head = open(f).readline()
        m = re.search(r'(\d+) samples, (\d+) lost, (\d+) active', head)
        dll += int(m.group(1)); active += int(m.group(3))
        for line in open(f):
            if line.startswith('#') or line.startswith('c ') or line.startswith('e '): continue
            off, n = line.split()
            a = image_base + int(off, 16)
            i = bisect.bisect_right(addrs, a) - 1
            nm = names[i] if i >= 0 else '?'
            hist[nm] = hist.get(nm, 0) + int(n)
    print('windows %s..%s s: %d active samples, %.1f%% in the game DLL' % (min(used), max(used), active, 100.0 * dll / max(active, 1)))
    for nm, n in sorted(hist.items(), key=lambda x: -x[1])[:top]:
        print('  %6.2f%%  %s' % (100.0 * n / max(active, 1), nm))


def cmd_callers(run, dll, syms, t0=0, t1=1e9, top=40):
    """call sites in recompiled code that lead to helper samples (SWR_PROF_CALLERS=1), with the A64 encoding the
    call passes (the last `mov $imm,%r8d` before the return address) and its total by encoding"""
    image_base = int(os.environ.get('ORBITALS_DLL_BASE', '2E2900000'), 16)
    sites, active = {}, 0
    for f in sorted(glob.glob(os.path.join(run, 'profile-*.txt.dll.txt'))):
        sec = profile_time(f)
        if not (t0 <= sec <= t1): continue
        m = re.search(r'(\d+) active', open(f).readline()); active += int(m.group(1))
        for line in open(f):
            if line.startswith('c '):
                _, off, n = line.split(); sites[int(off, 16)] = sites.get(int(off, 16), 0) + int(n)
    ranked = sorted(sites.items(), key=lambda x: -x[1])
    import struct
    data = open(dll, 'rb').read()
    pe = struct.unpack_from('<I', data, 0x3c)[0]
    nsec = struct.unpack_from('<H', data, pe + 6)[0]; opt = struct.unpack_from('<H', data, pe + 20)[0]
    secs = []
    for i in range(nsec):
        o = pe + 24 + opt + 40 * i
        vsize, va, rsize, raw = struct.unpack_from('<IIII', data, o + 8)
        secs.append((va, max(vsize, rsize), raw))
    def rva_bytes(rva, n):
        for va, sz, raw in secs:
            if va <= rva < va + sz: return data[raw + rva - va: raw + rva - va + n]
        return b''
    addrs, names = load_syms(syms) if syms else ([], [])
    by_enc = {}
    for off, n in ranked:
        code = rva_bytes(off - 64, 64)
        enc = None; callee = '?'
        if len(code) == 64 and code[-5] == 0xE8:
            tgt = image_base + off + struct.unpack_from('<i', code, 60)[0]
            i = bisect.bisect_right(addrs, tgt) - 1
            if i >= 0: callee = names[i]
            k = code.rfind(bytes((0x41, 0xB8)), 0, 59)
            if k >= 0: enc = struct.unpack_from('<I', code, k + 2)[0]
        key = (callee, enc)
        by_enc[key] = by_enc.get(key, 0) + n
    print('%d active samples, %d attributed to call sites' % (active, sum(sites.values())))
    for (callee, enc), n in sorted(by_enc.items(), key=lambda x: -x[1])[:top]:
        print('  %6.2f%%  %-16s %s' % (100.0 * n / max(active, 1), callee, ('%08x' % enc) if enc is not None else '-'))


def cmd_runtime(run, syms, t0=0, t1=1e9, top=40):
    """runtime exe samples (the NVN/Vulkan translation, the kernel) by function; SYMS = nm -n of the runtime exe"""
    addrs, names = load_syms(syms)
    base = int(os.environ.get('ORBITALS_EXE_BASE', '140000000'), 16)
    hist, active = {}, 0
    for f in sorted(glob.glob(os.path.join(run, 'profile-*.txt.dll.txt'))):
        sec = profile_time(f)
        if not (t0 <= sec <= t1): continue
        active += int(re.search(r'(\d+) active', open(f).readline()).group(1))
        for line in open(f):
            if line.startswith('e '):
                _, off, n = line.split(); a = base + int(off, 16)
                i = bisect.bisect_right(addrs, a) - 1
                nm = names[i] if i >= 0 else '?'
                hist[nm] = hist.get(nm, 0) + int(n)
    tot = sum(hist.values())
    print('%d active samples, %.1f%% in the runtime exe' % (active, 100.0 * tot / max(active, 1)))
    for nm, n in sorted(hist.items(), key=lambda x: -x[1])[:top]:
        print('  %6.2f%%  %s' % (100.0 * n / max(active, 1), nm))


if __name__ == '__main__':
    if sys.argv[1] == 'frames':
        cmd_frames(sys.argv[2], sys.argv[3:])
    elif sys.argv[1] == 'profile':
        a = sys.argv[2:]
        cmd_profile(a[0], a[1], float(a[2]) if len(a) > 2 else 0, float(a[3]) if len(a) > 3 else 1e9, int(a[4]) if len(a) > 4 else 40)
    elif sys.argv[1] == 'runtime':
        a = sys.argv[2:]
        cmd_runtime(a[0], a[1], float(a[2]) if len(a) > 2 else 0, float(a[3]) if len(a) > 3 else 1e9, int(a[4]) if len(a) > 4 else 40)
    elif sys.argv[1] == 'callers':
        a = sys.argv[2:]
        cmd_callers(a[0], a[1], a[2], float(a[3]) if len(a) > 3 else 0, float(a[4]) if len(a) > 4 else 1e9, int(a[5]) if len(a) > 5 else 40)
