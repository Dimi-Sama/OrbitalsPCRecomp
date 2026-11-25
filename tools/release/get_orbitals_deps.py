# Orbitals PC Recomp, a work based on SwitchRecomp by MZ Labs. GNU AGPL v3.0 with the additional terms of NOTICE.txt (LICENSE.txt).
"""What an Orbitals build needs beyond Switch2Recomp's Install.bat (Python + GCC), downloaded from the projects' own servers, each checked
against a pinned SHA-256 (BUILDING.md). Nothing is installed on the system: everything lands inside the repository.

  python tools/release/get_orbitals_deps.py [--only gxx,spirv,glslang,dotnet,sdl3] [--toolchain DIR]

  gxx      GCC 16.2 C++ (conda-forge gxx_impl, into gcc/ beside the C compiler Install.bat put there): the Vulkan layer (runtime/nvn) is C++
  spirv    SPIRV-Tools 2026.4 (conda-forge): spirv-val / spirv-opt for the live shader translator      -> <toolchain>/vulkan-bin
  glslang  glslang 16.6.0 (conda-forge): the runtime's own GLSL shaders, at build time                  -> <toolchain>/vulkan-bin
  dotnet   .NET runtime 10.0.15 (Microsoft): runs the shader translator (dmsh_xlate, Ryujinx's)         -> <toolchain>/dotnet10
  sdl3     SDL 3.4.16 (libsdl.org release): window, input and audio of the Windows runtime              -> <toolchain>/SDL3.dll

Windows x64 only for now (the Linux build uses the distribution's packages, BUILDING.md). The toolchain folder defaults to
<repo>/external/orbitals-toolchain; the launcher and tools/release/setup-windows.ps1 look for it there.
"""
import argparse, hashlib, io, os, shutil, sys, tarfile, zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.normpath(os.path.join(HERE, '..', '..'))
sys.path.insert(0, os.path.join(REPO, 'tool'))
import get_deps as G   # fetch / unpack / relocate of conda packages, GCC itself

CONDA = 'https://conda.anaconda.org/conda-forge/'
PKGS = {   # name: (url, sha256, size)
    'gxx': (CONDA + 'win-64/gxx_impl_win-64-16.2.0-hdbe55fc_7.conda', 'a9ee571df9ca3ec7ac8ec85916a12615e7c5ab0740d17f930abfb8730528935c', 15386224),
    'spirv': (CONDA + 'win-64/spirv-tools-2026.4-h49e36cd_2.conda', '933e40fe9ca887a63ef742260f0ed801cda317354806504d864764a4ed9749e1', 1605988),
    'glslang': (CONDA + 'win-64/glslang-16.6.0-h8fa7867_0.conda', '048f538b07594cc717a14517191a81cb1d3825fdde9c573d132c158b26d15806', 5149438),
    'dotnet': ('https://builds.dotnet.microsoft.com/dotnet/Runtime/10.0.15/dotnet-runtime-10.0.15-win-x64.zip',
               'c9f219ad2ec570478f4b1950ae56f88a48e76cabba75e7f54764a1d8a9009e87', 36980907),
    'sdl3': ('https://github.com/libsdl-org/SDL/releases/download/release-3.4.16/SDL3-3.4.16-win32-x64.zip',
             '4217944b4e51457af4a59c82d883f8443b3e65964b2acd8943484c492756c4b6', 1163613),
}


def download(name, dl):
    url, sha, size = PKGS[name]
    print(f'  {name}: {url.rsplit("/", 1)[-1]} ({size / 1048576:.1f} MB)', flush=True)
    return G.fetch(url, sha, os.path.join(dl, url.rsplit('/', 1)[-1]))


def conda_files(data):
    """(path, bytes) of a .conda package's payload"""
    z = zipfile.ZipFile(io.BytesIO(data))
    for n in z.namelist():
        if n.startswith('pkg-') and n.endswith('.tar.zst'):
            t = tarfile.open(fileobj=io.BytesIO(G.unzstd(z.read(n))))
            for m in t.getmembers():
                if m.isfile() and not m.name.startswith('/') and '..' not in m.name.split('/'): yield m.name, t.extractfile(m).read()


def main():
    if sys.platform != 'win32': raise SystemExit('Windows only: on Linux install g++, glslang, spirv-tools, SDL3 and the .NET 10 runtime from the distribution (BUILDING.md)')
    ap = argparse.ArgumentParser()
    ap.add_argument('--only', default='gxx,spirv,glslang,dotnet,sdl3')
    ap.add_argument('--toolchain', default=os.path.join(REPO, 'external', 'orbitals-toolchain'))
    a = ap.parse_args()
    what = [w.strip() for w in a.only.split(',') if w.strip()]
    tc = os.path.abspath(a.toolchain); dl = os.path.join(tc, '_downloads'); os.makedirs(dl, exist_ok=True)
    print(f'Orbitals build dependencies -> {tc}')
    if 'gxx' in what:
        if G.install_gcc(): raise SystemExit('GCC (C) is missing: run Install.bat first')
        G.relocate(G.unpack(download('gxx', dl)), G.DEST)   # same layout as the C compiler: x86_64-w64-mingw32-g++ and cc1plus beside gcc
        if not os.path.isfile(os.path.join(G.DEST, 'Library', 'bin', 'x86_64-w64-mingw32-g++.exe')): raise SystemExit('g++ did not unpack where expected')
    vb = os.path.join(tc, 'vulkan-bin'); os.makedirs(vb, exist_ok=True)
    for name, want in (('spirv', ('spirv-', 'SPIRV-Tools')), ('glslang', ('glslang',))):
        if name not in what: continue
        n = 0
        for path, body in conda_files(download(name, dl)):
            base = path.rsplit('/', 1)[-1]
            if path.startswith('Library/bin/') and base.lower().endswith(('.exe', '.dll')) and base.startswith(want):
                open(os.path.join(vb, base), 'wb').write(body); n += 1
        print(f'    {n} files into {vb}')
    if 'dotnet' in what:
        d = os.path.join(tc, 'dotnet10')
        if os.path.isdir(d): shutil.rmtree(d)
        zipfile.ZipFile(io.BytesIO(download('dotnet', dl))).extractall(d)
        print(f'    into {d}')
    if 'sdl3' in what:
        z = zipfile.ZipFile(io.BytesIO(download('sdl3', dl)))
        for n in z.namelist():
            if n.split('/')[-1] in ('SDL3.dll', 'LICENSE.txt', 'README-SDL.txt'):
                open(os.path.join(tc, 'SDL3-' + n.split('/')[-1] if n.endswith('.txt') else 'SDL3.dll'), 'wb').write(z.read(n))
        print(f'    SDL3.dll into {tc}')
    # what a release audit needs: the versions in use, next to the files
    with open(os.path.join(tc, 'VERSIONS.txt'), 'w') as f:
        for k, (u, s, n) in PKGS.items(): f.write(f'{k}\t{u}\t{s}\n')
    print('done')


if __name__ == '__main__':
    main()
