#!/usr/bin/env python3
# SwitchRecomp - Copyright 2026 MZ Labs
# Licensed under the GNU Affero General Public License v3.0, see LICENSE.txt and NOTICE.txt.
# Forks and derived works have to keep the credit to SwitchRecomp by MZ Labs and the startup screen.
"""nxs_kraken: builds, on this PC, the decoder nxs_prepare.py uses for the game's compressed shader archives.

  nxs_kraken.py --out DIR [--source FILE] [--cxx COMPILER]

The decoder is Powzix's ooz (https://github.com/powzix/ooz), GPL-3.0-or-later, an open source implementation of the Kraken family of
formats (Kraken, Mermaid, Selkie, Leviathan) that Unreal's IoStore containers use. This project ships none of it, and no Oodle library:
the decoder part of kraken.cpp is downloaded at a pinned commit (or read from --source), checked against its SHA-256, compiled here with
kraken/ooz_compat.h in place of its Windows-only stdafx.h and kraken/kraken_shim.cpp (OodleLZ_Decompress's calling convention) by MinGW
g++, the system's g++ / clang++ or Zig's clang (--cxx path/to/zig: nxs_deps.py's on SteamOS, which has no compiler), into
DIR/ooz_kraken.dll (Windows) or DIR/libooz_kraken.so (Linux), with DIR/ooz_kraken.txt naming its source and license. LZNA and BitKnit
are left out (their ooz files carry no license notice); Orbitals' archives use neither.

One JSON line on stdout: {"phase": "built", "library": ...} or {"phase": "error", ...}."""
import argparse, hashlib, json, os, shutil, subprocess, sys, tempfile, urllib.request
NO_WINDOW = 0x08000000 if os.name == 'nt' else 0   # CREATE_NO_WINDOW: a tool started from the launcher (no console) opens no window

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
COMMIT = '05038060aa68f9187ae9923b2388ca8db40e58d1'
URL = f'https://raw.githubusercontent.com/powzix/ooz/{COMMIT}/kraken.cpp'
SHA256 = '20c48a30db54efa7681f8c9c674f2a16f081373872d033885a6fdf244b9cff01'   # kraken.cpp at COMMIT, as GitHub serves it (LF line ends)
CUT = '\nvoid error(const char *s'   # the command-line tool after the decoder (file loading, LoadLibrary, timing): not built


def library_name():
    return 'ooz_kraken.dll' if os.name == 'nt' else 'libooz_kraken.so'


def compiler(explicit=None):
    if explicit: return explicit
    if os.name == 'nt':
        try:
            import s2r_paths as P
            gpp = P.gcc_tool('g++')
            if os.path.exists(gpp): return gpp
        except ImportError:
            pass
        return shutil.which('x86_64-w64-mingw32-g++') or shutil.which('g++') or shutil.which('clang++')
    return shutil.which('g++') or shutil.which('clang++')


def source_text(path=None):
    data = open(path, 'rb').read() if path else urllib.request.urlopen(URL, timeout=60).read()
    data = data.replace(b'\r\n', b'\n')
    if hashlib.sha256(data).hexdigest() != SHA256:
        raise RuntimeError('kraken.cpp does not match the pinned SHA-256 (expected ooz commit %s)' % COMMIT[:12])
    text = data.decode('utf-8', 'replace')
    if CUT not in text or '#include "stdafx.h"' not in text:
        raise RuntimeError('kraken.cpp does not have the expected layout')
    return text[:text.index(CUT)].replace('#include "stdafx.h"', '#include "ooz_compat.h"', 1) + '\n'


def build(out, source=None, cxx=None):
    cc = compiler(cxx)
    if not cc: raise RuntimeError('no C++ compiler (MinGW g++ on Windows, g++ or clang++ on Linux)')
    os.makedirs(out, exist_ok=True)
    lib = os.path.join(out, library_name())
    with tempfile.TemporaryDirectory(prefix='nxs_kraken_') as w:
        open(os.path.join(w, 'kraken_decoder.cpp'), 'w', encoding='utf-8', newline='\n').write(source_text(source))
        shutil.copy(os.path.join(HERE, 'kraken', 'ooz_compat.h'), w)
        zig = os.path.basename(cc).lower().startswith('zig')   # Zig's bundled clang (nxs_deps.py on Linux): "zig c++"
        cmd = [cc, *(['c++'] if zig else []), '-O2', '-msse4.1', '-shared', '-fPIC', '-fpermissive', '-w', '-I', w, '-o', os.path.join(w, library_name()),
               os.path.join(w, 'kraken_decoder.cpp'), os.path.join(HERE, 'kraken', 'kraken_shim.cpp')]
        if os.name == 'nt' and not zig: cmd[1:1] = ['-static']
        r = subprocess.run(cmd, capture_output=True, text=True, creationflags=NO_WINDOW)
        if r.returncode: raise RuntimeError('compiling the decoder failed: ' + (r.stderr.strip().splitlines() or ['exit %d' % r.returncode])[-1][:300])
        shutil.copyfile(os.path.join(w, library_name()), lib + ".new"); os.replace(lib + ".new", lib)   # the temporary folder can be on another drive
    open(os.path.join(out, 'ooz_kraken.txt'), 'w', encoding='utf-8').write(
        f'{library_name()}: built on this PC by tools/nxshader/nxs_kraken.py from kraken.cpp of ooz\n'
        f'(https://github.com/powzix/ooz, commit {COMMIT}, SHA-256 {SHA256}), Copyright (C) 2016 Powzix,\n'
        'GNU General Public License version 3 or later; with tools/nxshader/kraken (GNU AGPL v3, SwitchRecomp).\n'
        'Used to decode the shader archives of your own copy of the game; keep it on this PC.\n')
    return lib


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--out', required=True); ap.add_argument('--source', help='a local copy of kraken.cpp at the pinned commit'); ap.add_argument('--cxx')
    a = ap.parse_args(argv)
    try:
        lib = build(a.out, a.source, a.cxx)
    except (OSError, RuntimeError, ValueError) as error:
        print(json.dumps({'phase': 'error', 'error': str(error)[:400]}), flush=True); return 1
    print(json.dumps({'phase': 'built', 'library': lib}), flush=True)
    return 0


if __name__ == '__main__':
    sys.exit(main())
