# Orbitals PC — performance roadmap (state of 2026-11-21)

Targets: Steam Deck OLED 720p **30 FPS** co-op (Linux, RADV, 15 W) · MSI Katana 15 (RTX 5070 Laptop) 1080p **60 FPS**
native co-op · later the 7800X3D / RTX 5080 at 4K120. None is reached yet.

## Where each machine stands (co-op, scripted path, same windows as the reports)

| Machine | FPS now | Gate | Report |
|---|---:|---|---|
| Laptop, `ue_fps=60`, 1080p | **51-52** (was 46.5-46.8) | the serial NVN→Vulkan translation thread, **16.2 ms CPU** a frame (was 18.8) | `LAPTOP_60FPS.md` §6 |
| Steam Deck, `ue_fps=30`, 720p | **17.4** | the **GPU** (90-92 % busy at ~1 GHz inside 15 W); CPU 420 % | `STEAM_DECK_PERFORMANCE.md` §4.10 |

## Method (kept for every change)

Profile before → written hypothesis → isolated change behind a switch → functional check (captures, `[RED]` lines, a check
mode where one exists) → identical A/B, alternated, ≥ 2 runs each → commit with the numbers. Tools:
`tools/claude_laptop/run-orbitals.ps1` (isolated runs, `-AllowConcurrent`), `profile=1` + `prof_symbolize.py` (the
translation thread on its own), `ab_stats.py` (FPS, p50/p95/p99, translation CPU over a window), `NXRT_VK_PHASES=1`
(replay phases), Deck: `deck-run.sh` / `deck-queue.sh` / `deck_report.py` (telemetry: power, clocks, busy).

## Windows follow-up (2026-11-22)

With a new launcher profile and an empty cache on the RTX 5070 Laptop, the first game image was accepted at 4.12 s. The first
1,100 frames had 16 shader waits totalling 9.91 s, with a longest wait of 4.55 s and no draws skipped for a missing shader. The
same launch with the cache filled had zero shader waits. Against a cache made by an older shader chain, the first 900 frames
took 43 s and spent about 4.4 s waiting for shaders. The live translator processes the current session's requests, so it avoids
recompiling the old dump directory before addressing the shaders the game needs.

On 96 local shader dumps, two serial and two parallel builds averaged 13.10 s and 11.55 s respectively. Every SPIR-V module
and reflection file matched the serial output byte for byte. All 96 SPIR-V modules passed `spirv-val --target-env vulkan1.3`.

Co-op benchmark on the RTX 5070 Laptop in experimental 60 FPS mode with a 1280×720 window and docked rendering. Two runs per
build used the same saved game, input path, shader cache and fixed cameras. Measurements cover 181–199 s of the run and about
4,360 draws and 53,400 memory uses per frame.

| Metric | Reference | Windows update |
|---|---:|---:|
| Full memory syncs per frame | 15,561 | 6,952 |
| NVN translation thread CPU per frame | 17.07 ms | 16.11 ms |
| Presents per second | 50.72 | 51.39 |
| p95 frame interval | 23.83 ms | 23.17 ms |
| p99 frame interval | 31.68 ms | 32.20 ms |

The visual suite flagged none of the four paired captures. Frame times still vary between runs, and the 60 FPS target remains open.

## Shader translation follow-up (2026-11-23)

An empty-cache translation of 334 local shader dumps on the RTX 5070 Laptop system took **18.40 s**, down from **35.58 s** with the
previous translator. Both runs used batches of 48, three workers and the same .NET and SPIRV-Tools binaries. The SPIR-V and reflection
files were byte-identical across the two runs, and all 334 modules passed validation for Vulkan 1.3.

The SPIR-V editor indexes identifier uses on demand. The translator reuses intermediate data in memory and publishes shaders that are
ready while vertex-shader analysis runs. Cache readers allow files to be replaced while open, and the writer retries temporary Windows
sharing errors. Before that fix, two rejected cache replacements in the 720p co-op test hit the 15-second shader wait deadline.
The next run from the same stale cache reached the opening cinematic with zero deadline hits and zero draws skipped for a missing
shader. Its longest logged shader wait was **2.29 s**.

The launcher now lets Unreal lower the 3D scene resolution while keeping the HUD at 1080p. Window output has its own setting. See
[Graphics settings](GRAPHICS_SETTINGS.md).

The replay caches a pool lookup inside the current submission and validates the cache when the pool list changes. It asks for an
upload command buffer only when it needs to synchronize pages. The 1080p co-op A/B on the RTX 5070 Laptop in experimental 60 FPS
mode had about 4,370 draws and 53,400 memory uses per frame. With phase timing enabled, the memory lookup and sync path went from
**5.35 to 5.20 ms/frame**. The full translation thread was **17.19 vs 17.46 ms/frame** and presentation stayed around **51 FPS**
(p95 **22.59 vs 22.64 ms**). The visual suite flagged none of the three paired captures. This sample did not establish an overall CPU
or frame rate improvement.

## CPU-limited Windows follow-up (2026-11-23)

The Vulkan replay bounds lazy write-back shadow searches by the furthest recorded insertion in each bucket.
It also skips empty resource retirement polls, limits vertex-input comparisons to the entries passed to the
driver, and skips graphics descriptor binds when the descriptor set, pipeline layout and command-buffer
recording already match. Co-op recorded roughly **685 skipped descriptor binds per displayed frame**.
The descriptor cache is invalidated as the layout or command-buffer recording changes. [Vulkan descriptor set compatibility](https://docs.vulkan.org/spec/latest/chapters/descriptorsets.html#descriptorsets-compatibility)

The recompiler emits packed SSE2 for ARM single-precision vector `FMLA` and `FMLS`, with portable C and
packed FMA paths. The implementation uses each build's existing intermediate precision and ARM NaN handling.
The Windows game module was rebuilt for all 2,953 affected instructions in 48 translation units. The differential
suite passed 3,000 encodings with eight states each in each build mode. The test includes both vector widths,
addition, subtraction and source/destination aliasing. In a microbenchmark of 40 million four-lane accumulations,
median time was **688 ms** with the previous operation and **410 ms** with SSE2. Both produced identical output.

The i7-14650HX / RTX 5070 Laptop was limited to one logical thread on each of two physical performance cores for
the 275–301 s co-op window. The same saved game, fixed cameras and 30 FPS async replay mode produced about 4,350
draws per frame and two 960×1080 viewports in all three runs. CPU time per present divides the process CPU time across
all its threads by the presentations in the window. Capture timestamps align the presentation clock with the runtime log.

| Metric | Clean reference | Vulkan changes | Vulkan and packed FMLA/FMLS |
|---|---:|---:|---:|
| Presents per second | 27.42 | 27.81 | 28.15 |
| p95 interval | 52.50 ms | 49.87 ms | 49.94 ms |
| Process CPU per present | 63.07 ms | 64.29 ms | 61.99 ms |
| NVN translation CPU per frame | 13.32 ms | 13.15 ms | 13.28 ms |

The combined build improved presentation rate by **2.7%** and process CPU per present by **1.7%** in this comparison.
The intro test used both logical threads on one physical core. The reference and combined build both played at
approximately **0.89×**. Co-op screenshot pairs were sampled at three points and both views rendered. The largest share
of visibly different sampled pixels was 4.0% at a channel difference threshold of 24/255. The Vulkan validation startup
check completed on both builds with the same eight shader-interface diagnostics. The performance runs disable validation.

Windows run tags are `codex-lowcpu-clean-control`, `codex-lowcpu-runtime-only` and `codex-lowcpu-combined` in
`build/orbitals-debug/runs`. The local harness and aligned report are `test-low-cpu.ps1` and `report-lowcpu.py` in
`build/orbitals-debug`. The combined build is installed in `games/Orbitals`. The previous executable and game DLL
are backed up in `build/orbitals-debug/codex-lowcpu-rollback`.

## Next work, by expected gain

1. **Laptop — descriptor-set reuse (now ~20 % of the translation thread, + part of the 28 % memory sync).** Only 11 % of
   6,400 sets a frame are reused: per-draw uniform ranges change the set. Dynamic uniform-buffer offsets
   (`UNIFORM_BUFFER_DYNAMIC`) would let a set serve every draw that differs only by those offsets. Constraints: layouts
   change (pipeline cache), RADV's `maxDescriptorSetUniformBuffersDynamic`, the push-descriptor path, `ub_keep` copies.
   Needs the visual regression suite before landing (past bugs: invisible meshes, black views, wrong UVs).
   Study for v0.1 (not landed): a set is keyed by `g_bver[st]`, which moves with every uniform rebind, and the per-draw push-constant
   arena and driver segment (c0: base instance, dispatch size) are new arena slices each draw: all three would become dynamic offsets,
   with a separate version for the non-uniform bindings and the set reused while each uniform binding keeps its VkBuffer and range.
   `vkm_use` per binding stays (the memory sync is the other 28 %). Limits: 15–16 dynamic uniform buffers per set on NVIDIA / RADV
   (shaders with more keep the current path), none with push descriptors. Expected 1–2 ms of the 16 ms: worth a branch
   (`exp/dynamic-ubo`), validated by `tools/visual_suite` and `ab_stats.py`, not a release blocker.
2. **Laptop — memory sync (`vkm_use` / `pool_sync`, ~28 %).** 53k uses a frame, 12-16k on the slow path, mostly ranges that
   are new every frame (ring-buffer uniforms); a bigger lookup table was measured useless. Candidate: resolve a ring
   buffer's pool window once per submission instead of per use.
3. **Deck — GPU time per frame.** Per-pass GPU timing on the Deck (`NXRT_VK_GPUTIME_AT_S`), then the costs the replay adds
   on the GPU itself: the write-back comparison dispatches (~200 a frame), the full barriers at pass begin (9 % when
   removed, needs a dependency-exact barrier), uploads. CPU micro-optimisation alone does not move the Deck's FPS (§4.10).
4. **Recompiled game code** (69 % of all CPU, spread over ~8 worker threads; not the laptop's critical path, part of the
   Deck's power budget): PGO of the module on the co-op path; `-mfma` for the AdvSIMD helpers.
5. ~~Intel UHD white triangle edges~~ — fixed in v0.1 (GRAPHICS_ACCURACY.md §3): not the formatless reads (handled too, typed texel
   buffer variants) but fragment-shader subgroup shuffles that leave helper invocations out on Intel's driver; read through quad
   operations on Intel. Co-op on the UHD runs at ~4 FPS: correct, not a performance target.

## After v0.1: precompile every shader at the first launch

v0.1 translates a shader when the game first uses it (the replay waits for it, `NXRT_SHADER_WAIT_MS`) and builds the known pipelines at
every launch (`pipelines.tsv` prewarm). Precompiling everything before the first session means reading the game's own shader archive:
Unreal's shader code library sits in the IoStore containers (`.ucas`, Oodle-compressed chunks, each shader's code often compressed again).
Plan: find in the recompiled code the game's Oodle decompression and the shader library reader (`FShaderCodeLibrary` /
`FSerializedShaderArchive`), call them from the runtime at start (guest calls, as the netplay hooks do), dump every NVN shader they yield and
let the translator work through them in one long batch with a progress screen. Nothing of Oodle or of the game is shipped: the player's own
game code does the decompression. Expected first-launch cost: tens of minutes of translation for the whole game, once.

## Not to repeat without a new hypothesis

Push descriptors, merged light passes, hot-function layout, `-march=znver2`, CPU quotas, resolution-only cuts (Deck);
parallel recording of pass draws (parity on the laptop); a larger `vkm_use` table (NXRT_VK_SEEN_BITS=16).
