# Liftoff — Orbitals PC Recomp v0.1.5

**Liftoff** is an unofficial native PC port of *Orbitals* (Nintendo Switch 2) for Windows and Linux / Steam Deck, made by static
recompilation on top of [SwitchRecomp by MZ Labs](SWITCH2RECOMP.md). v0.1.5 is its first public release.

> Not affiliated with, endorsed or sponsored by Nintendo or by the developers or publishers of *Orbitals*. **These archives contain no
> game files, no game code (original or recompiled), no keys and no firmware.** You build the game on your own PC from your own legally
> obtained copy.

## Downloads

| File | For |
|---|---|
| `OrbitalsPCRecomp-0.1.5-windows-x64.zip` | Windows 10/11 x64: open `Orbitals-Launcher.bat` |
| `OrbitalsPCRecomp-0.1.5-x86_64.AppImage` | Linux x86-64: `chmod +x`, then open it |
| `OrbitalsPCRecomp-0.1.5-linux-x64.tar.gz` | Linux x86-64 and the Steam Deck's files: open `Orbitals-Launcher.sh` |
| `OrbitalsPCRecomp-0.1.5-source.zip` / `.tar.gz` | the source tree |
| `SHA256SUMS.txt`, `MANIFEST.json` | the SHA-256 of each file; every file of every archive with its origin and license |

You need your own copy of the game (a folder with `exefs/` and `romfs/`), 16 GB of RAM, a Vulkan 1.3 GPU and about 5 GB of disk. On
Linux, gcc, SPIRV-Tools and the .NET 10 runtime from your distribution (the launcher names the packages if one is missing).
Quick start: [README.md](../README.md#getting-started).

## What's in it

**Launcher**
- A title screen of its own, with one menu for the next step: INSTALL ORBITALS, or PLAY, PREPARE SHADERS, SETTINGS, PROFILES, HELP.
- A demoscene screen for each long task, with the real progress: an ARM64-to-C listing and a vector wireframe during the recompile,
  a plasma under a ball of dots during the shader preparation.
- A game compiled by an older version is detected and recompiled with this one; the saves are copied, the old installation is kept.
- Updates: the launcher checks this repository's latest release (Settings can turn it off), downloads the archive for your system when
  you accept, checks it against the release's `SHA256SUMS.txt`, unpacks it beside the current one and opens it.
- Linux: missing tools named with the packages for your distribution (apt, dnf, pacman, zypper), the install command in the clipboard.

**Shaders and loading**
- **Prepare shaders** translates all 23,134 shaders of the game from your files before the first session (about 15 minutes on a
  recent PC, 23 on a Steam Deck), so the first playthrough does not pause. 853 pipeline states are built while the game boots.

**Rendering**
- Fires, smoke, exhaust, character thrusters and the rainbow curtain behind the ship bay are drawn.
- The red and blue flashes after the opening film are gone (the particle sort's shared memory size).
- AMD, Intel and the Steam Deck: subgroups of 32 lanes as the game's shaders expect, and shared memory accesses kept in order (the
  game's particle sort was compiled for NVIDIA's lockstep warps): no giant green / blue sprites in space, the curtain in the in-game
  cutscene. NVIDIA's driver is unchanged.

**Linux and the Steam Deck**
- One AppImage for Linux (its own Python with Tk, used when the system's has no Tk with scalable fonts).
- No more stutter from memory checks: the runtime asked the kernel's memory map for every unknown page and every movie frame; it now
  asks the kernel directly. Cutscene movies stay in sync with their sound. Steam Deck co-op: twice the frame rate in the heaviest
  stretch measured.
- The **Performance** preset: 3D at 1280×720, all effects kept (Steam Deck co-op about +13 %).

**Settings**
- In-game **PC settings** on Windows, from the game's own Settings screen: display, frame rate, live 3D resolution, volume, keyboard
  player, mouse camera, vibration.

## Measured performance (co-op)

| Machine | Mode | FPS |
|---|---|---:|
| RTX 5070 Laptop + i7-14650HX, 1080p | 30 (reference) | 30 |
| same | 60 (experimental) | ≈ 51–54 |
| Steam Deck OLED, 15 W | 30, Performance preset, colony | ≈ 21–22 |
| same | 30, High, space scene | ≈ 17–19 |

## Known issues

- **60 FPS is experimental**: co-op stays below 60 on the tested PCs.
- Steam Deck co-op is GPU-bound (17–22 FPS depending on the scene).
- The rainbow curtain's hues may differ from the console's (more pink and violet); an aligned console capture is needed to settle it.
- The in-game PC settings panel is Windows only; on Linux use the launcher or `Orbitals.ini`.
- AMD Radeon on Windows and Intel GPUs have had little testing: reports are welcome.
- No online or LAN play. Full list: [KNOWN_ISSUES.md](../KNOWN_ISSUES.md).

## Reporting a problem

Use the issue templates, with a report made by the launcher's **HELP → Create a report** (logs with local paths masked, system and GPU
information, settings; never your saves or any game file).

## Verify the archives

`SHA256SUMS.txt` lists every file of the release; `MANIFEST.json` lists every file of every archive with its SHA-256, origin and license.
The AppImage holds the Linux archive's kit, CPython 3.12.16 from python-build-standalone (PSF license; its components' licenses are inside,
under `usr/python`) and the AppImage runtime (MIT).
