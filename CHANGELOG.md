# Changelog — Liftoff (Orbitals PC Recomp)

The upstream recompiler's own history is in [CHANGELOG.txt](CHANGELOG.txt).

## v0.1.5 — first public release

The first release in the public repository. It gathers the private developer previews v0.1.5-preview.1 to .3 on top of v0.1.0;
details in [docs/RELEASE_NOTES_v0.1.5.md](docs/RELEASE_NOTES_v0.1.5.md).

- **Launcher**: a new title screen, a demoscene screen for the recompile and another for the shader preparation, the installation
  bar following the recompile, outdated-game detection with a recompile that keeps the saves, update checks and downloads (checked
  against the release's SHA-256), Linux dependency messages per distribution.
- **Linux AppImage** (`tools/release/make_appimage.sh`).
- **Prepare shaders**: the 23,134 shaders translated before the first session; no console windows on Windows.
- **Rendering**: fires, smoke, exhaust, thrusters and the rainbow curtain drawn; the flashes after the opening film fixed; on AMD,
  Intel and the Steam Deck, 32-lane subgroups and shared memory kept in order (the space scene's sprites, the cutscene's curtain).
- **Linux**: memory checks without `/proc/self/maps` (the stutter, and movies behind their sound).
- **Performance**: the Performance preset (720p 3D), long submissions handed to the GPU every 4 ms, the flight recorder off for
  players.

The entries below are the private history before v0.1.5.

## v0.1.0 — Private Developer Preview

- Includes the RC4 runtime, launcher, installer and AOT function discovery.
- Adds optional offline shader prewarm for existing NVN2 captures. It verifies capture keys, validates SPIR-V, reuses verified cache entries and reports progress as JSON. [Offline shader prewarm](docs/SHADER_PREWARM.md)
- 30 FPS is recommended. 60 FPS is experimental. First-session shader pauses, graphics differences and Linux or Steam Deck limitations remain possible. Network play is unavailable. [Known issues](KNOWN_ISSUES.md)
- The planned GitHub distribution is a prerelease in the private repository. The archives contain the runtime, launcher and tools. Installation requires the player's own game data. [Building and installation](BUILDING.md)

## v0.1.0-rc4 — Private Release Candidate (2026-11-23)

- The recompiler discovers more native entry points from packed relative relocations in the game executable, before the first launch.
- A transient Windows file lock can be retried by the live shader translator. The retry keeps the original shader and cache format.
- Vulkan preserves copies into storage-backed 3D textures across later uploads and groups the synchronization around GPU memory readbacks.
- The runtime skips the interpreter bookkeeping lock for previously recorded entry points and logs the native module's entry count.
- Existing Windows installations can rebuild the game module with `-RebuildCode`.


## v0.1.0-rc3 — Private Release Candidate (2026-11-23)

- The launcher's **Controls** tab lists gamepads, saves the keyboard and mouse player, and configures the mouse camera and sensitivity per profile.
- Both players can receive rumble on compatible controllers. The runtime converts Switch HD Rumble commands to PC motor intensities.
- Keyboard and mouse take over Player 1 when its controller is absent. Assign them to Player 2 for co-op with one controller.
- Mouse camera and trigger clicks work through the desktop backends. F2 toggles capture during play.


## v0.1.0-rc2 — Private Release Candidate (2026-11-23)

- Linux x86-64 can install from ExeFS and RomFS in the launcher with a native GCC build and the runtime included in the archive.
- The launcher opens the signed-in GitHub release page for private previews and offers separate scene and output resolutions.
- Windows offers live 3D resolution in the F1 menu. The 30 FPS async replay mode is available in Graphics.
- CPU work is reduced in Vulkan descriptor binding and write-back bookkeeping, and in selected ARM vector instructions.
- Live shader translation prioritizes requests from the current session, publishes ready shaders sooner and handles Windows cache replacements.
- Windows audio output retains packet deadlines when a busy CPU delays a wakeup.


## v0.1.0-rc1 — Private Release Candidate (2026-11-22)

The candidate for v0.1.0, for a fresh-install test on other PCs. Everything below under v0.1.0, plus:

- First session validated on a fresh install with the stepped test (`tools/visual_suite/stepper.py`, each input sent when the game shows
  the screen it expects; its clock leaves out the shader waits): title to the colony corridor in co-op, 0 draws skipped, the corridor lit
  as in the next session (player 2's view: mean luma 53.9 vs 51.9), 134 s of shader pauses in 392 s; 202 s and no pause with the cache.
- Launcher in English (values saved by the earlier French interface still load), `Orbitals-Launcher.bat`, the monitor's native
  resolution first in the output sizes, the release / commit / Vulkan device in bug reports and on the home page.
- The runtime's log names the release and the commit it was built from (`switchrecomp.py release_id`, a `COMMIT` file in archives).
- Graphics settings: the user layer's `DeviceProfiles.ini` is ignored by the game; individual quality variables through `Scalability.ini`
  apply but changed nothing measurable (Intel UHD 4.0 vs 4.0 FPS): no new setting offered (GRAPHICS_SETTINGS.md).
- The French development logs and the first PC settings prototype leave the public tree; their findings are in
  docs/DEVELOPMENT_NOTES.md.

## Developer Preview baseline before RC1

These are the features and measurements that preceded the release candidates. [Known issues](KNOWN_ISSUES.md)

### What works

- Windows 10/11 x64 and Linux x64 / Steam Deck: boot, menus, intro video, character select, the opening chapter, two-player local co-op
  in split screen, controllers and keyboard, audio, Bink cutscenes, saves.
- The 30 FPS reference mode (the game's own pacing) and an **experimental** 60 FPS mode (`ue_fps=60`, real frames, game speed preserved).
- NVN2 → Vulkan renderer with shaders translated while the game runs, shader and pipeline caches per game folder.
- A reproducible build from your own copy of the game: `tools/release/setup-windows.ps1` (Windows) and the Linux / Steam Deck cross
  build (BUILDING.md), every build tool downloaded from its official source and checked against a pinned SHA-256.
- A desktop launcher (profiles, settings, bug reports) and a command-line bug report exporter that never includes saves or game files.
- Launcher **Install from my files** (Windows): the player's own `exefs/` + `romfs/` go through the setup (official build tools,
  pinned SHA-256, the game's code recompiled on the PC), with step progress and a log; the new installation is selected at the end.
- Launcher **Graphics** tab: presets High (the game's own rendering, 3D 1920×1080) and Low (the game's handheld 3D resolution,
  1600×900: +30 % co-op FPS on an Intel UHD), Custom; 30 FPS reference / 60 FPS experimental with its warning; output size kept apart
  from the 3D resolution; display mode, VSync; reset; saved per profile and applied per session. Unreal's scalability groups,
  `r.ScreenPercentage` and the game's dynamic resolution were measured and are not offered (GRAPHICS_SETTINGS.md).
- The SwitchRECOMP startup screen (required by NOTICE.txt) is now shown by the Vulkan renderer too; it was only drawn by the OpenGL
  one. The window title is the game's name (the credit stays on the startup screen and in the README).
- Clean-install test of the Windows archive (fresh folder, launcher path, the player's own files): it found and fixed a setup that could
  not start `Install.bat` from the launcher; the full install then took 36 minutes on the laptop (downloads 30 s, recompilation the rest).
- First session on a fresh install: before a command list is replayed, the shaders it binds that are not translated yet are sent to the
  translator in one batch and the renderer waits for them (`NXRT_SHADER_WAIT_MS`, 15 s cap, on when the live translator runs). Measured
  on a clean install: 350,318 draws skipped and a much darker colony corridor before; 0 skipped, 88 s of pauses in a 9-minute first session
  after. Later sessions are unchanged (cache).
- Linux: the game stops on SIGTERM again (Steam's Stop, the launcher, `orbitals-deck.sh`): SDL's signal handlers had turned it into a
  quit event nobody read. The launcher's first session reuses the game folder's shader cache (a Steam Deck cannot translate shaders).

### Graphics fixes included (since the first playable builds)

- Main menu: the illustrated planes and the logo were invisible (vertex fetch buffers taken for 2D images by a SPIR-V edit).
- High-five cutscene: Maki and Omura disappeared for 18 frames (same cause).
- Left half of the menu darkened, pink title screen (layered render targets: every layer is now rendered).
- Black views inside environments (walls not rendered: same vertex fetch defect).
- NVN2 buffer reads: bindless storage images and buffer textures bound (`img_ubo`, `tbuf_ubo`, `tex_ubo`).
- Translator SPIR-V edits: wrapped bindless fetches as texel buffers (`5b84511`), size queries of bound volume textures (`6925916`),
  vertex fetch buffers whose id equals a capability number (`0ac42cb`: the 59 corrected modules of the reference cache, about 45
  vertex shaders with Unreal's manual vertex fetch and 4 compute shaders, all passing `spirv-val`; `tools/nxshader/nxs_reedit.py`
  applies the current edits to an existing cache without retranslating).
- **New in v0.1 — Intel GPUs:** white triangle edges on dark surfaces. Fragment shaders compute derivatives with subgroup shuffles across
  the 2×2 quad; Intel's driver leaves helper invocations out of plain shuffles. In-quad shuffles now go through
  `OpGroupNonUniformQuadSwap` (helpers take part) on Intel; `NXRT_VK_QUAD_SHUFFLE=0|1` overrides. Same pictures on NVIDIA with the
  path forced on (GRAPHICS_ACCURACY.md).
- **New in v0.1 — devices without `shaderStorageImageReadWithoutFormat`:** compute shaders reading storage texel buffers declared
  without a format get a variant that declares the bound view's format when the device cannot read that format without one
  (`VK_FORMAT_FEATURE_2_STORAGE_READ_WITHOUT_FORMAT_BIT`); `NXRT_VK_TBUF_TYPED=0|1|2`. `tools/vk_format_probe.c` prints what a GPU
  supports.

### Performance (measured, see PERFORMANCE_ROADMAP.md)

- Lazy write-back shadows (`NXRT_VK_SHADOW_LAZY`, on): laptop co-op at 60 mode 46.6 → 51.7 FPS, translation thread 18.8 → 16.2 ms CPU a
  frame, no image change (check mode: 0 differences).
- GPU comparison of write-backs (`NXRT_VK_WB_GPU=1`, on in the launch scripts): +4.9 % co-op FPS on the Steam Deck, 534,027 ranges
  checked against the CPU comparison with 0 differences.
- Linux: `GetCurrentThreadId` cached per thread (a system call each time before): +19 % co-op FPS on the Steam Deck.
- NVN translation on its own thread, inline AdvSIMD floating point forms in the recompiled code, Steam Deck GPU clock policy with a
  validated restore on exit.

### Not included

Online and LAN play (postponed; experimental branches are kept apart), DLSS / XeSS / frame generation, 120 FPS.
