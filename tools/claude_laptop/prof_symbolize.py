"""Symbolize the runtime part of a profile=1 profile (Windows runtime built with mingw gcc, symbols kept).

  python prof_symbolize.py <run dir> [profile-0200.txt] [--top 40]

Reads <profile>.focus.txt (focus thread: 'e off n' runtime samples, 'c off n' runtime call sites of samples outside the
runtime) and <profile>.dll.txt ('e off n' runtime samples of every thread), maps exe offsets to functions with nm of the
run's own Orbitals.exe, and prints per-function totals. Image base 0x140000000.
"""
import os, re, subprocess, sys, bisect, glob, collections

NM = os.environ.get("NM") or __import__("shutil").which("x86_64-w64-mingw32-nm") or os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "gcc", "Library", "bin", "x86_64-w64-mingw32-nm.exe")
BASE = 0x140000000

def symbols(exe):
    out = subprocess.run([NM, "-n", "--defined-only", exe], capture_output=True, text=True).stdout
    syms = []
    for line in out.splitlines():
        p = line.split()
        if len(p) == 3 and p[1] in "TtWw":
            syms.append((int(p[0], 16), p[2]))
    syms.sort()
    return [a for a, _ in syms], [n for _, n in syms]

def table(path, kind):
    rows = []
    if not os.path.exists(path): return rows
    for line in open(path):
        p = line.split()
        if len(p) == 3 and p[0] == kind:
            rows.append((int(p[1], 16), int(p[2])))
    return rows

def per_function(rows, addrs, names):
    tot = collections.Counter()
    for off, n in rows:
        i = bisect.bisect_right(addrs, BASE + off) - 1
        tot[names[i] if i >= 0 else "?"] += n
    return tot

def main():
    run = sys.argv[1]
    prof = sys.argv[2] if len(sys.argv) > 2 and not sys.argv[2].startswith("--") else None
    top = int(sys.argv[sys.argv.index("--top") + 1]) if "--top" in sys.argv else 40
    if not prof:
        cands = sorted(glob.glob(os.path.join(run, "profile-*.txt")))
        prof = os.path.basename([c for c in cands if not c.endswith((".dll.txt", ".focus.txt"))][-1])
    addrs, names = symbols(os.path.join(run, "Orbitals.exe"))
    p = os.path.join(run, prof)
    head = open(p).read()
    m = re.search(r"focus thread \(NVN translation\): (\d+) active samples", head)
    ftot = int(m.group(1)) if m else 0
    print(f"{prof}: focus thread {ftot} active samples")
    if m:
        sec = head[m.start():].split("focus: runtime offsets")[0]
        print(sec.rstrip())
    for kind, title in (("e", "focus thread, runtime functions (self)"), ("c", "focus thread, runtime callers of samples outside the runtime")):
        tot = per_function(table(p + ".focus.txt", kind), addrs, names)
        print(f"\n{title} (% of the thread's active samples):")
        for name, n in tot.most_common(top):
            print(f"  {100.0 * n / max(ftot, 1):6.2f}%  {name}")

if __name__ == "__main__":
    main()
