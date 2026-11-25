# Graphics accuracy — v0.1.0

How faithful the PC rendering is to *Orbitals* on Switch 2, what was checked, how, and what is still open. Three kinds of evidence are
kept apart:

- **demonstrated defect**: reproduced, its cause found in the renderer or the translated shaders, fixed and verified on captures;
- **PC-to-PC comparison**: the candidate build against the reference build on the same scripted path (it proves no regression, not
  fidelity to the console);
- **unverified difference**: something that looks odd on PC but was not compared with a Switch 2 capture of the same moment yet.
  No Switch 2 capture of the scripted path was available for this release: every console comparison below is still to do.

## 1. Method

- **Scripted path** (`tools/steamdeck/coop-path.script{,2}`): two players, real-time inputs, from launch to co-op gameplay in 330 s, the
  save of the reference playable ("Continue").
- **Visual suite** (`tools/visual_suite`): `run_suite.ps1` runs the path once per build with a full-resolution capture every 5 s (65 per
  run); `vsuite.py compare` pairs the captures of two runs by time on the path, prints the mean absolute difference (MAD, 0–255) and the
  share of pixels that differ by more than 24, per screen half (the two co-op views), and flags black views, much darker views and large
  differences; `compare.html` shows the pairs side by side. Inputs are real time: a build that loads a little faster or slower shifts the
  scene by a few frames, so a difference spread over the picture is usually camera or animation timing, a local one is a rendering change.
  Each flagged pair is looked at.
- **Scenes** (`tools/visual_suite/scenes.json`): engine and studio logos, photosensitivity warning, title screen, intro sketch
  animation, main menu (illustration, logo, options), controller assignment, save select, character select (Maki, Omura), loading,
  in-engine cockpit cutscene, high-five, co-op split screen with HUD (lighting, particles, transparency, post-processing, shadows of
  the colony corridor).
- **Shader checks**: every SPIR-V module the runtime rewrites passes `spirv-val --target-env vulkan1.3` (`NXRT_VK_TYPED_DUMP=<dir>`).
- **Logs**: the `[RED]` lines of a run (what the renderer knows it cannot do exactly) must be the reference's.

Captures are not committed: they are pictures of the game. They stay in the run folders named below and can be remade with the suite.

## 2. Scenes checked and status per GPU

| Scene (time on the path) | RTX 5070 Laptop (Windows) | Steam Deck RADV (Linux) | Intel UHD (Windows) |
|---|---|---|---|
| Logos, warning, title (0–39 s) | ok | ok (`rc1-path-20261121-160340`) | not captured |
| Intro sketch animation (39–49 s) | ok | ok (`rc1-path-20261121-160340`) | not captured |
| Main menu: illustration, logo, options (49–58 s) | ok (fixed `0ac42cb`) | ok (`rc1-path-20261121-160340`) | not captured |
| Controller assignment, save select (58–95 s) | ok | ok (`rc1-path-20261121-160340`) | not captured |
| Character select Maki / Omura (95–135 s) | ok | ok (`rc1-path-20261121-160340`) | not captured |
| Cockpit cutscene (150–160 s) | ok | ok (`rc1-path-20261121-160340`) | not captured |
| High-five, both characters visible (160–166 s) | ok (fixed `0ac42cb`) | ok (`rc1-path-20261121-160340`) | not captured |
| Co-op split screen: environment, characters, lighting, particles, transparency, HUD (166–330 s) | ok | ok (`rc1-coop-{1,2}`, shadows dark, HUD in place) | edges ok **since v0.1**; character drop shadows wrong (light translucent shapes), cause open |
| Bink intro video | not on this path; validated in docs/DEVELOPMENT_NOTES.md (audio leads by 2–3 s, KNOWN_ISSUES) | ok, with subtitles (`rc1-path`, 192–313 s) | not checked |
| Pause menu | not on this path; title in Japanese (unverified on console) | not checked | not checked |
"ok" = no defect seen on the captures of the path and no `[RED]` line beyond the reference's; it is not a pixel comparison with the console.

## 3. Defects fixed for v0.1 (demonstrated)

### 3.1 White triangle edges on Intel GPUs

**Seen:** on the Intel UHD of the i7-14650HX (Windows driver 101.x), every mesh of the co-op scene showed bright lines along its triangle
edges, most visible on dark surfaces (run `igpu-coop30-20261120-161659`).

**First hypothesis, checked and only partly right:** the device lacks `shaderStorageImageReadWithoutFormat`. `tools/vk_format_probe.c`
shows that Intel's driver can read storage **images** of every format without a declared format (per-format
`VK_FORMAT_FEATURE_2_STORAGE_READ_WITHOUT_FORMAT_BIT`), but no storage **texel buffer** format. 63 compute shaders of the cache read a
texel buffer declared `Unknown` (only R32_SFLOAT reached them on the path). They now get a variant declaring the bound view's format
(`vksh_typed_variant`, on by default only where the device lacks the bit; 18 variants made on the path, all valid SPIR-V). This is a real
correctness fix, but the edges stayed (`igpu-typed30-20261121-150931`).

**Cause:** Maxwell compiles a fragment shader's derivatives as SHFL across the 2×2 quad; the translator writes them as
`OpGroupNonUniformShuffle` with an index computed from the lane (81 fragment shaders of the cache). Vulkan does not make helper
invocations (the quad's pixels outside the triangle) active for that operation, only for quad operations. NVIDIA and AMD run them
anyway; Intel does not, so at every triangle edge, where quads hold helper lanes, the shuffle returned garbage.

**Fix:** each fragment-shader shuffle becomes: a source in the lane's own quad read with `OpGroupNonUniformQuadSwap`
(horizontal / vertical / diagonal by `(index ^ lane) & 3`), any other source with the original shuffle — the same values wherever the
original is defined (`vkspv_quad_shuffles`, `NXRT_VK_QUAD_SHUFFLE`, default on for Intel only). 81 modules rewritten, all valid.
**Verified:** `igpu-quad30-20261121-151722`: the edges are gone, the `[RED]` lines equal the reference's.

### 3.2 Earlier fixes kept in this release

| Defect | Cause | Commit |
|---|---|---|
| Main menu without its illustrated planes and logo, darker left half | vertex fetch buffers taken for 2D images: a capability literal counted as an id use in `fetch1d_tbuf` | `0ac42cb` |
| Maki and Omura invisible for 18 frames during the high-five | same | `0ac42cb` |
| Black views inside walls | walls not rendered: same | `0ac42cb` |
| Pink title screen | layered render targets: only layer 0 was drawn | `54823a2` |
| Bindless storage images / buffer textures read as zero | `img_ubo` / `tbuf_ubo` / `tex_ubo` bindings | `5b84511`, `d31610c` lineage |
| Wrong size queries on bound volume textures | invalid SPIR-V size query | `6925916` |
| GPU hang on RTX 50 (warp-aggregated atomic ballot after early returns) | ballot made per lane where the add's result is unused | `vkspv_ballot_per_lane` |

## 4. Regression check of the optimisations (PC-to-PC)

The candidate runtime against the reference runtime (`e7a94ed`, the last build before v0.1's changes; both with the lazy write-back
shadows, both in the 30 FPS reference mode), RTX 5070 Laptop, 65 captures each over the whole path:

| Pair | Runs | Median MAD | Pairs flagged | Verdict |
|---|---|---:|---:|---|
| reference vs v0.1 candidate | `vs-ref0-20261121-152323` / `vs-cand0-20261121-152903` | 2.7 | 1 | no rendering difference |
| v0.1 default vs Intel paths forced on NVIDIA (`NXRT_VK_QUAD_SHUFFLE=1 NXRT_VK_TBUF_TYPED=2`) | `vs-cand0-…152903` / `vs-cand0-forced-20261121-153441` | 6.8 | 2 | no rendering difference |

Every pair above MAD 5 was looked at:
- 26 s (title screen): the flash of the title fades in; the two captures are 0.15 s apart in a fade.
- 71 s (controller assignment, right half): player 2's "join" animation (a white flash) at another frame.
- 196 s and 231 s (co-op): the scripted camera swing caught at other angles; characters running at other positions.
- forced run, 176–322 s, left view only (MAD ≈ 19, right view ≈ 1.8 as in the reference pair): player 1's camera is turned a few
  degrees further: the real-time inputs landed on a slightly different game state. Shading, materials, characters and HUD are the same
  on a full-resolution crop.
- forced run, 147 s: the loading screen had already faded to black in one of the two captures.

The `[RED]` lines of the three runs are identical (four kinds, all pre-existing, see §6). So: the Intel-only paths do not change the
picture on a GPU that does not need them, and v0.1 does not change the picture on NVIDIA. This proves no regression; it does not prove
fidelity to the console.

The lazy write-back shadows (`59a8249`, on by default) were validated separately when they landed: a check mode compared every lazily
copied page with an eager copy (0 differences) and the captures and `[RED]` lines matched the reference (LAPTOP_60FPS.md §6).

## 5. Technical checks

| Area | How it is checked | Status |
|---|---|---|
| Transforms, skinning, GPUScene | characters and props in place and animated on every capture of the path; GPUScene texel buffers read through the typed path on Intel | ok on the path; GPUScene buffer dumps (`NXRT_VK_DUMP_*`) not compared with the console |
| Vertex buffers, UVs | menu planes, characters, environment textures (the vertex fetch fix above) | ok |
| Image formats, textures | BCn native, ASTC → BC7 on PC, per-format storage reads checked against the device (`vk_format_probe`) | ok; one BC3 storage copy cannot be read back (log line, no visible effect) |
| Descriptor bindings | `[RED]` lines; set reuse only for shaders without writes or guest-decoded bindings | one approximated binding (buffer texture sampled as an image reads 0) |
| Barriers, pass order | a full barrier at each pass start and around dispatches (correct, costs GPU time on the Deck) | ok |
| Compute | dispatch write-backs compared on the GPU against the CPU comparison: 534,027 ranges, 0 differences (Deck) | ok |
| Colour, tonemapping | game's own post-processing; presentation filter `standard` by default | no console reference yet |
| Depth, alpha blending, transparency | HUD, particles, translucent menu planes on the captures | ok on the path |
| Layered targets | every layer rendered (`54823a2`) | ok |
| Internal resolution | TV profile: 1920×1080 (3D drawn by the game at its own size), handheld 720p profile on the Deck | as the game asks |

## 6. Remaining limitations

- Intel: character drop shadows are light translucent shapes instead of dark ones (igpu-quad30-20261121-151722, legs of both
  characters); NVIDIA and the Deck draw them dark. Demonstrated, cause not found (to investigate: the shadow pass's depth reads and blend
  state on Intel).
- No Switch 2 reference capture: colour, exposure, shadows and effects are not proven identical to the console.
- Only the opening chapter is on the path; later areas, effects and menus are untested.
- Unverified differences: pause menu title in Japanese, camera folding onto the character near walls, cutscene audio ahead of the
  picture by 2–3 s (KNOWN_ISSUES.md).
- `[RED]` lines common to all builds: a buffer texture bound where a shader samples an image (reads 0), shader `e2cd2d78c70fdd98`
  writing float colour into an integer target, a BC3 storage copy that cannot be read back. No visible effect found on the path.

## v0.1.5 — Enter the ship

A Windows player reported missing character thruster jets, ship exhaust, fire, smoke and some scene details. The capture shows both
characters outside the ship with the Enter the ship objective. All 16 newly requested shaders logged near that section were compiled,
and the replay recorded no draws skipped for a missing shader. Three indirect draw pairs had zero GPU instances across the captured
windows. Those counts alone do not identify their effects.

The pass dump showed buffers bound as 2D textures in graphics and compute shaders. The SPIR-V conversion recognises wrapped 1D
fetches for numbered slots recorded by the translator. It ignores literal type widths and extended instruction numbers when
counting uses. It accepts duplicated loads of the same coordinate only when the loads share a block and intervening stores target
other variables. Cases without the required evidence keep the previous translation. Vulkan reflection now assigns uniform texel
buffer descriptors to the rewritten bindings.

All 747 shaders from the session passed SPIR-V validation in an isolated cache. Compared with the original build, 91 modules
changed and 144 descriptors became uniform texel buffers. The remaining 656 modules were byte-identical. The Windows format
probe accepted the tested texel formats on NVIDIA RTX 5070 Laptop and Intel UHD. The real co-op replay ran on NVIDIA. It showed
ship flames and smoke at the airlock and long exhaust trails during thrust. The console recording shows the same classes of effects
[after the opening movie](https://www.youtube.com/watch?v=gcKbaXobj2o&t=315s) and
[at the airlock](https://www.youtube.com/watch?v=gcKbaXobj2o&t=376s).

The player reported new red and blue artifacts around the burning ship after the opening film. The visually matched reference
capture already contains colour fringes at monitor edges. The specific new artifacts have yet to be isolated. The candidate also
showed intermittent GPU waits. A timed frame attributed 49.27 ms to the work ending at dispatch d42f1fbf408a6b5a. A follow-up
with that module unavailable attributed 225.62 ms to the work ending at a different, byte-identical dispatch, c4065f7847419be7.
These timestamps include GPU dependencies. The follow-up's compact JSON triggered a cache miss before its metadata was corrected,
so it does not establish a visual A/B result for that module. Keep this change on the experiment branch while investigating.

### Red and blue flashes after the opening film: found and fixed

**Seen:** with the texel-buffer candidate, the cockpit shot that follows the opening film (both characters looking at the burning
ship), with the film played or skipped, shows one-frame full-screen veils in red, blue, cyan or magenta. The flight recorder caught
19 to 39 such frames per 30 s; the reference build shows none (it shows no fire either). Bench: `tools/claude_laptop/flash_repro.py`
(stepper scenario gated on the cockpit shot, flight recordings), `flight_read.py scan` (one-frame red/blue pixels), `gamectl passview`
/ `drawstats` / `watch`.

**Located:** `passview` put the first divergence in the separate-translucency pass; hiding shaders and `drawstats` (fragment shader
invocations per draw) isolated the Niagara sprite draw `fdbfa1dd5f01a5f9` (29-37 instances): 0 fragments on most frames, up to 14 M
(seven screens) on the flash frames. Its vertex shader reads each particle through `SortedIndices[SortedIndicesOffset + instance]`;
`watch` dumps showed that range never held a permutation of the particles: the GPU sort result was garbage.

**Cause:** the sort is Unreal's GPU radix sort (key generation `1a30b8e5b743a0bb`, then per 4-bit digit: clear `c4065f7847419be7`,
upsweep `5c7fb5af900ce0bc`, spine `f27f74bb26d86ae9`, downsweep `d032ce5090303e01`). Capturing each dispatch's buffers before and
after (`gamectl watch` on compute keys, `flight/dwatch.bin`) showed the key generation correct (indices 0..36, real depth keys) but
the first upsweep's histogram right for digits 0-6 and zero for digits 7-15. The upsweep uses 8,836 bytes of shared memory (the NVN2
compute control section gives it at +0x64); the translator was never told and declared 4,096 bytes, so rows past word 1,024 (from
digit 7 on) were undefined accesses. The spine (4,964 bytes) and downsweep (9,444 bytes) were cut too. With all keys equal (the
reference build reads the particle data as zero) the sort is an identity and the bug stays invisible: the texel-buffer fix exposed it.

**Fix:** `nxs_front.py` passes the size to the translator (`shared`, the field mesh stages already used), `FRONT_VERSION` 4. The
translator declares 2,209 words for the upsweep. Every NVN2 compute shader with more than 4 KB of shared memory benefits, not only
the sort. **Verified:** kit `build/flash/fix1` (the 747 session shaders plus the session's own dumps retranslated, 45 compute modules
changed, 703 identical): 0 flash frames over 30 s of the cockpit shot (runtime detector and red/blue scan), and the cockpit now shows
the ship's fires with their dark smoke plumes, as on the Switch 2 recording.

**Performance:** the same fault was the texel-buffer candidate's performance regression. Corridor windows of the QA co-op route,
two 12 s windows on all cores, RTX 5070 Laptop, the same runtime binary for the three kits (`build/flash/perf.sh ab1`):

| Kit | FPS (window 1 / 2) | p95 present interval (ms) | written back per frame | uses while a write-back was on its way |
|---|---|---|---|---|
| reference (no effects) | 50.86 / 51.01 | 24.19 / 24.18 | 47.2 MB, 211 k words | 55 |
| texel candidate (effects, truncated shared memory) | 26.11 / 9.93 | 26.45 / 819.76 | 49.3 MB, 606 k words | 256 |
| fix1 (effects, shared memory fixed) | 50.51 / 51.54 | 24.38 / 22.57 | 46.8 MB, 252 k words | 51 |

The garbage sort and the simulations fed from it made the GPU stalls; with the sort correct the effects cost about 1.6 MB of
uploads a frame and no measurable FPS in this window.

### Green, blue and magenta sprites in space on AMD (Steam Deck): found and fixed

**Seen:** on the Steam Deck (RADV), even with 32-lane subgroups, the space route shows giant green, blue or magenta sprites over a
player's half of the screen, and the burning-ship cutscene loses its rainbow curtain. The RTX PCs draw neither.

**Located:** `NXRT_VK_TBUF_DUMP` (vk_replay.c: the memory behind the texel buffers a listed shader binds, four snapshots) and its
writer log, with `tools/steamdeck/tbuf_stats.py`. The translucency sprites (vertex shader `df34be095a55bcff`) read their particles
through the index list that the radix sort's downsweep `d032ce5090303e01` writes. On the PC that list is a permutation (0..0x16);
on the Deck it held duplicated and out-of-range indices and the sort's own `0x0badf00d` padding (530 to 952 entries per snapshot).

**Cause:** the downsweep (128 threads, 25 workgroup barriers, no subgroup operation) was compiled for NVIDIA's lockstep warps: it
hands values between the lanes of one warp through shared memory without a barrier. SPIR-V does not promise that order; RADV's ACO
keeps or reorders those shared accesses, and the sort breaks.

**Fix:** `vkspv_volatile_shared` (vk_shader.c) gives every load and store through a Workgroup pointer the Volatile memory access. On by
default on every driver except NVIDIA's own (the reference, which draws it right as compiled); `NXRT_VK_SHARED_VOLATILE=0/1` forces
it. **Verified** on the Deck, space route, same build: 0 padding entries and a clean permutation; worst saturated blue 0.55 % of a
capture against 13 %, green 0 against 13.5 %. Co-op corridor 21.67 against 21.72 FPS (the space scene is not comparable: the build
without the fix draws the broken sprites). NVIDIA (RTX 5070 Laptop): unchanged, 53.5 / 50.5 FPS.

## Switch 2 references and the space scene (v0.1.5)

**Sources.** The references are kept on the development PC, outside the repository, with their sources listed beside them:

- the owner's Switch 2 photos of the ship bay in space;
- the official February 2026 press screenshots from the Kepler Interactive / Cosmocover press release.

Video platforms are not used as sources: their terms do not allow downloads outside their own features.

**What is fixed.** The vertical rainbow curtain behind the ship bay is drawn again. Niagara curve buffers were read as 2D images that
returned zeros; see the SPIR-V use index fix (`fetch1d_tbuf` v7).

**What still differs.** On the recorded route, the curtain shows pink, violet and cyan streaks.

- The owner's photo of the same bay shows more orange and yellow.
- The press screenshot of a later space fight shows bright orange, white and cyan streaks over a blue haze, with strong bloom and film
  grain. Its scene, camera and capture conditions (resolution, grading, compression) differ from ours, so it supports no pixel
  comparison.

**What is ruled out.** The curve tables the curtain's Niagara compute shaders read are `R32F` buffers (NVN format `0xA`), not colour
formats. A colour format conversion is not the cause.

**What remains open.** An aligned capture of the bay (same camera, same moment) is needed to say whether the hue difference is real.
If it is, the next checks are the curve sampling (index arithmetic after the 1D-fetch rewrite) and the emissive or bloom intensity of
those sprites.
