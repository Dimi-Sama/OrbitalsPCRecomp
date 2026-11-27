# Steam Deck tools (branch `claude-steamdeck`)

## Build the Linux ELF files on Windows

Needs the cross folder of `orbitals-dev-vulkan-linux` (`build/linux-cross`: Zig 0.15.2 for Windows and the Ubuntu 24.04 sysroot made
by its `prepare-linux-sysroot.py` / `prepare-opus.py`) and the toolchain's `vulkan-bin` (glslang). Paths default to the sibling
worktrees; override with `ORBITALS_LINUX_CROSS` and `ORBITALS_TOOLCHAIN`.

```sh
python tools/steamdeck/cross/build.py runtime --jobs 8          # build/steamdeck-linux/Orbitals (PIE, symbols kept)
python switchrecomp.py <GAME_DATA> --out Orbitals --outdir build/steamdeck-game --target linux --backend x11 --no-build
python tools/steamdeck/cross/build.py code --jobs 10 --generated build/steamdeck-game/Orbitals_build
                                                                 # build/steamdeck-linux/Orbitals_code.so (~8 min on 10 jobs)
```

`build/steamdeck-game/Orbitals_data/{exefs,romfs}` should be junctions to the game data before the generation, otherwise
`switchrecomp.py` copies the 9.6 GB RomFS. `build/steamdeck-game/Orbitals.hints` is the hint list the generation uses.
Copy the generated `Orbitals_code.build.json` alongside the module. The recorded checksum covers the linked output.

## Install on the Deck (`/home/deck/Downloads/Orbital`)

Folder layout (no root, nothing outside the folder):

```
Orbitals  Orbitals_code.so  Orbitals_code.build.json  Orbitals.ini  Orbitals.hints  orbitals-deck.sh
Orbitals_nvn/cache/   (translated shaders: required, Linux has no on-demand translation)
Orbitals_nvn/vk/      (pipeline cache: pipelines-1002-1435.bin is RADV's for this Deck, optional)
Orbitals_data/exefs/  Orbitals_data/romfs/  Orbitals_data/save/
```

```sh
bash tools/steamdeck/install-profile.sh /home/deck/Downloads/Orbital steam_deck_720p30
/home/deck/Downloads/Orbital/orbitals-deck.sh                    # desktop mode
```

Game mode: Steam → Add a Non-Steam Game → `orbitals-deck.sh`. The Deck's controls are player 1 (Steam Input's gamepad or, in
desktop mode, SDL's `Steam Deck Controller`); a Bluetooth/USB controller is player 2.

## Measure on the Deck

`deck-run.sh` makes an isolated run folder per run (copied save, linked data and cache), keeps the screen on (`kde-inhibit`), logs
1 Hz telemetry (APU power, GPU clock and load, CPU, RSS, VRAM/GTT, temperatures, fan, battery) and optionally captures and `perf`.

```sh
# on the Deck, from ~/Downloads/Orbitals-dev (base/ = an installed game folder, Orbitals_data/ = exefs + romfs)
bash tools/deck-run.sh coop --base base --data Orbitals_data --seconds 320 --ini ue_fps=30 \
    --script "$(cat tools/coop-deck.script)" --script2 "$(cat tools/coop-deck.script2)" --shots 230-320/15000
# on the PC
bash tools/steamdeck/pull-run.sh <run-name>                      # -> build/deck-runs/<run-name>
python tools/steamdeck/deck_report.py <run-name>:label --window 230:320
```

`coop-deck.script{,2}` is the laptop's co-op path (`coop-path.script{,2}`) with the Deck's longer loads: B held 6 s out of every 7
from 150 to 262 s skips the intro movie whenever it starts, and the gameplay inputs move 85 s later. Co-op gameplay is on screen
from ~230 s; compare runs on 230–320 s. `coop-path.script{,2}` (no skip) plays the movie: compare 200–290 s.

Useful switches: `NXRT_VK_LOG_RES=1` (draw resolutions), `NXRT_VK_GPUTIME_AT_S=290` (per-pass GPU time),
`--perf 260-290` (perf record, then `perf report -i perf.data` on the Deck), `SWR_ALLOW_SCREENSAVER=1`, `NXRT_VK_RT_KEEP=0`.

## For Codex (netplay branch)

Take the commits of `claude-steamdeck` on top of `orbitals-dev-vulkan-linux` (`git log orbitals-dev-vulkan-linux..claude-steamdeck`).
The Linux fixes (PIE, hidden Vulkan pointers, screen saver) are needed by any Linux build of the runtime made with Zig; a native GCC
build on Linux is PIE by default but still needs the hidden pointers and the screen saver inhibition. Nothing here touches input,
IPC or networking code. The candidate build is `build/steamdeck-candidate/` (see `STEAM_DECK_PERFORMANCE.md`).
