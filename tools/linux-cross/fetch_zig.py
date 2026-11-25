# Orbitals PC Recomp, a work based on SwitchRecomp by MZ Labs. GNU AGPL v3.0 with the additional terms of NOTICE.txt (LICENSE.txt).
"""Zig 0.15.2 for Windows x64 (ziglang.org), the C compiler that builds the Linux ELF files on Windows (tools/steamdeck/cross/build.py).
Downloaded once into this folder, checked against its pinned SHA-256, unpacked to zig-x86_64-windows-0.15.2/.

  python tools/linux-cross/fetch_zig.py
Then: python tools/linux-cross/prepare-linux-sysroot.py and prepare-opus.py (Ubuntu 24.04 headers and libraries, each package checked
against the archive's own SHA-256)."""
import hashlib, io, os, urllib.request, zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
URL = 'https://ziglang.org/download/0.15.2/zig-x86_64-windows-0.15.2.zip'
SHA = '3a0ed1e8799a2f8ce2a6e6290a9ff22e6906f8227865911fb7ddedc3cc14cb0c'

if __name__ == '__main__':
    dest = os.path.join(HERE, 'zig-x86_64-windows-0.15.2')
    if os.path.isfile(os.path.join(dest, 'zig.exe')): raise SystemExit(f'already there: {dest}')
    cache = os.path.join(HERE, 'zig.zip')
    data = open(cache, 'rb').read() if os.path.isfile(cache) else None
    if not data or hashlib.sha256(data).hexdigest() != SHA:
        print(f'downloading {URL} (88 MB)', flush=True)
        with urllib.request.urlopen(URL, timeout=300) as r: data = r.read()
        if hashlib.sha256(data).hexdigest() != SHA: raise SystemExit('the download is damaged (SHA-256 differs)')
        open(cache, 'wb').write(data)
    zipfile.ZipFile(io.BytesIO(data)).extractall(HERE)
    print(f'zig in {dest}')
