#!/usr/bin/env python3
# SwitchRecomp - Copyright 2026 MZ Labs
# Licensed under the GNU Affero General Public License v3.0, see LICENSE.txt and NOTICE.txt.
# Forks and derived works have to keep the credit to SwitchRecomp by MZ Labs and the startup screen.
"""nxs_deps: the programs shader preparation needs on Linux (SteamOS included), in a private folder, without administrator rights.

  nxs_deps.py --dest DIR [--offline]

  dotnet   .NET runtime 10.0.15, linux-x64 (Microsoft, builds.dotnet.microsoft.com): runs the shader translator  -> DIR/dotnet10
  spirv    SPIRV-Tools 2026.4 (conda-forge linux-64): spirv-val, spirv-opt and libSPIRV-Tools-shared            -> DIR/spirv-tools
  zig      Zig 0.15.2, x86_64-linux (the Zig project's wheel on PyPI, else ziglang.org): its bundled clang compiles the archive
           decoder (nxs_kraken)                                                                                  -> DIR/zig

Each download comes from its project's own server and is checked against a pinned digest (the SHA-512 Microsoft publishes for .NET,
SHA-256 for the others) before anything is unpacked. Nothing outside DIR is written: no package manager, no system library, no
environment change, no service. A component already in DIR whose recorded digest matches is kept, so a later run is offline. With
--offline nothing is downloaded and a missing component is an error. Downloads go to DIR/_downloads first, so an interrupted run
resumes from the files already checked. The components run on glibc 2.17+ with libstdc++ from GCC 15 (SteamOS 3.8 has 2.41 and
GCC 15's); Python 3.14's zstd, or the zstandard wheel from PyPI on older Pythons, unpacks the conda package.

One JSON object per line on stdout: {"phase": "deps", "component": ..., "status": kept|downloading|installed} then
{"phase": "deps_ready", "dotnet": ..., "spirv_tools": ..., "cxx": ...} or {"phase": "error", ...}."""
import argparse, hashlib, io, json, os, shutil, sys, tarfile, urllib.request, zipfile

PKGS = {   # name: (url, algorithm, digest, size)
    'dotnet': ('https://builds.dotnet.microsoft.com/dotnet/Runtime/10.0.15/dotnet-runtime-10.0.15-linux-x64.tar.gz', 'sha512',
               'a90177d75bc891f71aa814dde3bcf76a356f5a506824669f1891754457954a3d13b72f3ca04c98fa0fe588514a5a781f8a87b17930ee802105c14f9edb28318a', None),
    'spirv': ('https://conda.anaconda.org/conda-forge/linux-64/spirv-tools-2026.4-h7148c6a_2.conda', 'sha256',
              'e8791349946b2c98ffa5cc67cf1525931e066aef8a01800d6f7c151444a3f052', 2433353),
    'zig': ('https://ziglang.org/download/0.15.2/zig-x86_64-linux-0.15.2.tar.xz', 'sha256',
            '02aa270f183da276e5b5920b1dac44a63f1a49e55050ebde3aecc9eb82f93239', 53733924),
}
# The same Zig 0.15.2 as the Zig project's Python wheel on PyPI (ziglang): served by PyPI's CDN, tried first (ziglang.org served ~110 KB/s
# to a Steam Deck: 8 min for the tarball); the tarball is the fallback
ALT = {
    'zig': ('https://files.pythonhosted.org/packages/db/81/f9f5c7fd68d80b8edff2a641a1c95ac4125356387d298374227040b8e1e8/'
            'ziglang-0.15.2-py3-none-manylinux_2_12_x86_64.manylinux2010_x86_64.musllinux_1_1_x86_64.whl', 'sha256',
            '806316453d1ede7174ed3fefb8e5348154629089c3bb5fe812dfd0e172fac130', 93508126),
}


def emit(phase, **fields):
    print(json.dumps({'phase': phase, **fields}), flush=True)


def digest(data, algorithm):
    return hashlib.new(algorithm, data).hexdigest()


def fetch(name, dest, offline, table=PKGS):
    url, algo, want, _ = table[name]
    path = os.path.join(dest, '_downloads', url.rsplit('/', 1)[-1])
    if os.path.isfile(path):
        data = open(path, 'rb').read()
        if digest(data, algo) == want: return data
    if offline: raise RuntimeError(f'{name} is not in {dest} and --offline was given')
    emit('deps', component=name, status='downloading', url=url)
    with urllib.request.urlopen(url, timeout=300) as r: data = r.read()
    if digest(data, algo) != want: raise RuntimeError(f'{name}: the download does not match its pinned {algo} (damaged or changed upstream)')
    os.makedirs(os.path.dirname(path), exist_ok=True)
    open(path + '.part', 'wb').write(data); os.replace(path + '.part', path)
    return data


def safe_members(tar, prefix=''):
    for m in tar.getmembers():
        n = m.name
        if n.startswith('/') or '..' in n.split('/') or (m.issym() or m.islnk()) and (m.linkname.startswith('/') or '..' in m.linkname.split('/')):
            continue
        if prefix and not n.startswith(prefix): continue
        yield m


def unpack_tar(data, mode, out, strip=0):
    tmp = out + '.unpack'
    shutil.rmtree(tmp, ignore_errors=True); os.makedirs(tmp)
    with tarfile.open(fileobj=io.BytesIO(data), mode=mode) as t:
        members = list(safe_members(t))
        for m in members:
            if strip:
                parts = m.name.split('/', strip)
                if len(parts) <= strip: continue
                m.name = parts[strip]
        t.extractall(tmp, members=[m for m in members if m.name], filter='tar') if sys.version_info >= (3, 12) else t.extractall(tmp, members=[m for m in members if m.name])
    shutil.rmtree(out, ignore_errors=True); os.replace(tmp, out)


def unzstd(data):
    try:
        from compression import zstd
        return zstd.decompress(data)
    except ImportError:
        pass
    here = os.path.dirname(os.path.abspath(__file__))
    sys.path.insert(0, os.path.join(here, '..', '..', 'tool'))
    import get_deps   # the zstandard wheel from PyPI for this Python, as the Linux tool setup does
    return get_deps.unzstd(data)


def unpack_wheel(data, out, top):
    """the files under top/ of a wheel (zip), modes kept (a wheel's executables carry them in the zip's external attributes)"""
    tmp = out + '.unpack'
    shutil.rmtree(tmp, ignore_errors=True); os.makedirs(tmp)
    z = zipfile.ZipFile(io.BytesIO(data))
    for info in z.infolist():
        n = info.filename
        if not n.startswith(top + '/') or n.endswith('/') or '..' in n.split('/'): continue
        dst = os.path.join(tmp, *n[len(top) + 1:].split('/'))
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        with open(dst, 'wb') as f: f.write(z.read(info))
        mode = info.external_attr >> 16
        if mode & 0o111: os.chmod(dst, 0o755)
    shutil.rmtree(out, ignore_errors=True); os.replace(tmp, out)


def unpack_conda(data, out):
    tmp = out + '.unpack'
    shutil.rmtree(tmp, ignore_errors=True); os.makedirs(tmp)
    z = zipfile.ZipFile(io.BytesIO(data))
    for n in z.namelist():
        if n.startswith('pkg-') and n.endswith('.tar.zst'):
            with tarfile.open(fileobj=io.BytesIO(unzstd(z.read(n)))) as t:
                members = [m for m in safe_members(t) if m.name.startswith(('bin/', 'lib/'))]
                t.extractall(tmp, members=members, filter='tar') if sys.version_info >= (3, 12) else t.extractall(tmp, members=members)
    shutil.rmtree(out, ignore_errors=True); os.replace(tmp, out)


def ensure(dest, offline=False):
    """the three components in dest; → {'dotnet': path, 'spirv_tools': bin folder, 'cxx': zig path}"""
    os.makedirs(dest, exist_ok=True)
    rec_path = os.path.join(dest, 'VERSIONS.json')
    try: rec = json.load(open(rec_path))
    except (OSError, ValueError): rec = {}
    layout = {'dotnet': ('dotnet10', 'dotnet'), 'spirv': ('spirv-tools', 'bin/spirv-val'), 'zig': ('zig', 'zig')}
    for name, (folder, probe) in layout.items():
        out = os.path.join(dest, folder)
        wants = {PKGS[name][2]} | ({ALT[name][2]} if name in ALT else set())
        if rec.get(name) in wants and os.path.exists(os.path.join(out, probe)):
            emit('deps', component=name, status='kept'); continue
        want = None
        if name in ALT:   # the faster source first, the other one if it fails
            try:
                data = fetch(name, dest, offline, ALT); want = ALT[name][2]; unpack_wheel(data, out, 'ziglang')
            except (OSError, RuntimeError, zipfile.BadZipFile) as error:
                emit('deps', component=name, status='alternative failed', error=str(error)[:200])
        if want is None:
            data = fetch(name, dest, offline); want = PKGS[name][2]
            if name == 'dotnet': unpack_tar(data, 'r:gz', out)
            elif name == 'zig': unpack_tar(data, 'r:xz', out, strip=1)
            else: unpack_conda(data, out)
        if not os.path.exists(os.path.join(out, probe)): raise RuntimeError(f'{name} did not unpack as expected ({probe} missing)')
        rec[name] = want
        open(rec_path + '.part', 'w').write(json.dumps(rec, indent=1)); os.replace(rec_path + '.part', rec_path)
        emit('deps', component=name, status='installed')
    return {'dotnet': os.path.join(dest, 'dotnet10', 'dotnet'), 'spirv_tools': os.path.join(dest, 'spirv-tools', 'bin'),
            'cxx': os.path.join(dest, 'zig', 'zig')}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--dest', required=True); ap.add_argument('--offline', action='store_true')
    a = ap.parse_args(argv)
    try:
        if not sys.platform.startswith('linux'): raise RuntimeError('Linux only (Windows: tools/release/get_orbitals_deps.py)')
        emit('deps_ready', **ensure(os.path.abspath(a.dest), a.offline))
        return 0
    except (OSError, RuntimeError, ValueError, tarfile.TarError, zipfile.BadZipFile) as error:
        emit('error', error=str(error)[:400]); return 1


if __name__ == '__main__':
    sys.exit(main())
