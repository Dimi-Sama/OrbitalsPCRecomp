# Orbitals on the Steam Deck: native Linux, 720p30 profile, measurements

Branch `claude-steamdeck`, based on `orbitals-dev-vulkan-linux` (023e681). Codex's branches were not modified.

All figures below were measured **on the Steam Deck** (no laptop number is extrapolated):
Steam Deck OLED (DMI `Galileo`, AMD Custom APU 0932, 4 Zen 2 cores / 8 threads, RDNA 2 GPU 200–1600 MHz, 15 W APU limit),
SteamOS 3.8.16, Linux 6.16.12-valve24.5, Mesa 26.0.0-devel RADV (VANGOGH), Vulkan 1.4.330, desktop mode (KDE Plasma, Xwayland),
1280×800 panel at 90 Hz, mains power, game data on the internal NVMe. Each run is a separate process with its own copy of the save,
the same shader cache, the same scripted inputs for both players (`tools/steamdeck/coop-deck.script{,2}`) and 1 Hz telemetry.

## 1. What was needed to start the game on Linux at all

The Linux build had never run before (only its ELF format had been checked). Three bugs, all fixed:

| Symptom on the Deck | Cause | Fix |
|---|---|---|
| `FATAL: Could not reserve the game's addresses (8000000-2000000000)` | The Zig cross build linked the runtime at 0x1000000; Linux places the brk heap up to 1 GB after it, inside the range `renderer=vulkan` maps at the game's own addresses | Runtime linked as a PIE (`tools/steamdeck/cross/build.py`, libnvn with `-fPIE`) |
| SIGSEGV executing `vkEnumerateInstanceVersion` before the first frame | `-rdynamic` exported the runtime's Vulkan function *pointers* under the commands' names; the loader and the Deck's implicit layers (MangoHud, gamescope WSI, Lossless Scaling) called them by name | Pointers and glibc shims hidden; no `-rdynamic` in the cross build (the module imports only `memcpy/memset/sqrt/sqrtf`) |
| Game frozen at 2 presents/s, 454 ms per `vkAcquireNextImageKHR` | An unattended Deck in desktop mode turns its screen off; a gamepad-only player gives KDE no input activity; FIFO presents then wait | `org.freedesktop.ScreenSaver.Inhibit` over D-Bus while the game runs (`SWR_ALLOW_SCREENSAVER=1` to opt out) |

Since then: title screen, menus, character select, the intro movie and co-op gameplay ("Réparer le vaisseau / Quitter la colonie",
both players and HUD drawn), exit code 0 on every run. The Deck's built-in controls are detected as `Steam Deck Controller` (SDL2),
audio goes through SDL2/PipeWire, saves go to `Orbitals_data/save`.

SteamOS stays untouched: no root, no package, nothing written outside the game folder (and `~/.cache/mesa_shader_cache` by
Mesa). Everything the runtime loads is in SteamOS 3.8 already: glibc, libX11/Xwayland, libvulkan + RADV, SDL2 (sdl2-compat over
SDL3), libdbus; Opus is linked statically. The runtime is built for glibc 2.34 and needs no newer symbol. Tested in desktop mode
over SSH (KDE Plasma, Xwayland); game mode (gamescope) is expected to work the same way (X11 window through gamescope's Xwayland,
Steam Input's virtual gamepad as player 1) but was not exercised: it needs the Deck's own UI.

## 2. Resolution: what the game really renders

`NXRT_VK_LOG_RES=1` (new) logs the viewport sizes the draws use. Measured in handheld mode (`docked=0`):

* The game's final image is **1920×1080** in handheld mode too (the Switch 2 handheld screen is 1080p): the swap chain starts at
  1280×720 for the boot logos, then the game recreates it at 1920×1080. `ResX`/`ResY` on its command line are ignored.
* Its 3D is drawn at **1600×900** (83 %), **two 800×900 views** in co-op; the HUD at 1920×1080; the runtime scales the picture to
  1280×720 on the 1280×800 panel.
* The game looks for Unreal's user config layer `Orbitals/Saved/Config/Switch2/*.ini` in its RomFS. The new RomFS overlay
  (`Orbitals_data/romfs_overlay`) serves such files and the game reads them, but `r.ScreenPercentage` and
  `r.DynamicRes.MaxScreenPercentage` set there (`[SystemSettings]`, `[ConsoleVariables]`, device profile CVars) do not change the
  1600×900: the game sets its resolution later, from code.
* With `game_dynamic_resolution=1` the game's own dynamic resolution works on the Deck and drops co-op to **480×540 per view**.
  The GPU time stays at ~56 ms per frame and the frame rate barely moves (13.8 vs 13.2 FPS): on the Deck **the GPU time does not
  follow the pixel count** (per-pass GPU timing: the G-buffer pass costs 5.7 ms at both resolutions, the depth pre-pass more at the
  lower one). Lowering the resolution, natively or with FSR 1, is not what limits co-op today; the profile therefore keeps the
  game's 1600×900 and does not present an upscaled image as native 720p.

## 3. Where the time goes in co-op (Deck)

Per-pass GPU timing (`NXRT_VK_GPUTIME_AT_S`, new) and `perf` on the Deck (user space, 499 Hz, 30 s of co-op):

* **The APU is at its 15 W limit** (15.1–15.6 W) with the game keeping ~4 cores busy (395–405 %). The GPU, 77–88 % busy, runs at
  **500–850 MHz on average** instead of 1600. The CPU takes most of the power budget, but capping it does not give the GPU more: under a
  cgroup CPU quota (300 %, 250 %) the APU drops to 8 W and the GPU clock stays at 720–840 MHz while FPS falls to 8.6 / 7.0 (section 4.5).
* GPU, one co-op frame: 430 render passes (55–62 ms), 130 dispatches (4–8 ms). 235 of the passes are one draw each (Unreal's
  deferred lights). **Corrected in section 4.7**: they are not split by inline uniform updates (the co-op path makes none,
  `NXRT_VK_UBSTAT`) but by Unreal unbinding every target between lights (416 of the 429 pass ends a frame, `NXRT_VK_RTWHY`).
  Removing the pass-begin barrier entirely (measurement switch `NXRT_VK_PASS_BARRIER=0`, wrong pictures possible) gained 9 % FPS
  in 60 mode; merging the light passes (section 4.7) did not.
* CPU (4.2 cores): NVN translation thread 74 % of a core (RADV, `memcpy` of uploads, `vkm_use_`, descriptor writes); the GPU
  write-back landing thread 35 % of a core, 83 % of it `bcmp`: **41 MB a frame are copied back from the GPU and compared, of which
  ~600 KB (151 000 words) changed**; five game worker threads; the game thread.
* In the intro movie the Bink 2 decoder (the game's own, recompiled) runs on two threads; ~40 % of their time was in the AdvSIMD
  interpreter fallback (`swr_simd`) for instructions the code generator did not translate inline.

## 4. Changes and their measured effect

### 4.1 `ue_fps=30` (new): the game's own 30 FPS with the NVN translation on its own thread

`ue_fps=0` translates NVN on the game's render thread; `ue_fps=60` moves it to its own thread but presents every vblank. `ue_fps=30`
keeps the game's 2-vblank interval (each image shown 3 vblanks on the 90 Hz panel) and moves the translation to its own thread:
in co-op the GPU no longer idles waiting for submissions (35 ms → 1 ms a frame). Simulation, movie and audio speed are unchanged
(Unreal takes its delta time from the clock; nothing in the game's timing is altered).

### 4.2 Inline AdvSIMD translation for the Bink 2 decoder and the game's workers

New inline templates in `a64.py`, each checked against the reference interpreter (`tests/a64/simd_inline_diff.py`, 3000 random
encodings × 8 random states per seed, 14 seeds, also with flush-to-zero; 0 mismatches):
LD1/ST1 one lane and LD1R (552 of the 724 fallback sites of the decoder's hottest function), MOVI/MVNI/ORR/BIC immediates (all
forms but FMOV), integer MLA/MLS/MUL by element (the decoder's inverse transform), SADDLP/UADDLP, SHLL, BSL/BIT/BIF, SQDMULH/SQRDMULH.
AdvSIMD fallback sites in the whole game: 82 562 → 48 902; a third generation (SLI/SRI, FMOV immediate, ADDV/MAXV/MINV, scalar DUP)
brings them to 40 207.

### 4.3 Results

Co-op gameplay ("Quitter la colonie", both players), 230–320 s of `coop-deck.script`:

| Run | Window (s) | FPS | p50 ms | p95 ms | p99 ms | worst ms | frames > 2x p50 /min | APU W | GPU MHz | game CPU % | GPU busy % | max edge C | max RSS MB |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| ue_fps=0, original module (before) | 230:320 | 11.6 | 83.9 | 96.0 | 109.8 | 262 | 4.0 | 15.6 | 668 | 356 | 77 | 72 | 5343 |
| ue_fps=60 | 230:320 | 13.2 | 73.2 | 96.3 | 114.1 | 193 | 4.0 | 14.9 | 740 | 403 | 84 | 73 | 5343 |
| ue_fps=60 + game dynamic resolution (480x540 views) | 230:320 | 13.8 | 70.8 | 97.5 | 137.6 | 404 | 7.3 | 15.3 | 506 | 404 | 86 | 72 | 5367 |
| ue_fps=30 | 230:320 | 14.3 | 69.3 | 88.6 | 98.0 | 173 | 2.7 | 15.3 | 849 | 405 | 88 | 71 | 5336 |
| ue_fps=30 + SIMD (1st generation) | 230:320 | 14.4 | 68.4 | 87.8 | 99.1 | 185 | 3.3 | 15.4 | 782 | 399 | 86 | 71 | 5326 |
| ue_fps=30 + SIMD (2nd generation) | 230:320 | 14.4 | 68.8 | 88.3 | 96.1 | 175 | 2.7 | 14.6 | 772 | 397 | 86 | 72 | 5355 |
| **candidate build (profile)** | 230:320 | 14.6 | 68.6 | 88.7 | 100.7 | 157 | 4.0 | 15.1 | 833 | 396 | 84 | 72 | 5300 |

Intro movie (Bink 2, 1920×1080 at 24 FPS, not skipped), 200–290 s of `coop-path.script`; two runs each, the spread between runs is ±0.6 FPS:

| Run | Window (s) | FPS | p50 ms | p95 ms | p99 ms | worst ms | frames > 2x p50 /min | APU W | GPU MHz | game CPU % | GPU busy % | max edge C | max RSS MB |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| original module, run 1 | 200:290 | 21.4 | 45.6 | 60.8 | 65.8 | 139 | 3.3 | 15.3 | 403 | 452 | 70 | 70 | 5241 |
| original module, run 2 | 200:290 | 21.7 | 44.2 | 59.0 | 67.6 | 391 | 5.3 | 15.3 | 335 | 455 | 80 | 71 | 5229 |
| SIMD 1st gen, run 1 | 200:290 | 22.7 | 43.3 | 57.2 | 62.3 | 124 | 2.7 | 15.7 | 399 | 443 | 74 | 71 | 5223 |
| SIMD 1st gen, run 2 | 200:290 | 21.6 | 45.7 | 61.8 | 69.1 | 126 | 2.7 | 15.4 | 405 | 430 | 66 | 71 | 5245 |
| SIMD 2nd gen, run 1 | 200:290 | 21.6 | 45.3 | 63.2 | 68.8 | 138 | 3.3 | 15.4 | 500 | 412 | 52 | 71 | 5242 |
| SIMD 2nd gen, run 2 | 200:290 | 22.8 | 42.2 | 56.5 | 62.4 | 232 | 4.7 | 14.5 | 451 | 431 | 64 | 71 | 5252 |

Menus (title, main menu, character select), 20–100 s:

| Run | Window (s) | FPS | p50 ms | p95 ms | p99 ms | worst ms | frames > 2x p50 /min | APU W | GPU MHz | game CPU % | GPU busy % | max edge C | max RSS MB |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| ue_fps=0 | 20:100 | 29.8 | 33.3 | 33.4 | 34.4 | 181 | 3.8 | 7.4 | 713 | 143 | 54 | 65 | 2419 |
| ue_fps=60 | 20:100 | 58.8 | 16.7 | 18.3 | 22.2 | 317 | 8.2 | 13.6 | 1364 | 239 | 88 | 77 | 2445 |
| ue_fps=30 | 20:100 | 29.8 | 33.3 | 33.3 | 33.3 | 180 | 3.8 | 8.0 | 789 | 127 | 61 | 61 | 2440 |
| **candidate build** | 20:100 | 29.8 | 33.3 | 33.6 | 33.8 | 195 | 5.2 | 7.6 | 778 | 121 | 57 | 66 | 2450 |

Memory and heat in co-op: game RSS 5.3 GB (of 16 GB), GTT 2.6 GB, VRAM 1.0 GB (the BIOS carve-out), APU edge temperature
≤ 72 °C, fan 5 900–6 000 RPM. Menus at 30 FPS: RSS 2.4 GB, 7.6–8.0 W.


Third code generation (one run each): co-op unchanged, the movie at its best measurement so far.

| Run | Window (s) | FPS | p50 ms | p95 ms | p99 ms | worst ms | frames > 2x p50 /min | APU W | GPU MHz | game CPU % | GPU busy % | max edge C | max RSS MB |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| co-op SIMD 2nd gen | 230:320 | 14.4 | 68.8 | 88.3 | 96.1 | 175 | 2.7 | 14.6 | 772 | 397 | 86 | 72 | 5355 |
| co-op SIMD 3rd gen | 230:320 | 14.2 | 69.8 | 90.2 | 99.6 | 180 | 1.3 | 14.7 | 748 | 403 | 88 | 71 | 5372 |

| Run | Window (s) | FPS | p50 ms | p95 ms | p99 ms | worst ms | frames > 2x p50 /min | APU W | GPU MHz | game CPU % | GPU busy % | max edge C | max RSS MB |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| movie SIMD 3rd gen | 200:290 | 23.3 | 41.8 | 54.7 | 62.8 | 218 | 0.7 | 15.5 | 402 | 443 | 71 | 70 | 5258 |

### 4.4 Long session

The candidate build for 30 minutes (`soak30min-20261120-153647`): menus, the co-op path, then both players standing in co-op
gameplay until 1800 s. No error in the log, exit code 0. Game RSS 5 381–5 383 MB from 300 s to the end (no growth), GTT
2.51–2.53 GB, VRAM 1.0 GB, APU edge 69–73 °C, fan 5 900–5 950 RPM, APU 14.6–14.8 W in co-op.

| Run | Window (s) | FPS | p50 ms | p95 ms | p99 ms | worst ms | frames > 2x p50 /min | APU W | GPU MHz | game CPU % | GPU busy % | max edge C | max RSS MB |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 30 min, candidate build | 20:100 | 29.8 | 33.3 | 33.3 | 33.3 | 186 | 3.8 | 7.6 | 749 | 129 | 58 | 65 | 2433 |
| 30 min, candidate build | 240:600 | 15.3 | 64.3 | 85.9 | 96.7 | 171 | 0.5 | 14.8 | 822 | 418 | 90 | 72 | 5382 |
| 30 min, candidate build | 600:900 | 15.6 | 63.6 | 83.8 | 94.7 | 168 | 0.8 | 14.6 | 821 | 423 | 89 | 72 | 5382 |
| 30 min, candidate build | 900:1200 | 15.6 | 63.3 | 83.5 | 94.2 | 148 | 0.6 | 14.6 | 844 | 423 | 86 | 73 | 5382 |
| 30 min, candidate build | 1200:1500 | 15.7 | 62.7 | 83.5 | 94.6 | 144 | 1.0 | 14.7 | 854 | 423 | 90 | 72 | 5382 |
| 30 min, candidate build | 1500:1800 | 15.1 | 64.5 | 88.4 | 96.7 | 148 | 1.0 | 14.6 | 836 | 418 | 90 | 72 | 5383 |

### 4.5 Ideas measured and dropped

* **CPU quota** (cgroup `cpu.max` through `systemd-run --user -p CPUQuota=`, no root), to leave the GPU more of the 15 W:

| Run | Window (s) | FPS | p50 ms | p95 ms | p99 ms | worst ms | frames > 2x p50 /min | APU W | GPU MHz | game CPU % | GPU busy % | max edge C | max RSS MB |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| candidate, no quota | 230:320 | 14.6 | 68.6 | 88.7 | 100.7 | 157 | 4.0 | 15.1 | 833 | 396 | 84 | 72 | 5300 |
| candidate, CPUQuota=300% | 230:320 | 8.6 | 110.0 | 165.5 | 177.2 | 222 | 0.7 | 8.0 | 840 | 326 | 62 | 63 | 5343 |
| candidate, CPUQuota=250% | 230:320 | 7.0 | 128.7 | 198.0 | 222.5 | 287 | 1.3 | 7.9 | 721 | 274 | 47 | 60 | 5305 |

  The GPU clock does not rise; less CPU only means fewer frames. Not used.
* **Coalescing the write-backs of one submission** (one base copy and one final copy for a range written by several dispatches):
  `NXRT_VK_WBLOG=262144 NXRT_VK_WBLOG_REC=1` in co-op shows 15.1 MB a frame of write-backs of 256 KB or more, only 12 % of it a range
  already recorded in the same frame (`tools/steamdeck/wblog_repeats.py`). At most ~4 % of the traffic, for a change that touches the
  upload / write-back ordering: not done.
* **Lower resolution through the game's config or its dynamic resolution**: section 2.
* **Keeping the pass open on identical target binds**: implemented (`NXRT_VK_RT_KEEP`), but the per-light passes are split by inline
  uniform updates first, so it keeps no pass in Orbitals' co-op.

### 4.6 Laptop iGPU (weak PC reference)

Same co-op path on the laptop's integrated GPU (Intel UHD of the Core i7-14650HX, "RaptorLake-S Mobile Graphics Controller", Vulkan
1.3.293, driver 101.6078; `NXRT_VK_DEVICE=Intel`), Windows runtime of this branch, `ue_fps=30`, 1280×720 window. Frame times from
`frames.csv` (no power telemetry on Windows):

| Run | Menus 20–100 s | Co-op 230–330 s | p50 / p95 co-op | GPU per co-op frame |
|---|---:|---:|---:|---:|
| TV mode (`docked=1`): 3D 2 × 960×1080 | 12.9 FPS | 4.0 FPS | 247 / 436 ms | 233 ms (passes 172, dispatches 48) |
| Handheld (`docked=0`): 3D 2 × 800×900 | 19.4 FPS | 5.2 FPS | 190 / 323 ms | 190 ms (passes 131, dispatches 35) |
| TV mode + `game_dynamic_resolution=1` | 13.4 FPS | 4.1 FPS | 246 / 437 ms | 235 ms (the game kept 960×1080) |

This iGPU is several times slower than the Deck's; unlike the Deck it is pixel bound (31 % fewer pixels → 18 % less GPU time), and
the G-buffer (28 ms), the 235 per-light passes (27 ms, 115 µs each) and the base pass (14 ms) dominate. It also shows a **rendering
bug of its own**: triangle edges drawn as a white mesh over dark surfaces (ceiling cloth, pipes), absent on RADV and NVIDIA. The
device lacks `shaderStorageImageReadWithoutFormat`, which the translated shaders use ("shader corpus needs: … formatless storage
read/write 0/1 … [RED] something is missing"): those image loads are undefined there. Next step for such GPUs: give the translated
SPIR-V the image format when the device lacks formatless reads. Runs: `build/orbitals-debug/runs/igpu-*-20261120-*`.

### 4.7 Session of 2026-11-20 evening (Deck on the local network)

Method as above: the scripted co-op path, window 230–320 s, the candidate's shader and pipeline caches, runs of each variant
alternated in one queue, `ue_fps=30`. Reference runs of the session: 14.11–14.42 FPS (14.28, 14.42, 14.32, 14.11; 13.91 with
`perf stat` attached). Raw runs: `~/Downloads/Orbitals-dev/runs/` on the Deck (names below).

| Change | Result on the Deck | Kept |
|---|---|---|
| **Push descriptors** (`NXRT_VK_PUSH_DESC=1`, pixel shaders' sets; RADV `maxPushDescriptors` 32) — `ref-phases`, `push-fs` | replay 71.9 vs 71.6–72.6 ms a frame, 12.79 vs 12.80 FPS (phases on). Allocation + `vkUpdateDescriptorSets` are only ~3 ms of the ~72 ms replay; the cost is the bindings' resolution (`vkm_use` ~37 ms, uniform ranges ~16 ms) | code kept, off |
| **Write-backs compared on the GPU** (`NXRT_VK_WB_GPU=1`, `wb_diff.comp`) — `wbab-*`, `hotab-*` | **14.92 vs 14.22 FPS (+4.9 %)**, p50 64.8 vs 70.0 ms; later queue 15.21 FPS (3 runs). Differential check (`=2`): 534,027 ranges over menus, movie and co-op, 0 blocks differing from the CPU's comparison; ~1 MB a frame back instead of 41 MB | **on in `orbitals-deck.sh`** |
| `-march=znver2` module — `ab-*` | 14.50 vs 14.35 FPS (+1 %, noise level) | no |
| znver2 + `-ffp-contract=off` + hot functions moved together (`split_hot.py`, as Hookshot / mkw-recomp) — `hotab-*` | 15.05 vs 15.21 FPS (−1 %); `perf stat`: iTLB 12.5 % L2 misses ≈ 1 % of cycles, i-cache misses ≈ 3 %: little to win there | no (tool kept) |
| Unbind kept open (`NXRT_VK_RT_UNBIND_KEEP=1`, split-aware) — `unbsplit*` | passes 430 → ~110 a frame; 14.72 vs 14.76 FPS. Same pictures: alternate-frame test (`=2`), neighbouring frames differ less (1.32 / 1.67) than frames two apart (1.42 / 1.92), `tools/steamdeck/frame_diff.py` | code kept, off |
| **`GetCurrentThreadId` cached** (Linux shim: a `gettid` system call at each memory use) — `tidab-*` | **17.37 / 17.36 vs 15.11 / 14.01 FPS (+19 %)**, p50 55 vs 65–70 ms; translation CPU 17.7–17.9 vs 21.7–23.2 ms a frame; GPU 955–1081 vs 720–870 MHz | **yes** |

30-minute session of the consolidated build (`~/Downloads/Orbital/logs/stable-soak30-*`, co-op path then co-op idle): exit 0 after
1,862 s; 230–600 s 16.35 FPS (p95 85 ms), 600–1200 s 16.58 (p95 81 ms), 1200–1850 s 17.03 (p95 79 ms); RSS 5.36 → at most 5.39 GB
(no growth); edge 71 °C average, 74 °C at most; APU 14.6 W.

What the profiles say (`perf-ref`, co-op, 25 s): **68 % of the CPU time is the recompiled game itself** (`Orbitals_code.so`:
Unreal's animation / skinning blends such as `F_EB177C0` 4.9 %, AdvSIMD helpers ~7 %), 24 % the runtime (translation, write-back
landing), 3.6 % RADV. The APU stays at 15 W with the GPU at ~800 MHz and 87–94 % busy: CPU work costs GPU clock, and the GPU frame
is near its limit as well. Halving neither side alone reaches 30 FPS.

Laptop (i7-14650HX + RTX 5070, Windows, 1080p, `ue_fps=60`, `fps_limit=0`, same path, 2 runs each): reference 44.95 FPS
(p99 33.8 ms), `wb_gpu` 45.85, `wb_gpu` + unbind kept 46.35 (p99 29.2 ms). The translation thread (~20 ms of a 22.8 ms frame) is
the PC's limit; the parallel recording for PC is on its own branch (`PC_PARALLEL_REPLAY.md`).

### 4.8 GPU clock pinned to 1100 MHz (new)

The Deck's APU shares one 15 W budget between the CPU and the GPU. Left on the driver's automatic policy, the GPU clock swings
(≈ 900–980 MHz measured in co-op) and the frame time is uneven. Pinning the GPU clock is a trade: too high starves the CPU
(the translation thread, which gates the frame), too low starves the GPU. Measured on the scripted co-op path, window 230–320 s,
through `tools/steamdeck/gpu-clock.sh` (runs on the Deck in `~/Downloads/Orbital/runs`):

| GPU clock | FPS | p95 (ms) | p99 (ms) | note |
|---|---|---|---|---|
| automatic (baseline) | 17.35 (17.23 / 17.47) | ~74 | ~85 | driver swings 900–980 MHz |
| fixed 800 MHz | 15.21 | 68 | 90 | GPU-starved (single run) |
| fixed 1000 MHz | 17.67 | 63 | 79 | single run |
| **fixed 1100 MHz** | **17.98 (17.89 / 18.07)** | **66** | **77** | **+3.6 % vs auto, tighter tail; kept** |
| fixed 1200 MHz | 17.83 (17.92 / 17.74) | 68 | 76 | ~ tied with 1100, no gain |
| fixed 1400 MHz | 16.96 | 71 | 82 | CPU starts to starve (single run) |
| fixed 1600 MHz / "high" | 15.9 / 15.8 | 88 | 101 | CPU-starved: the clock is stolen from translation |

1100 MHz is the sweet spot: the best average and the tightest frame-time tail, still inside the 15 W budget (14.6–15.6 W
measured, edge ≤ 72 °C). It is a small, real gain, additive to the rest; it does **not** approach 30 FPS on its own.

`orbitals-deck.sh` sets it on launch and restores the console's setting on exit. It uses SteamOS' own interface
(`steamos-polkit-helpers/steamos-priv-write`, the same path the quick-access menu's manual GPU clock uses), only within the
firmware's `OD_RANGE` (200–1600 MHz): **no overclock, no undervolt, the 15 W APU limit and the thermal protections are the
firmware's and are left untouched.** The restore runs on a normal quit and on `SIGTERM` / `SIGINT` (Steam's "Stop", the terminal),
through a single `EXIT` handler that also stops the game — tested on the Deck for all three (the clock returns to the automatic
policy and the saved-state file is removed each time). **Limitation:** a hard kill (`SIGKILL`) or a power loss cannot run the
handler and would leave the clock pinned; the launcher clears that at the start of the next run (it restores any leftover
saved-state before setting its own — also tested). `ORBITALS_GPU_CLOCK=auto` opts out and leaves the driver policy alone;
`ORBITALS_GPU_CLOCK=<MHz>` picks another value.

### 4.9 Deep co-op CPU profile (2026-11-21) and why 30 FPS is out of reach on CPU micro-ops

`perf record -e cpu-clock:u` over the co-op combat (180–240 s) of `base-simdh` (SIMD + merged hints), 17.71 FPS. Raw data:
`build/profsimdh2-coop-profile.txt`. By shared object:

| DSO | share | what it is |
|---|---|---|
| `Orbitals_code.so` | **69.2 %** | the recompiled game |
| `Orbitals` (runtime) | 19.9 % | NVN→Vulkan replay + dirty-page tracking |
| `libc.so.6` | 6.5 % | mostly `memmove`/`memcpy` |
| `libvulkan_radeon.so` (RADV) | 3.5 % | the driver |

Hottest symbols (self %): `F_EB177C0` 4.24 (Unreal animation/skinning blend) · `prep_write` 4.21 (runtime, dirty-page
release) · `memcpy` 3.81 + `bcmp` 1.93 (runtime, replay data movement) · `vkm_use_` 1.83 + `write_set_` 1.08 (descriptor
binding resolution) · then a spread of generated functions (`F_EA0C160` 1.14, `F_12636FC0` 0.91, `F_EA0D9A0` 0.83, …) and the
AdvSIMD per-lane helpers `fp_fma64` 0.86, `swr_simd` 0.80, `simd_3same` 0.67, `rsqrte_bits` 0.52, `fop2_` 0.48,
`simd_2misc` 0.43, `swr_frecpe_32` 0.41.

What this says, and the limits found:

- **The cost is spread, not concentrated.** The largest single item is 4.2 %; there is no new `GetCurrentThreadId`-class item
  (one cheap systemic fix worth double digits). 17.4 → 30 FPS needs the frame roughly 70 % faster; no micro-op approaches that.
- **Generated game code is 69 %** — dominated by Unreal's animation/skinning (`F_EB177C0` and the `F_EA0…`/`F_EB…` cluster).
  It is already `-O2`; the only lever on it is **PGO** (profile-guided rebuild) or targeted inlining. PGO is safe (same results)
  but is a multi-hour instrumented rebuild + collection + rebuild of the 390 MB module with an uncertain payoff on
  machine-generated C; it is the one real remaining lever on the dominant cost and is logged here as the next dedicated effort,
  not run in this pass.
- **The AdvSIMD helpers that remain (~4.4 %) are mostly irreducible.** `fp_fma64`/`fop2_`/`rsqrte_bits`/`swr_frecpe_32` are the
  actual per-lane float math *called by the already-inlined templates* — inlining the form does not remove them. Only the
  `swr_simd`/`simd_3same`/`simd_2misc` fallback (~1.9 %) could be inlined away, spread across many uncommon forms (thin, per-form
  regression risk). One safe idea left: compile `cpu_helpers.c` with `-mfma`/`-mavx2` so `fp_fma64` uses the Deck's hardware FMA3
  instead of a libm call (identical results, so the differential test still holds) — a module rebuild, bounded ~1–2 % expected.
- **`prep_write` (4.2 %) cannot be shortened safely.** It must scan every live range per guest write; the ranges are page-rounded
  per NVN pool and *adjacent pools can share a boundary page* (`nvn_dirty.c`), so a "last range hit" early-out would miss the
  neighbour and corrupt dirty tracking. Left as is.
- **`memcpy`/`bcmp` (~6 %)** is the replay moving each frame's buffers into Vulkan staging; `wb_gpu` already cut the write-back
  half. The rest is inherent data movement.
- **The GPU is near its limit too** (80–94 % busy at ~0.9–1.1 GHz inside 15 W), so even a large CPU cut would then hit the GPU
  wall. The 15 W APU budget is shared and is the firmware's; staying inside it (a project rule) caps both sides.

**Honest conclusion:** on native rendering, inside 15 W, stable 30 FPS co-op is not reachable by CPU micro-optimisation. The
measured, kept gains (thread-id cache +19 %, `wb_gpu` +4.9 %, SIMD inlining +1.5 %, GPU clock +3.6 %) stack to ~17.4–18 FPS,
well short of 30. Reaching 30 would need either PGO to land a large, currently-unproven cut on the generated code, or a rendering
reduction (resolution/effects) — which the brief rules out.

## 5. The `steam_deck_720p30` profile

`tools/steamdeck/profiles/steam_deck_720p30/profile.ini`, written into `Orbitals.ini` by `tools/steamdeck/install-profile.sh`:
handheld mode, fullscreen, `ue_fps=30` (FIFO, 30 FPS cadence), the Deck's controls as player 1 and a second controller as player 2,
`game_dynamic_resolution=0`. Presentation: Vulkan FIFO; FSR 1 EASU is only used when the window is larger than the picture,
which never happens on the Deck (1080p shown at 720p); `NXRT_VK_UPSCALE=fsr1|standard` stays available for an external display.

## 6. Status against the goals

| Goal | Status on the Deck |
|---|---|
| Runs natively, without streaming | Yes: menus, movies, co-op; built-in controls, audio, saves |
| 720p | Shown at 1280×720 on the panel; the game renders 1600×900 3D + 1080p HUD and its resolution cannot be lowered from config (section 2) |
| 30 FPS in menus | Yes, locked: 29.8 FPS, p95 33.3 ms, 8 W APU |
| 30 FPS in cutscenes | Not reached: 21.4–21.7 FPS before, 25.9 in the v0.1 RC (`rc1-path`, 200–290 s; 24 FPS movie, so the cadence is the movie's own plus loading); CPU bound (4.2 cores) |
| 30 FPS in co-op | **Not reached: 11.6 → 14.6 → 17.4 → 17.1 FPS in the v0.1 RC** (section 4.11). Power-bound APU (15 W, GPU ~800 MHz, 87–94 % busy) and 68 % of the CPU in the recompiled game itself |
| No change to simulation, audio or movie speed | None of the changes touch timing |

## 7. Next steps, by expected gain

What 30 FPS in co-op needs on the Deck, from the measurements above: the GPU frame (55 ms at ~800 MHz) and the NVN translation
thread (0.74 core at 14.4 FPS, i.e. **~51 ms of CPU per frame**: 4 400 draws, 430 passes, 6 500 descriptor sets written, RADV itself
18 % of that thread) both have to come under 33 ms. Lower resolution does not get there (section 2); per-draw and per-pass costs do.

Measured since (section 4.7): push descriptors, the hot-function layout, znver2 and merged light passes bring nothing measurable on
the Deck; the GPU write-back comparison brings +4.9 % and is on. What is left, by expected gain:

1. **The recompiled game's own CPU time (68 %)**: Hookshot / mkw-recomp's next step after the hot layout is PGO on the hot functions
   (an instrumented build, a profile from the co-op path, `-fprofile-instr-use`), and inlining hot callees (the layout alone did not
   help here). Also the AdvSIMD helpers still called out of line (`swr_simd`, `simd_2misc`, `simd_3same`, ~7 % of the CPU).
2. **Power**: the APU is at 15 W with the CPU taking most of it. A manual GPU clock in the Deck's quick access menu (game mode) moves
   power to the GPU; to be measured by the owner in game mode (needs the Deck's UI).
3. **GPU per-pass cost**: 235 light passes merged into ~110 changed nothing on RADV; the pass-begin barrier (9 % when removed, wrong
   pictures possible) would need a dependency-exact barrier instead of the full one.
4. More AdvSIMD forms in the movie decoder (cutscenes at 21–23 FPS).

## 8. Candidate build

**Current (2026-11-20 evening): `~/Downloads/Orbital/stable` on the Deck.** Runtime of `claude-steamdeck` (GPU write-back
comparison on in the launcher, `gettid` cached), the module below (hard link, not a copy), the profile in `Orbitals.ini`,
`orbitals-deck.sh`, a copy of the shader and pipeline caches, an empty save of its own; `Orbitals_data/exefs` and `romfs` link to
`~/Downloads/Orbitals-dev/Orbitals_data` (the game data is not copied). `SHA256SUMS` and `BUILD.txt` beside it. Checked there:
the scripted co-op path at 17.42 FPS (p95 75.9 ms, `~/Downloads/Orbital/logs/stable-check-*`), the launcher on its own (exit 0,
write-back comparison on), and a 30-minute session (`stable-soak30-*`, section 4.7). The morning's candidate below stays as it was.

Earlier:

`build/steamdeck-candidate/orbitals-steamdeck-720p30-03d9567.tar` (537 MB, `SHA256SUMS` beside it; not in git): the folder `Orbital/`
with the runtime and module of this branch (module stripped of debug info), the profile already written into `Orbitals.ini`,
`orbitals-deck.sh`, the shader cache and the Deck's RADV pipeline cache, an empty save. **No game data**: `Orbitals_data/exefs` and
`Orbitals_data/romfs` are relative links (`../../Orbitals_data/...`) to be replaced by the owner's own `exefs/` and `romfs/`.
The same build is unpacked on the Deck at `~/Downloads/Orbitals-dev/candidate` and was run there through `orbitals-deck.sh`
(desktop mode: Steam Deck Controller detected, screen kept on, 28–30 FPS in the menus) and through the scripted co-op path
(table above). With an empty save the game starts with its first-launch language screen, as on a new console.

## 9. Reproduce

See `tools/steamdeck/README.md`.

### 4.10 Lazy write-back shadows on the Deck (2026-11-21)

The laptop's +10 % change (commit 59a8249, `NXRT_VK_SHADOW_LAZY`), same module (`base-simdh`), runtime of 59a8249 in
`base-lazy`, co-op 230-320 s, `NXRT_VK_WB_GPU=1`, off/on alternated twice:

| | FPS | p95 ms | APU W | GPU MHz | game CPU % | GPU busy % |
|---|---:|---:|---:|---:|---:|---:|
| off (2 runs) | 17.3 / 17.3 | 76.2 / 75.9 | 14.6 | 968 / 980 | 431 | 92 |
| on (2 runs) | 17.4 / 17.4 | 75.4 / 75.5 | 14.5-14.9 | 1029 / 1005 | 419 / 420 | 92 / 90 |

The CPU saving is real (-11 % of a core) and goes to the GPU clock (+40 MHz inside the same 15 W), but the frame rate does
not move: **in co-op the Deck is GPU-bound** (90-92 % busy). Kept (no loss, less power on the CPU). The Deck's next lever is
GPU time per frame (per-pass timing `NXRT_VK_GPUTIME_AT_S`, the write-back comparison dispatches, the full barriers between
passes), not more CPU micro-work.

### 4.11 v0.1.0 release candidate on the Deck (2026-11-21)

Runtime of `release/v0.1` (Intel fixes inactive on RADV: the log says `fragment shader quad shuffles through quad operations: off`
and `formatless storage read/write 1/1: all present`), same module and data as `base-lazy` (the previous runtime), co-op
230–320 s, `ue_fps=30`, `NXRT_VK_WB_GPU=1`, alternated (`tools/q24.txt`; raw files in `build/deck-runs/<run>`):

| Run | FPS | p95 ms | p99 ms | APU W | GPU MHz | game CPU % | GPU busy % | RSS MB |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| RC `rc1-coop-1` | 17.1 | 77.7 | 89.3 | 14.4 | 992 | 416 | 79 | 5369 |
| reference `lazy-coop-1` | 17.4 | 75.2 | 85.0 | 15.1 | 1023 | 420 | 93 | 5335 |
| RC `rc1-coop-2` | 17.1 | 77.4 | 87.0 | 14.5 | 1042 | 417 | 92 | 5354 |
| reference `lazy-coop-2` | 17.2 | 76.6 | 86.0 | 14.7 | 990 | 416 | 85 | 5342 |

The RC is at the reference's level (17.1 vs 17.3 on average, within the spread of earlier sessions; the code paths that changed are
off on RADV). Whole path with captures (`rc1-path`): menus 29.8 FPS (20–120 s), intro movie 25.9 FPS (200–290 s), every scene drawn
as on the laptop (GRAPHICS_ACCURACY.md). **31-minute session** (`rc1-long`, 1862 s, exit 0): co-op 17.7 / 17.5 / 17.6 FPS at
300–400 / 900–1000 / 1750–1850 s, resident memory 5367 → 5396 MB over 25 minutes (flat), no `fatal` / `svcBreak` line.
### 4.8 One co-op frame by fragment shader (2026-11-24, v0.1.5, `NXRT_VK_GPUTIME_AT_S=290`)

One GPU-timed frame, original 3D resolution (2 × 1600×900 RGBA16F scene targets in co-op), GPU at about 1,115 MHz: 48.4 ms from the first
mark to the last; passes 43.2 ms (430), dispatches 4.7 ms (132). The 380 passes of one or two draws take 25.8 ms; grouped by fragment shader:

| Fragment shader | Passes | GPU ms | Each | What |
|---|---:|---:|---:|---|
| `7d5d50be3bfa00f7` | 235 | 8.37 | 36 µs | Unreal's deferred lights (one pass per light, ~117 lights per view); merging them changed nothing (4.7) |
| `571293a528a61b28` | 2 | 2.34 | 1.17 ms | full-screen pass, once per view |
| `dc3a3111b211a512` | 2 | 2.26 | 1.13 ms | full-screen pass, once per view |
| `b7c9684d203def9e` | 2 | 1.73 | 0.87 ms | full-screen pass, once per view |
| `e858d353fe93a6f5` | 6 | 1.67 | 0.28 ms | |
| `62995aed8faf645e` | 10 | 1.65 | 0.17 ms | 8 at 1600×900, 2 at the 1080p output |
| `6075febc89dd4775` | 20 | 1.35 | 68 µs | 1600×900 BGRA8 |
| `f5fb2ea217468f2e` | 1 | 1.13 | 1.13 ms | the final 1920×1080 composite |

The per-pass work scales with the scene resolution (the Performance preset's 720p 3D: 19.0 → 21.4 FPS); the six heaviest full-screen
passes are ~9 ms of the frame. Next measurements on the Deck: identify those six shaders (their SPIR-V in the shader cache) and the pass
barrier's share per class (the 9 % of `NXRT_VK_PASS_BARRIER=0`, 4.5), then a barrier limited to what the next pass reads.

### 4.9 Pass barrier and SPIR-V optimisation (2026-11-25, v0.1.5, Performance preset 720p 3D, `ue_fps=30`, flight recorder off)

| Change | Result | Kept |
|---|---|---|
| No barrier at pass begin (`NXRT_VK_PASS_BARRIER=0`, measurement only: wrong pictures possible) — `pb0-*` vs `pb1-*` | 22.4 / 21.8 vs 21.7 / 21.7 FPS: at most +2 % (the 9 % of 4.5 was in 60 mode at the original resolution) | no |
| The nine heaviest post shaders through `spirv-opt -O` (validated; the translated modules are 2.7–3× smaller: register emulation leaves ~4,500 local variables in the light shader) — `gtbase-1` vs `gtopt-1`, one GPU-timed frame each | per shader the same GPU time (lights 5.74 vs 5.49 ms for 235 passes, 1.27 / 1.27, 1.21 / 1.20, 0.92 / 0.89 ms…): RADV's compiler already does it | no |

The per-pass GPU cost on the Deck is the game's own shading work at the chosen resolution; the cheap levers (barriers, SPIR-V size)
are measured out. What is left: fewer pixels (the Performance preset), or less work per pixel in the heaviest passes, which changes the
picture and is not done.
