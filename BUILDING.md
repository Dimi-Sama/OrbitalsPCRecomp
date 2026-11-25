# Building Orbitals PC Recomp

The private preview archives contain the source, launcher and platform runtime. Installation requires **your own copy** of the game.
The recompiled module, shader cache, pipeline cache and saves are generated locally and must stay on your PC.

## What you need

- A folder with `exefs/` (`main`, `main.npdm`, `sdk`, `rtld`, `subsdk*`) and `romfs/` from your copy of *Orbitals* (Nintendo Switch 2,
  version 1.0.0). This project does not explain how to dump or decrypt console software and ships no keys.
- 16 GB of RAM (each compiler job takes about 0.5 GB; 4 jobs are safe), about 30 GB of free disk space (15 GB when the game data is linked
  instead of copied), a GPU with **Vulkan 1.3**.
- Windows 10/11 x64, or Linux x86-64 (glibc 2.34+). Internet access for the build tools (see the table below), never for the game.

## Windows: one command

```powershell
powershell -ExecutionPolicy Bypass -File tools\release\setup-windows.ps1 -GameData D:\path\to\Orbitals [-InstallDir games] [-Jobs 4] [-CopyData]
```

| Step | What happens | Result |
|---|---|---|
| 1 | `Install.bat`: Python 3.14 (nuget.org) and GCC 16.2 (conda-forge) into the repository | `python\`, `gcc\` |
| 2 | `tools\release\get_orbitals_deps.py`: g++ 16.2, SPIRV-Tools 2026.4, glslang 16.6.0 (conda-forge), .NET runtime 10.0.15 (Microsoft), SDL 3.4.16 (libsdl.org) | `gcc\` (g++), `games\toolchain\` |
| 3 | `tools\build_nvn.py` then `switchrecomp.py --build-runtime` | `bin\runtime_win64_win32.exe` |
| 4 | `switchrecomp.py <GameData> -o Orbitals -O 2`: the game's code translated to C and compiled (20–60 min) | `games\Orbitals\Orbitals_code.dll` |
| 5 | runtime, SDL3, live shader translator and launch script put in place | `games\Orbitals\` |

Every download is checked against the SHA-256 pinned in `tool\get_deps.py`, `Install.bat` and `tools\release\get_orbitals_deps.py`;
nothing is installed system-wide and no administrator rights are needed. `exefs\` and `romfs\` are linked (NTFS junctions) by default:
keep the game data where it is, or pass `-CopyData`. Each step is skipped when its result is there; `-Rebuild` makes everything again.

For renderer updates on an existing installation, run the same command with `-RebuildRuntime` to rebuild and install the Win32 executable while reusing `Orbitals_code.dll`.
When updating an existing RC3 installation, use `-RebuildCode` with the v0.1.0 kit to apply the ahead-of-time function discovery introduced in RC4.
The option recompiles your game module with the installed compiler and uses the runtime supplied in the kit.

Play:

```powershell
powershell -ExecutionPolicy Bypass -File games\Orbitals\Play-Orbitals.ps1                       # 30 FPS reference mode
powershell -ExecutionPolicy Bypass -File games\Orbitals\Play-Orbitals.ps1 -Mode Experimental60
powershell -ExecutionPolicy Bypass -File games\Orbitals\Play-Orbitals.ps1 -InternalResolution 720p -OutputSize 1920x1080 -DisplayMode Windowed
python\python.exe -B -m launcher --game-dir games\Orbitals                                      # the desktop launcher
```

The first session translates each shader the first time the game uses it. Vulkan waits for batches so that draws that run only once, such as lighting passes,
have their shaders. A missing shader can hold up a batch for up to 15 seconds. Later draws can pick up the shader if it arrives after the wait.
The results stay in `games\Orbitals\Orbitals_nvn\cache` for later sessions.

If you already have NVN2 shader captures, the optional offline command can verify and translate those captures ahead of a session.
Keep the renderer stopped while preparing the cache. With no captures, continue with the normal setup and live translation.
[Offline shader prewarm](docs/SHADER_PREWARM.md)

### By hand (what the script does)

```powershell
cmd /c Install.bat
python\python.exe -B tools\release\get_orbitals_deps.py --toolchain games\toolchain
$env:PATH = "$PWD\gcc\Library\bin;$PWD\games\toolchain\vulkan-bin;$env:PATH"
$env:VULKAN_SDK = "$PWD\runtime\edenvk\deps\vulkan-headers"      # the Vulkan headers shipped in the repository
python\python.exe -B tools\build_nvn.py --jobs 4                                   # build\nvn\libnvn.a; check that it ends with exit code 0
python\python.exe -B switchrecomp.py --build-runtime --cc gcc\Library\bin\x86_64-w64-mingw32-gcc.exe --target win64 --backend win32
mkdir games\Orbitals\Orbitals_data; cmd /c mklink /J games\Orbitals\Orbitals_data\exefs D:\path\to\Orbitals\exefs
cmd /c mklink /J games\Orbitals\Orbitals_data\romfs D:\path\to\Orbitals\romfs
python\python.exe -B switchrecomp.py D:\path\to\Orbitals -o Orbitals --outdir games\Orbitals --runtime bin\runtime_win64_win32.exe `
    --cc gcc\Library\bin\x86_64-w64-mingw32-gcc.exe --target win64 --backend win32 -O 2 --jobs 4
```

Then copy `bin\runtime_win64_win32.exe` to `games\Orbitals\Orbitals.exe`, `games\toolchain\SDL3.dll` and
`tools\release\Play-Orbitals.ps1` into `games\Orbitals\`, and make `games\nxshader` (→ `tools\nxshader`) and `games\python`
(→ `python`) junctions: the runtime looks for `nxshader\nxs_live.py` and `python\python.exe` in its folder and up to three folders above.

Never add `--native` / `-march=native` for a build you share between PCs: the module must stay generic x86-64.

## Linux / Steam Deck

The runtime and the module are ELF x86-64 files. The Steam Deck has no compiler: build on a PC and copy the result.

### On Windows, for the Steam Deck (the validated path)

```powershell
python\python.exe -B tools\release\get_orbitals_deps.py --only spirv,glslang --toolchain external\orbitals-toolchain
python\python.exe -B tools\linux-cross\fetch_zig.py                  # Zig 0.15.2 (ziglang.org, pinned SHA-256)
python\python.exe -B tools\linux-cross\prepare-linux-sysroot.py      # Ubuntu 24.04 X11/GL headers and libraries (archive SHA-256 checked)
python\python.exe -B tools\linux-cross\prepare-opus.py
python\python.exe -B tools\steamdeck\cross\build.py runtime --jobs 4  # build\steamdeck-linux\Orbitals
python\python.exe -B switchrecomp.py D:\path\to\Orbitals --out Orbitals --outdir build\steamdeck-game --target linux --backend x11 --no-build
python\python.exe -B tools\steamdeck\cross\build.py code --jobs 4 --generated build\steamdeck-game\Orbitals_build   # build\steamdeck-linux\Orbitals_code.so
```

Make `build\steamdeck-game\Orbitals_data\{exefs,romfs}` junctions to your game data before the `--no-build` step, or it copies 10 GB.

### On Linux

Extract the Linux x86-64 release archive and open `Orbitals-Launcher.sh`. **Install from my files** uses the included Linux runtime
and recompiles the game module with GCC. Keep your ExeFS and RomFS in place. The installation links to them by default.

On Debian or Ubuntu with Python 3.12 or later, install the launcher, compiler and graphics dependencies using your distribution's packages.
Install the [.NET 10 runtime](https://learn.microsoft.com/en-us/dotnet/core/install/linux) for the live shader translator. You also need a
working Vulkan driver for your GPU. For example, on Ubuntu 24.04 you can install the remaining dependencies with:

```sh
sudo apt install build-essential python3-tk libx11-6 libgl1 libsdl2-2.0-0 libvulkan1 spirv-tools
bash Orbitals-Launcher.sh
```

**AppImage:** `chmod +x OrbitalsPCRecomp-<version>-x86_64.AppImage` and open it; it copies the kit to
`~/.local/share/OrbitalsPCRecomp/kit-<version>` and starts the launcher there (Python with Tk included). The other dependencies above
are still needed. Release managers build it from the Linux archive with `bash tools/release/make_appimage.sh <linux tar.gz> <version>
<out folder>` on any x86-64 Linux (WSL included).

For a source-only checkout, install `libx11-dev`, `libgl-dev`, `libopus-dev` and `glslang-tools` to build the runtime too. The same setup
can be run directly with `bash tools/build-orbitals-linux.sh /path/to/Orbitals games/Orbitals 4`.

### Install on the Deck

Copy to a folder such as `/home/deck/Games/Orbitals`:

```
Orbitals  Orbitals_code.so  orbitals-deck.sh  gpu-clock.sh      (tools/steamdeck/orbitals-deck.sh, tools/steamdeck/gpu-clock.sh)
Orbitals_data/exefs/  Orbitals_data/romfs/                       your game data
Orbitals_nvn/cache/                                               the shader cache of a Windows session (see below)
```

Then `bash tools/steamdeck/install-profile.sh <folder> steam_deck_720p30` writes the handheld profile, and `orbitals-deck.sh` starts the
game (desktop mode, or Steam → Add a Non-Steam Game in game mode). Nothing outside the folder is changed; SteamOS stays read-only.
`strip --strip-debug Orbitals_code.so` on the Deck brings the module from 1.1 GB to about 400 MB.

**Shaders on the Deck:** the live translator needs Python 3, the .NET 10 runtime and SPIRV-Tools, which SteamOS does not have. Play the
same scenes once on Windows and copy that game folder's `Orbitals_nvn/cache` to the Deck (it is made from your copy; do not share it).
A shader missing from the cache is skipped (that object is not drawn) and written to `Orbitals_nvn/cache/dumps` for a later translation.

## Checks after a build

```powershell
python -B -m unittest discover -s launcher/tests                    # launcher
python -B tools\release\make_public_tree.py --source HEAD --dry-run  # inspect tracked files for redistribution
```

`REGRESSION.md` lists the runtime's own regression tests (`tests/`), and
`tools/visual_suite` the capture comparison.
