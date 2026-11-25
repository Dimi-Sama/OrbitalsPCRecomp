# Known issues — v0.1.5

Measurements and observed issues below come from earlier builds through RC4. Graphics observations marked unverified still need a console comparison.

## Performance

- **60 FPS mode is experimental** (`ue_fps=60`). On the RTX 5070 Laptop + i7-14650HX, co-op at 1080p runs at about **54 FPS** (p95 22 ms,
  v0.1.5-preview.1), not a stable 60. A frame is the Vulkan replay of the game's main command list (about 11 ms on one thread) followed by
  the GPU work the game then waits for (about 6.5 ms). Menus and single views reach 60. Cutscene and simulation speed are correct at 60
  (the game's clock is never changed to gain frames).
- **Steam Deck co-op runs at about 19 FPS** with High and **21–22 FPS** with the Performance preset (720p 3D) (menus 30, intro video ≈ 26
  for a 24 FPS movie). The Deck is GPU-bound in co-op (90–96 % busy inside the 15 W budget); about 380 full-screen post-processing passes
  take half of its frame. 720p30 co-op on the Deck is a goal, not reached.
- **Intel integrated GPUs** render correctly since v0.1 (see Graphics) but run co-op at about 4 FPS (UHD of the i7-14650HX). Not a
  supported target.
- **The opening cinematic can fall behind under heavy CPU load.** The first three seconds of black frames are part of the movie.
  See the [CPU measurements](PERFORMANCE_ROADMAP.md#cpu-limited-windows-follow-up-2026-11-23).
- **First session pauses (Windows):** shaders are translated the first time the game uses them. The renderer waits for each batch
  (`NXRT_SHADER_WAIT_MS`, 15000 by default). A shader that misses the deadline does not block later command lists again. Windows also
  detects when the translator has exited and logs its exit status. On a fresh install of the original release candidate (RTX 5070
  Laptop), title screen to the colony corridor in co-op: **392 s with 134 s of pauses** (longest 4.9 s, mostly during loading screens),
  0 draws skipped, the corridor lit as in later sessions; the same path with the cache filled: 202 s, no pause. Before this, a skipped
  draw could leave work the game does once wrong for the whole session (a much darker colony corridor until the next start). A slower
  CPU translates more slowly. The optional offline tool can prepare existing captures. Shaders outside the supplied capture set still
  translate on demand. [Offline shader prewarm](docs/SHADER_PREWARM.md)
- **Launcher and first launch from a junction:** the translator resolves the actual tools directory before loading the runtime headers.
  Previously it could exit at startup and the renderer would wait for the missing shaders in successive command lists. When rebuilding
  a stale cache, the live translator compiles the shaders requested by the current session. Cache readers allow replacement while open,
  and the translator retries temporary Windows sharing errors during publication.

## Graphics

- Fixed in v0.1: white triangle edges on dark surfaces on Intel GPUs (fragment-shader subgroup shuffles left helper invocations out on
  Intel's driver; now read through quad operations on Intel), and texel buffers read without a declared format on GPUs that cannot do
  that (typed shader variants). See [GRAPHICS_ACCURACY.md](GRAPHICS_ACCURACY.md).
- **Intel GPUs: character drop shadows** are drawn as light, translucent shapes instead of dark ones (demonstrated on the UHD of the
  i7-14650HX after the edge fix; correct on NVIDIA and on the Steam Deck). Cause not found yet.
- **Pause menu title in Japanese** (e.g. "リアクターカセットを手に入れよう！" above French text): the runtime passes the right language
  (`language=2` changes nothing); the string is likely untranslated in the game's data. Unverified on the console.
- **Camera close to walls** can move in and fold onto the character. Plausibly Unreal's own camera boom; unverified on the console.
- The log reports `a buffer texture in a slot a shader samples as an image: it reads 0` once per session: a binding this renderer
  approximates with an empty image. No visible effect found on the tested path.
- The log reports `shader e2cd2d78c70fdd98 writes float colour 0 into an integer target` (undefined values in Vulkan; no visible effect
  found) and a GPU copy into a storage-backed BC3 texture that cannot be read back (no visible effect found).
- Only the scenes listed in GRAPHICS_ACCURACY.md were compared. Later chapters of the game were not tested at all.

## Video, audio, timing

- The opening uses separate Wwise audio. The `.bk2` contains a three-second black lead-in and no embedded audio.
  Exact dialogue alignment against a console recording still needs a test.

## Platforms and setup

- **Linux shader translation** needs Python 3, the .NET 10 runtime and SPIRV-Tools. Steam Deck setups can use a shader cache from an earlier
  session made with the same game build. See [BUILDING.md](BUILDING.md#linux--steam-deck).
- Linux needs page 0 for some NULL reads of the game: the runtime warns when `vm.mmap_min_addr` is not 0. SteamOS's default works on
  the tested path (no change needed); other distributions may need `sudo sysctl vm.mmap_min_addr=0`.
- The Linux runtime is cross-built. Native Linux installation, launch and input require testing on the target system.
- Wayland needs Xwayland (the Linux backend is X11).
- Only one game folder layout is supported by the launch scripts: `<dir>/Orbitals` with `<dir>/toolchain` beside it (what
  `setup-windows.ps1` makes).

## Graphics settings

- Custom internal 3D resolutions currently go from 960×540 to 1920×1080. The game composites at 1080p, so a 1440p or 4K output
  scales that composite. Co-op on the RTX 5070 Laptop is often CPU-bound, which can limit the FPS gain from lowering the scene resolution.
- No shadow / effects / post-processing quality setting: Unreal's scalability groups reach the game but replace its Switch 2 tuning
  (darker picture) and were slower on the Intel GPU; individual console variables (shadows, ambient occlusion, post-processing,
  reflections, fog) reach it without that change but made no measurable difference (Intel UHD 4.0 vs 4.0 FPS, GRAPHICS_SETTINGS.md).
  Launcher settings apply at the next launch. The Windows F1 menu can change the internal 3D resolution during play on the supported build.
- AMD GPUs on Windows are a validation priority. Earlier runs covered NVIDIA and Intel UHD on Windows
  and AMD RADV on Steam Deck.

## Controller input

- Rumble uses the PC controller's motor intensities. It approximates the Switch HD Rumble effects.
- PC controllers use Switch button positions in the game. The **Controls** tab lists available mappings.

## Not in this release

- **Online and LAN play.** The game's online mode needs Nintendo's servers, which this project does not and will not contact or
  emulate. Experimental local-network work exists on separate development branches and is not part of v0.1.
- DLSS / XeSS / frame generation, 120 FPS, an in-game menu for all launcher settings.
- A Linux AppImage: v0.1 ships a `tar.gz` (the launcher runs on SteamOS's own Python 3.13 + Tk 8.6). An AppImage can only carry the
  runtime, launcher and tools; the recompiled game and its data always stay in a folder of the player's.
