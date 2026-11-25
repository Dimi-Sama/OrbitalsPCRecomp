# Orbitals PC Recomp launcher

A desktop launcher in Python and Tk for Windows and Linux: installation from your own game files, saves, graphics settings and bug
reports. Its title card, logotype and icon are its own drawings (`tools/launcher_art`), without art of the game. The `launcher/` folder
holds the interface, the local operations and the tests.

## Start

From the repository root, with Python 3.12 or later and Tk.

**Windows**: double-click `Orbitals-Launcher.bat` (it finds a suitable Python and opens the launcher without a console window, or offers
to install Python 3.13 with winget), or:

```powershell
python -B -m launcher
```

`pythonw -B -m launcher` opens the same window without a console. The data folder needs a local NTFS volume (it uses junctions). Python can
live anywhere; it does not have to be next to the Orbitals build. The Python that `Install.bat` downloads for the recompiler has no Tk
and cannot run the launcher.

**Linux x86-64**: double-click `Orbitals-Launcher.desktop` (or `Orbitals-Launcher.sh`) in the file manager; no terminal opens. If Python
3.12+ with Tk is missing, a window says which packages to install (Arch / CachyOS: `python tk`; Debian / Ubuntu: `python3 python3-tk`).
`./Orbitals-Launcher.sh --menu` adds the launcher to the application menu after asking. Some file managers ask once whether to trust or
run a `.desktop` file or a script. From a terminal:

```sh
python3 -B -m tkinter     # checks that Tk works (Debian / Ubuntu: the python3-tk package)
python3 -B -m launcher
```

On the Steam Deck, use the desktop mode with Python and Tk available for the installation (choosing a folder opens the system's own
dialog). **TOOLS → Add to Steam** then starts the launcher from Gaming Mode.

A controller drives the launcher (SDL3, SDL2 or XInput): the directions choose, A takes, B goes back, the shoulders change the settings'
tab and Start plays. Only while its window is in front and no game runs. **General → Controller in the launcher** turns it off;
*Automatic* leaves it off on the Deck's desktop, where Steam Input already turns the controls into keys and a mouse.

`--game-dir` selects a local build explicitly. `--data-dir` uses another folder for saves and reports. By default the launcher keeps
its data in `%LOCALAPPDATA%/OrbitalsLauncher` on Windows, and in `$XDG_DATA_HOME/orbitals-launcher` or `~/.local/share/orbitals-launcher`
on Linux.

## Install and play

1. **GAME FILES** (Windows and Linux x86-64). Choose the folder extracted from your copy of the game, with `exefs/` and `romfs/`, then
   **INSTALL**. Windows setup downloads and verifies the build tools. Linux setup uses the dependencies in
   [BUILDING.md](../BUILDING.md#linux--steam-deck). Both recompile your game locally and select the new installation. The page shows each
   step, the time left once it can be told, and what failed with **Try again**; the output is in `games/setup.log`. **Stop** keeps what is
   compiled: installing again continues from there. Unpacking the first tools and the last step are not cut short.
2. Or **Use an installation made before**: the folder with `Orbitals.exe` and `Orbitals_code.dll` (Windows) or `Orbitals` and
   `Orbitals_code.so` (Linux), made by the setup or by BUILDING.md.
3. **Play**. *READY* means the expected layout is there; the rendering itself depends on the build, its dependencies and the
   GPU driver.

The title screen's menu holds the pages. A card on its left says what needs you, one thing at a time: a failure with what can be done
about it, a new version, a game compiled by an older one, shaders not prepared. The chips under it (game, shaders) and the
controllers' line lead to their pages. The arrow keys reach all of it, and F11 makes the window full screen.

The first session translates the game's shaders while it runs: the picture can pause for a few seconds, mostly behind loading screens
(KNOWN_ISSUES.md). Later sessions use the cache, which the launcher keeps per game build (seeded once from the game folder's own cache).
If `control.nacp` is available, the launcher shows the game's version; otherwise the ExeFS build id. The release and commit of the
runtime come from the first lines of its log, once a session has run. The `.nup` format is shown as not supported.

## Saves and settings

The runtime finds `Orbitals_data/save` from its executable's path, so each session runs from a launch folder where that path points to
the launcher's saves. ExeFS and RomFS are linked read-only; the original installation is never written.

**SAVES** backs them up, imports and exports them. To continue a game played from another build, use **Import or restore** with its
`Orbitals_data/save`; a restore keeps the previous save in `backups/`. Earlier versions of the launcher kept profiles, each with its own
saves and settings: if you made several, **Saves in use** chooses which one plays.

A setting is saved as soon as it is changed and applies at the next launch; what the selected one does stands beside the rows.
The arrow keys go through the rows and change their values, Ctrl+Tab goes through the tabs, and clicking a value lists all of them.
A dot marks a value that is not the default. While the game runs the rows are read-only: its own PC settings apply, and are read
when it closes.

In **Graphics**, choose **High** for the game's TV profile, **Low** for its handheld profile, or **Custom** to choose an internal 3D
resolution from 960×540 to 1920×1080. The game draws the HUD at 1080p. Set the physical output size in **Windowed** mode. **Borderless**
uses the monitor's desktop resolution. The same tab sets upscaling, VSync and frame rate. **30 (async replay)** keeps the 30 FPS cap
with replay on a separate thread. It reduced cinematic slowdown under CPU contention in the Windows test. Settings
apply at the next launch. See GRAPHICS_SETTINGS.md for the measurements. **General** contains the volume, the title
screen's animation, the issues URL and the check for updates at start.
On Windows, **F1 → 3D resolution (this session)** changes the actual scene resolution while the game is running.

## Controls

The **Controls** tab scans connected controllers with the game's input backend. Use **Scan** after connecting or replacing a
controller. Orbitals also detects hot-plugged controllers during play.

The keyboard remains available with a controller connected. Choose **Player 2** for local co-op with a controller as Player 1
and keyboard and mouse as Player 2. If Player 1's controller is absent, the keyboard and mouse control Player 1.

Choose **Mouse + IJKL** to enable the mouse camera at launch. **F2** toggles the mouse during a session. Left and right click
control ZR and ZL. WASD moves the left stick, and IJKL can move the right stick. **Game default** and a blank speed use the runtime's
INI settings.

## Tools

**Desktop shortcut** (on Linux, **Application menu**) adds the launcher with its icon. On Windows the launcher has an identity of its own,
so the taskbar shows its icon, and a pin starts `Orbitals-Launcher.pyw`.

**Add to Steam** adds the launcher as a non-Steam game for every Steam user of the PC, with library images drawn as the launcher's
title card. The other shortcuts are kept, and a copy of the list before is left beside it (`shortcuts.vdf.before-orbitals`); an image you
set yourself stays. Part of it is from [mkw-recomp](https://github.com/adriadam10/mkw-recomp) (MIT, `LICENSE_mkw-recomp.txt`).

## Report a problem

1. **TOOLS → Report a problem**: choose the category, describe the steps to reproduce.
2. Choose what to include, then **Preview**. Logs go through a filter that masks recognised local paths, some secrets, e-mail addresses
   and public IP addresses. Check them before posting. Saves are off by default; each save file must be chosen explicitly and is
   included as a binary copy.
3. **Create the ZIP**. The output folder also holds `issue.md`; **Copy the text** is in the preview.
4. **GitHub issues** opens the configured issues page, where you can attach the ZIP you checked. Use **All releases** in Tools to
   browse private previews with your signed-in GitHub account. **Check now** there checks the latest public stable release through GitHub's API.

```text
Orbitals-BugReport-<timestamp>.zip
  README.txt
  issue.md
  manifest.json
  logs/
    Orbitals.log, console.log, threads.txt, crash.log, exit.json
    launcher.log, launcher.log.1
  system/
    system_info.json, gpu_info.json, build_info.json
  config/
    settings.json
  saves/
    <type>/<selected GVAS file>
```

The contents depend on the boxes ticked and the files available. The manifest lists every file with its size and SHA-256, and the
requested items that were missing. `gpu_info.json` comes from `vulkaninfo --summary` when that command exists; the release, commit and
Vulkan device also come from the game log. The 24 MB limit leaves a margin under
[GitHub's attachment limit](https://docs.github.com/en/get-started/writing-on-github/working-with-advanced-formatting/attaching-files).
Reports are never sent automatically.

## Drawings and typefaces

`tools/launcher_art/render.py` draws the icon, the logotype and the Steam images again (it needs Pillow and the Dela Gothic One font, SIL
Open Font License). `launcher/paint.py` draws the bars, the screentone and the small shapes while the launcher runs, at the screen's
scale. Barlow and Barlow Condensed (SIL Open Font License, `assets/fonts/OFL.txt`) are loaded for the launcher only: nothing is installed.

## Tests and distribution

```text
python -B -m unittest discover -s launcher/tests -v
python -B -m launcher.tests.shots OUT --size 880x650 --dpi 144
```

The second line writes a picture of every page (it needs Pillow).

The launcher runs from source with the standard library and Tk. The tests cover detection, preparation, the isolation of saves, restores,
launch errors, graphics settings (including values saved by the earlier French interface), the update check, the installer step
parsing, stopping a job, the Steam shortcut and the reports, and every page of the window at its minimum size. The launcher was checked with the Windows runtime. The Linux x86-64 package can be tested using the
[the README](../README.md#getting-started).

The audit also looked at the installation and save handling of [Hookshot-rs](https://github.com/dazemc/Hookshot-rs) and
[mkw-recomp](https://github.com/adriadam10/mkw-recomp/blob/main/tools/prepare/README.md).
