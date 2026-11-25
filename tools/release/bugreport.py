# Orbitals PC Recomp, a work based on SwitchRecomp by MZ Labs. GNU AGPL v3.0 with the additional terms of NOTICE.txt (LICENSE.txt).
"""A bug report archive for a GitHub issue, made on your PC: logs with local paths, e-mail addresses, public IP addresses and secrets
masked (the launcher's own filter), system and GPU information, the game folder's settings and the runtime version.

  python -B tools/release/bugreport.py --game-dir games/Orbitals [--out DIR] [--run <a test run folder instead of the game folder>]

Never included: saves, game files (ExeFS, RomFS), shader or pipeline caches, recompiled code, screenshots. Check the archive before you
post it: the filter masks what it recognises, it cannot know everything that is personal.
"""
import argparse, hashlib, json, os, platform, sys, time, zipfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))
from launcher.reports import scrub, system_info, gpu_info   # noqa: E402

LOGS = ('Orbitals.log', 'console.log', 'threads.txt', 'crash.log', 'exit.json', 'stderr.txt', 'performance.txt')
LIMIT = 2 << 20   # per log: the start and the end are kept


def read_text(p):
    data = p.read_bytes()
    if len(data) > LIMIT: data = data[:LIMIT // 4] + b'\n--- middle omitted: size limit ---\n' + data[-(LIMIT - LIMIT // 4):]
    return data.decode('utf-8', errors='replace')


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--game-dir', required=True); ap.add_argument('--run'); ap.add_argument('--out', default='.')
    a = ap.parse_args()
    game = Path(a.game_dir).resolve(); src = Path(a.run).resolve() if a.run else game
    hide = [str(game), str(src), str(REPO), str(Path.home())]
    files, missing = {}, []
    for name in LOGS:
        p = src / name
        if p.is_file(): files['logs/' + name] = scrub(read_text(p), hide).encode('utf-8')
        else: missing.append(name)
    ini = game / 'Orbitals.ini'
    if ini.is_file(): files['config/Orbitals.ini'] = scrub(ini.read_text(errors='replace'), hide).encode('utf-8')
    head = ''
    if (src / 'Orbitals.log').is_file():
        head = next((l for l in read_text(src / 'Orbitals.log').splitlines()[:20] if 'Switch' in l or 'runtime' in l.lower()), '')
    info = {'system': system_info(), 'gpu': gpu_info(), 'python': platform.python_version(), 'runtime_header': scrub(head, hide),
            'repository_commit': (REPO / '.git').exists() and os.popen(f'git -C "{REPO}" rev-parse --short HEAD').read().strip() or None,
            'release': (REPO / 'VERSION').read_text().strip() if (REPO / 'VERSION').is_file() else None,
            'game_files_present': {k: (game / 'Orbitals_data' / k).exists() for k in ('exefs', 'romfs')},
            'missing_logs': missing}
    files['system/info.json'] = json.dumps(info, indent=1).encode('utf-8')
    files['README.txt'] = (b'Orbitals PC Recomp bug report. Check every file before attaching this archive to a public issue.\n'
                           b'It holds no saves and no game files. Local paths, e-mail addresses and public IP addresses were masked.\n')
    files['manifest.json'] = json.dumps([{'path': k, 'bytes': len(v), 'sha256': hashlib.sha256(v).hexdigest()} for k, v in sorted(files.items())], indent=1).encode()
    out = Path(a.out).resolve(); out.mkdir(parents=True, exist_ok=True)
    zp = out / f'Orbitals-BugReport-{time.strftime("%Y%m%d-%H%M%S")}.zip'
    with zipfile.ZipFile(zp, 'w', zipfile.ZIP_DEFLATED) as z:
        for k, v in files.items(): z.writestr(k, v)
    print(f'{zp} ({zp.stat().st_size // 1024} KB): {", ".join(sorted(files))}')
    if missing: print(f'not found (fine if the game did not get that far): {", ".join(missing)}')


if __name__ == '__main__':
    main()
