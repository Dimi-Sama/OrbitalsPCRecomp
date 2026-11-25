"""Make an isolated test kit from a playable folder: the runtime and settings copied, the code DLL hard-linked (never written), the game
data as junctions, a fresh copy of a save and of the shader cache, and junctions to the translator and toolchain the live compiler uses.

  make_kit.py --from <kit>/Orbitals --out <new>/  --save <save folder holding user/> [--nxshader DIR] [--toolchain DIR] [--cache DIR] [--exe FILE]

The new kit is <new>/Orbitals with <new>/nxshader and <new>/toolchain beside it, the layout coop_cores.py and flash_repro.py expect.
Nothing in the source kit, the save or the game data is written.
"""
import argparse, os, shutil, subprocess
from pathlib import Path


def junction(link, target):
    subprocess.run(['cmd', '/c', 'mklink', '/J', str(link), str(Path(target).resolve())], check=True, stdout=subprocess.DEVNULL)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--from', dest='src', type=Path, required=True)
    ap.add_argument('--out', type=Path, required=True)
    ap.add_argument('--save', type=Path, required=True)
    ap.add_argument('--nxshader', type=Path)
    ap.add_argument('--toolchain', type=Path)
    ap.add_argument('--cache', type=Path, help='Orbitals_nvn folder to copy (default: the source kit\'s)')
    ap.add_argument('--exe', type=Path, help='runtime to copy instead of the source kit\'s Orbitals.exe')
    a = ap.parse_args()
    src, out = a.src.resolve(), a.out.resolve()
    kit = out / 'Orbitals'
    kit.mkdir(parents=True, exist_ok=False)
    shutil.copy2(a.exe or src / 'Orbitals.exe', kit / 'Orbitals.exe')
    for name in ('SDL3.dll', 'Orbitals.ini', 'Orbitals.hints'):
        if (src / name).exists():
            shutil.copy2(src / name, kit / name)
    os.link((src / 'Orbitals_code.dll').resolve(), kit / 'Orbitals_code.dll')
    shutil.copytree(a.cache or src / 'Orbitals_nvn', kit / 'Orbitals_nvn')
    data = kit / 'Orbitals_data'; data.mkdir()
    for d in ('exefs', 'romfs'):
        junction(data / d, (src / 'Orbitals_data' / d).resolve())
    shutil.copytree(a.save, data / 'save')
    for name, given in (('nxshader', a.nxshader), ('toolchain', a.toolchain)):
        target = given or (src.parent / name)
        junction(out / name, target.resolve())
    print(kit)


if __name__ == '__main__':
    main()
