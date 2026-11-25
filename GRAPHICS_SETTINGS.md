# Graphics settings — what really changes the rendering (v0.1)

The launcher's **Graphics** tab only offers settings measured to change what the game renders. This page lists what was tried,
how, and what each setting does to the frame rate, the GPU time and the picture. "Original" always means the game's own Switch 2
settings, unchanged.

## How a setting reaches the game

- **Internal 3D resolution**. TV renders at 1920×1080 (two 960×1080 views in co-op). Handheld renders at 1600×900
  (two 800×900 views). The Custom preset also offers 960×540, 1280×720 and 1600×900 with the TV profile. It writes
  Unreal's `r.SecondaryScreenPercentage.GameViewport` to the session's `Engine.ini`. The HUD and final composite stay at 1920×1080.
  [Unreal Engine documentation](https://dev.epicgames.com/documentation/en-us/unreal-engine/screen-percentage-with-temporal-upscale-in-unreal-engine)
- **Unreal scalability groups** (`sg.*`): the game reads Unreal's user config layer `Orbitals/Saved/Config/Switch2/GameUserSettings.ini`
  from its RomFS; the runtime serves it from `<game>/Orbitals_data/romfs_overlay` (the launcher writes it in the session folder only).
  A scalability group is a *game setting*, which outranks the Switch 2 device profile's console variables.
- **Window output size** sets the window's client area in physical pixels (540p to 4K in the preset list). Borderless uses the monitor's
  desktop resolution. The runtime fits the 1080p composite to the output and can use bilinear, sharp or FSR 1 EASU when enlarging it.

## What does not work (and is not offered)

| Tried | Result |
|---|---|
| `r.ScreenPercentage`, `r.DynamicRes.Min/MaxScreenPercentage` in `Engine.ini` `[SystemSettings]` / `[ConsoleVariables]` / device profile | ignored: the Switch 2 device profile sets them at a higher priority, and the game sets its 3D size from code (laptop and Deck: views stay 960×1080 / 800×900) |
| `sg.ResolutionQuality=50` (`GameUserSettings.ini`) | ignored: views stay 960×1080 (`sg-res50`) |
| `-ExecCmds`, `-dpcvars` on the command line | ignored by the shipping build |
| Native 1440p and 4K | The higher sizes are available for output. The game still composites at 1920×1080. |
| 120 FPS / unlimited | not offered: the 60 mode already presents every vblank; co-op stays below 60 on every PC tested, so a higher mode would only add risk |

## Unreal scalability groups (RTX 5070 Laptop, co-op, `ue_fps=60`, 200–245 s)

The laptop is CPU-bound in co-op (the NVN translation thread), so its frame rate barely moves; the GPU time of one frame and the
number of compute dispatches show what the GPU is asked to do.

| Run | FPS | GPU frame (one sample) | Dispatches | 3D view | Picture |
|---|---:|---:|---:|---|---|
| Original (`gs-base`) | 51.7 | 20.3 ms | 128 | 960×1080 | reference |
| every `sg.*` = 0 (`gs-low`) | 54.6 | 16.1 ms | 34 | 960×1080 | much darker, different lighting |
| every `sg.*` = 3 (`gs-epic`) | 53.7 | 16.1 ms | 34 | 960×1080 | same as `sg=0`: any explicit level replaces the device profile's tuned values |
| one group at 0 at a time (11 runs, `sg-*`) | 50.0–52.1 | 17–22 ms | 123–161 | 960×1080 | no group alone reproduces the change |

So the scalability groups are real but **not** a fidelity-preserving quality ladder: the console's look comes from the device profile,
and setting the groups (to any level) swaps it for Unreal's generic levels. None is offered in v0.1: the measurements below show no
gain worth that change of look.

## Individual console variables (v0.1-rc1)

The game's device profiles are `Switch2_Console_Deferred` (TV) and `Switch2_Handheld_Deferred` (handheld), and it reads the user layer's
`Saved/Config/Switch2/DeviceProfiles.ini` and `Scalability.ini` too. Measured with the same scripted co-op path:

| Tried (user config layer) | Result |
|---|---|
| `DeviceProfiles.ini`: `+CVars=` in both profiles (and `[Switch2 DeviceProfile]`): `r.ShadowQuality=0`; `r.MipMapLODBias=6` + `r.ViewDistanceScale=0.05` | **ignored**: the file is read, the picture and the passes are identical (`dp-probe`, `dp-probe2`) |
| `Scalability.ini`: the same variables in every level of the groups' sections | **applied** without changing the console look: `r.MipMapLODBias=6` visibly blurs the textures (`dp-probe3`) |
| `Scalability.ini`, "everything low": shadows (512, one cascade, 0.5 distance), ambient occlusion off, bloom, depth of field, motion blur, lens flares, chromatic aberration, SSR, refraction, volumetric fog and subsurface off | picture unchanged (mean difference 0.4 / 255), 432 vs 428 passes; RTX 5070 Laptop 51.6 vs 51.7 FPS; **Intel UHD 4.0 vs 4.0 FPS** (`i-alllow`) |
| `Scalability.ini`, `r.MipMapLODBias=1` (half-resolution textures) | **Intel UHD 4.1 vs 4.0 FPS**: no gain worth a blurrier picture (`i-lod1`) |

So the Unreal-side quality settings either are set by the device profile at a higher priority or cost nothing in this game's rendering:
the GPU time goes to the 428 passes the replay records (Intel UHD: 174 ms of a 246 ms frame in passes), not to Unreal's optional
effects. The current controls for performance are frame pacing and internal 3D resolution. Replay also contributes a per-pass cost
(PERFORMANCE_ROADMAP.md).

## On the GPU-bound machines

**Intel UHD (i7-14650HX iGPU)**, co-op, `ue_fps=30`, 230–320 s, the scripted path of the reference Intel run:

| Run | FPS | p95 | GPU frame (one sample) | 3D view |
|---|---:|---:|---:|---|
| Original, TV (`igpu-quad30-20261121-151722`) | 4.0 | 443 ms | 252 ms | 960×1080 |
| **Handheld 3D resolution** (`i-portable`) | **5.2** | 321 ms | 193 ms | 800×900 |
| every `sg.*` = 0 (`i-sglow`) | 3.7 | 488 ms | 266 ms | 960×1080 |
| handheld + the game's dynamic resolution (`i-portable-drs`) | 5.2 | 320 ms | 188 ms | 800×900 (it never lowered it) |
| handheld + every `sg.*` = 0 (`i-portable-sglow`) | 4.8 | 372 ms | 206 ms | 800×900 |

**Steam Deck OLED (RADV)**, co-op, already at the handheld 3D resolution, 230–320 s:

| Run | FPS | p95 | GPU frame (one sample) |
|---|---:|---:|---:|
| Original (`orig-1`, `orig-2`) | 17.3 / 17.2 | 75.6 / 75.9 ms | 71.9 ms |
| every `sg.*` = 0 (`sglow-1`, `sglow-2`) | 17.0 / 17.2 | 77.3 / 76.9 ms | 65.5 ms |

## What v0.1 offers

| Preset | 3D resolution | Measured | Picture |
|---|---|---|---|
| **High** (default on PC) | TV: 1920×1080, 2 × 960×1080 in co-op | reference | the game's own |
| **Low** | handheld: 1600×900, 2 × 800×900 in co-op | +30 % co-op FPS on an Intel UHD (still far from playable there: 5 FPS); not measured on the RTX 5070 Laptop, which is CPU-bound in co-op | the game's own handheld rendering, HUD and final picture still 1080p |
| **Performance** (v0.1.5) | TV profile at 1280×720, 2 × 640×720 in co-op | Steam Deck co-op (230–320 s of the recorded route, 15 W): 19.0 / 18.7 → 21.4 / 21.3 FPS, +13 %; 960×540 gave 22.3 (one run), so not offered as a preset. The Deck's GPU clock drops at the lower load (1,130 → 815 MHz), which keeps the gain below the pixel ratio | the same effects as High, softer picture; HUD and final picture at the output size |
| **Custom** | TV or handheld, or TV at 960×540 / 1280×720 / 1600×900 | scale verified in Vulkan viewport and attachment logs | Unreal upscales the scene and composites the HUD at 1080p |

The output size list starts with the primary monitor's physical resolution and offers presets that fit it. Frame rate, output size,
display mode, upscaling filter and VSync are separate profile settings. Changes apply at the next launch.
The experimental **30 (async replay)** option keeps the 30 FPS target and schedules Vulkan replay on a separate thread.
It reduced the cinematic slowdown during the Windows test with a constrained CPU. [CPU and cinematic measurements](PERFORMANCE_ROADMAP.md#cpu-limited-windows-follow-up-2026-11-23)

On Windows, press **F1** during the game and use **3D resolution (this session)** to change the scene resolution immediately.
Choose **Launch setting** to restore the value the game started with. The HUD stays at 1080p and the window keeps its size.
The control is available for the Orbitals executable build validated by this release.

On Windows, the launcher was checked at 540p, 720p and 900p internally and with 1440p and 4K window output. The 720p co-op check
rendered both views in the colony corridor, in 636×720 and 640×720 viewports inside a shared 1284×720 attachment. Both HUDs
were visible in the 1920×1080 composite. A second co-op run changed from 1080p to 720p, 540p and 900p live, then restored 1080p.
Vulkan recorded both views at each setting and reported zero draws skipped for missing shaders in that sequence.

On Windows, `Play-Orbitals.ps1 -InternalResolution` also accepts `540p`, `720p`, `900p`, `1080p` and `Portable`.
Use `Portable` to select the handheld profile previously selected by `720p`.
