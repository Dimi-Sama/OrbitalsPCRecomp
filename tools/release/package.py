# Orbitals PC Recomp, a work based on SwitchRecomp by MZ Labs. GNU AGPL v3.0 with the additional terms of NOTICE.txt (LICENSE.txt).
"""Release archives of Orbitals PC Recomp. Nothing of the game goes in: the audit refuses it.

  python -B tools/release/package.py --ref public/v0.1.0 --version 0.1.0 --out dist/v0.1.0 \
      --windows-runtime bin/runtime_win64_win32.exe --linux-runtime build/steamdeck-linux/Orbitals --sdl3 <toolchain>/SDL3.dll

Archives:
  OrbitalsPCRecomp-<v>-source.zip / .tar.gz      git archive of the public commit
  OrbitalsPCRecomp-<v>-windows-x64.zip           the same source tree + the prebuilt Win32 runtime (bin/runtime_win64_win32.exe) and SDL3.dll:
                                                 tools/release/setup-windows.ps1 then skips building the runtime; the game's code is still
                                                 recompiled on the user's PC from their copy
  OrbitalsPCRecomp-<v>-linux-x64.tar.gz          the same source tree + the prebuilt Linux runtime (ELF, x11 backend, for the Steam Deck)
Beside them: MANIFEST.json (every file of every archive: size, SHA-256, origin, license) and SHA256SUMS.txt.
The binaries added to the source tree must be the runtimes built from that same commit (the manifest records the commit they were built
at; package.py checks that the working tree's HEAD tree equals the public tree when --check-build is given).
"""
import argparse, hashlib, io, json, os, subprocess, sys, tarfile, time, zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, '..', '..'))
sys.path.insert(0, HERE)
sys.path.insert(0, ROOT)
import audit_rules
import module_build

THIRD = {   # origin and license of the prebuilt files
    'bin/runtime_win64_win32.exe': ('built from this source tree (switchrecomp.py, win64/win32)',
                                    'AGPL-3.0 with NOTICE.txt terms; see NOTICE.txt for bundled dependencies'),
    'bin/SDL3.dll': ('SDL 3.4.16 official release, SDL3-3.4.16-win32-x64.zip', 'zlib'),
    'bin/SDL3-LICENSE.txt': ('SDL 3.4.16 official release', 'zlib'),
    'bin/runtime_linux_x11': ('built from this source tree (tools/steamdeck/cross/build.py runtime) with Zig 0.15.2 against Ubuntu 24.04 headers',
                              'AGPL-3.0 with NOTICE.txt terms; statically linked: Opus (BSD-3), libnvn (this tree)'),
}


def git(*a):
    r = subprocess.run(['git', *a], cwd=ROOT, capture_output=True)
    if r.returncode: raise SystemExit(f'git {" ".join(a)}: {r.stderr.decode(errors="replace")}')
    return r.stdout


def sha(b): return hashlib.sha256(b).hexdigest()


def platform_files(files, programs, binaries):
    result = []
    for path, mode, data in files:
        if path == 'recomplauncher.json':
            manifest = json.loads(data)
            for step in ('start', 'prepare'):
                manifest[step]['program'] = programs
            manifest['prepare']['done'].extend(f'{{data}}/games/Orbitals/{name}' for name in binaries)
            data = (json.dumps(manifest, ensure_ascii=False, indent=2) + '\n').encode('utf-8')
        result.append((path, mode, data))
    return result


def source_files(ref):
    """(path, mode, bytes) of the public tree, as git archive would write them"""
    data = git('archive', '--format=tar', ref)
    out = []
    with tarfile.open(fileobj=io.BytesIO(data)) as t:
        for m in t.getmembers():
            if m.isfile(): out.append((m.name, m.mode, t.extractfile(m).read()))
    return out


def audit(name, files):
    bad = []
    for path, _, data in files:
        why = audit_rules.name_reason(path)
        if why and path not in THIRD: bad.append(f'{path}: {why}')
        for r in audit_rules.text_reasons(path, data): bad.append(f'{path}: {r}')
        if path in THIRD and path.startswith('bin/runtime'):   # prebuilt runtimes: no build machine path (-ffile-prefix-map, stripped debug info)
            import re
            m = re.search(rb'(?i)[a-z]:[\\/](?:users|recomp)[\\/]|/home/(?!deck/)[a-z]', data)
            if m: bad.append(f'{path}: a build machine path in the binary ({data[m.start():m.start() + 60]!r})')
    if bad:
        print(f'REFUSED in {name}:'); [print('  ' + b) for b in bad]
        raise SystemExit(1)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--ref', default='public/v0.1.0'); ap.add_argument('--version', default='0.1.0'); ap.add_argument('--out', required=True)
    ap.add_argument('--windows-runtime'); ap.add_argument('--linux-runtime'); ap.add_argument('--sdl3')
    a = ap.parse_args()
    commit = git('rev-parse', a.ref).decode().strip(); short = commit[:7]
    prefix = f'OrbitalsPCRecomp-{a.version}/'
    os.makedirs(a.out, exist_ok=True)
    src = source_files(a.ref)
    contents = {path: data for path, _, data in src}
    if "module_build.py" in contents:
        contract = module_build.runtime_contract(contents.__getitem__)
        for binary in (a.windows_runtime, a.linux_runtime):
            if binary and module_build.marker_value(binary, module_build.RUNTIME_MARKER) != contract:
                raise SystemExit(f"The runtime does not match the code contract in {a.ref}: {binary}")
    src.append(('COMMIT', 0o644, (commit[:12] + '\n').encode()))   # switchrecomp.py release_id: the commit a build from this archive names in its log
    audit('the source tree', src)
    manifest = {'version': a.version, 'commit': commit, 'made': time.strftime('%Y-%m-%dT%H:%M:%S'), 'archives': {}}
    stamp = (2026, 11, 21, 0, 0, 0)

    def write_zip(name, files):
        p = os.path.join(a.out, name)
        with zipfile.ZipFile(p, 'w', zipfile.ZIP_DEFLATED, compresslevel=9) as z:
            for path, mode, data in sorted(files):
                zi = zipfile.ZipInfo(prefix + path, stamp); zi.external_attr = (mode & 0xffff) << 16; zi.compress_type = zipfile.ZIP_DEFLATED
                z.writestr(zi, data)
        return p

    def write_tgz(name, files):
        p = os.path.join(a.out, name)
        with tarfile.open(p, 'w:gz', compresslevel=9) as t:
            for path, mode, data in sorted(files):
                ti = tarfile.TarInfo(prefix + path); ti.size = len(data); ti.mode = mode; ti.mtime = 1795219200
                t.addfile(ti, io.BytesIO(data))
        return p

    def record(archive, files):
        manifest['archives'][archive] = [{'path': f, 'bytes': len(d), 'sha256': sha(d),
                                          'origin': ('platform manifest generated from the source tree at ' + short
                                                     if f == 'recomplauncher.json' and '-source.' not in archive
                                                     else THIRD.get(f, (f'source tree at {short}',))[0]),
                                          'license': THIRD.get(f, (None, 'see LICENSE.txt / NOTICE.txt / the file\'s own header'))[1]} for f, _, d in sorted(files)]

    outs = []
    n = f'OrbitalsPCRecomp-{a.version}-source'
    outs += [write_zip(n + '.zip', src), write_tgz(n + '.tar.gz', src)]; record(n + '.zip', src); record(n + '.tar.gz', src)
    if a.windows_runtime:
        extra = [('bin/runtime_win64_win32.exe', 0o755, open(a.windows_runtime, 'rb').read())]
        if a.sdl3:
            extra.append(('bin/SDL3.dll', 0o644, open(a.sdl3, 'rb').read()))
            lic = os.path.join(os.path.dirname(a.sdl3), 'SDL3-LICENSE.txt')
            if os.path.isfile(lic): extra.append(('bin/SDL3-LICENSE.txt', 0o644, open(lic, 'rb').read()))
        files = platform_files(src, ['Orbitals-Launcher.bat'], ['Orbitals.exe', 'Orbitals_code.dll']) + extra
        audit('the Windows kit', files)
        nm = f'OrbitalsPCRecomp-{a.version}-windows-x64.zip'; outs.append(write_zip(nm, files)); record(nm, files)
    if a.linux_runtime:
        files = platform_files(src, ['AppRun', 'Orbitals-Launcher.sh', 'OrbitalsPCRecomp-x86_64.AppImage'], ['Orbitals', 'Orbitals_code.so'])
        files.append(('bin/runtime_linux_x11', 0o755, open(a.linux_runtime, 'rb').read()))
        audit('the Linux kit', files)
        nm = f'OrbitalsPCRecomp-{a.version}-linux-x64.tar.gz'; outs.append(write_tgz(nm, files)); record(nm, files)
    json.dump(manifest, open(os.path.join(a.out, 'MANIFEST.json'), 'w'), indent=1)
    with open(os.path.join(a.out, 'SHA256SUMS.txt'), 'w', newline='\n') as f:
        for p in outs + [os.path.join(a.out, 'MANIFEST.json')]:
            f.write(f'{sha(open(p, "rb").read())}  {os.path.basename(p)}\n')
    for p in outs: print(f'{os.path.basename(p)}  {os.path.getsize(p) / 1048576:.1f} MB')
    print(f'MANIFEST.json, SHA256SUMS.txt in {a.out} (commit {short})')


if __name__ == '__main__':
    main()
