# Orbitals on the laptop (MSI Katana 15: i7-14650HX, RTX 5070): the path to 1080p60 co-op

Goal: real, stable 60 FPS co-op at 1920×1080, frame times under 16.67 ms, **no frame generation**.

Status: **not reached.** Co-op combat runs at ~44–46 FPS (≈ 22 ms a frame). The cause is measured below; it is a single serial
CPU stage, not the GPU and not the NVIDIA driver.

## 1. Method

Same scripted co-op path and window as the Steam Deck work (`tools/claude_laptop/run-orbitals.ps1`), `ue_fps=60`,
`fps_limit=0`, `forced_vsync=0`, `NXRT_VK_WB_GPU=1`, 1280×720 render as on the Deck profile (the CPU replay cost is
resolution-independent; the GPU is not the limit — see below). Recompiled module: the SIMD build (`recompile-simd`, 217 866
functions + merged hints). The runtime's own sampling profiler (`profile=1`, `SWR_PROF_WINDOWS=1`, `SWR_PROF_CALLERS=1`) gives
the module/thread/function split; the runtime's `[nvn]`/`[vk]` logs give the per-frame stage costs. Raw: the Deck-style run dir
`build/orbitals-debug/runs/prof-coop-20261121-095637` (kept on the laptop) and `build/laptop-coop-profile-0200.txt`.

## 2. Where the time goes (co-op combat, steady state, ~43.7 FPS, 22.3 ms a frame)

**By module (share of active, non-waiting, CPU time):**

| Module | share | what it is |
|---|---|---|
| game code (recompiled) | **~69 %** | `Orbitals_code.dll` — Unreal gameplay + animation/skinning |
| `Orbitals.exe` (runtime) | 16.0 % | NVN→Vulkan replay (translation thread) |
| `ucrtbase.dll` | 7.7 % | CRT `memcpy`/`memmove` — the replay's buffer uploads |
| `nvoglv64.dll` (**NVIDIA driver**) | **6.3 %** | the Vulkan driver |

**The NVIDIA driver is 6.3 % of CPU and the GPU is not saturated — so the driver is proven *not* the bottleneck** (the brief
asked not to assume it without proof). No driver change is warranted; frame generation is neither needed nor used.

**By thread (active samples):** one thread dominates at **26.4 %** (the NVN→Vulkan translation thread); the game's own
animation/skinning work is spread across ~8 worker threads at 5–13 % each and runs in parallel. So the game-side 69 % is *not*
the critical path — it is parallel. The serial critical path is the one translation thread.

**The decisive number, from the runtime's own log:**

```
[nvn] translation thread: 20.87 ms a frame translating (CPU 20.36 ms)
[vk]  present interval p50 22.3 ms (≈ 43.3 FPS)
```

The frame (22.3 ms) is gated by the translation thread's **20.4 ms of CPU on one core.** 60 FPS needs the frame under
16.67 ms, i.e. this one thread must drop by ~4 ms (~20 %), or its work must move off the critical path.

## 3. What the translation thread actually does per frame

From the replay counters (`[vk] replay ... per frame`):

- **4 366 draws**, 428 render passes, 125 dispatches, 23 clears.
- **6 408 descriptor sets** written (only 697 reused — 11 %).
- **53 337 memory "uses"** resolved (37 582 fast, **15 750 synced** — the slow coherence path).
- **~131 000 dynamic-state group commands**, of which ~123 000 (94 %) are deduplicated (`dyn_dedupe`) and skip the Vulkan call,
  but the dedup comparison itself still runs ~131 000×/frame.

This is a very large, serial command stream decoded and dispatched on one thread. The 20 ms is spread across it (no single call
dominates): descriptor resolution (`vkm_use_`, `write_set_`), the 15 750 synced memory uses, the 131 k state-dedup checks, and
the `memcpy` of buffer data (the 7.7 % `ucrtbase`).

## 4. What was tried / considered, and why 60 FPS is not reached

- **SIMD inlining (kept, +2 %).** The correctly-rebuilt SIMD module (217 866 functions + hints) measured 46.71 vs 45.80 FPS
  against the previous module, no regression. Kept. It does not change the translation-thread bottleneck.
- **Parallel replay — the obvious lever, but it does not address this bottleneck.** Branch `pc-parallel-replay` parallelises the
  *recording of a pass's draws* onto worker threads (`NXRT_VK_PARALLEL=<n>`). A prior test found it **parity only** (no FPS gain),
  which is consistent with the profile: the serial cost here is command **decode/dispatch and state/descriptor resolution**, not
  the secondary-command-buffer recording that branch offloads. A re-test this session was blocked anyway — that branch's runtime
  (older ABI) `svcBreak`s at boot with the current SIMD module, so a matched module rebuild would be required; given the prior
  parity result and the profile, it was not pursued. Truly parallelising the **decode** (not just the recording) would be a large
  architectural change and is the only clear route to a big cut.
- **Per-command reductions (not done — risk vs. bounded payoff).** Better descriptor-set reuse (today 11 %), fewer synced memory
  uses, or a cheaper dedup could each shave part of the 20 ms, but each is deep, correctness-sensitive replay-internals work with
  a bounded individual payoff; none alone closes the 4 ms gap safely.
- **The command volume is the game's** (4 366 draws/frame). Cutting it would mean reducing rendering, which the brief rules out.

## 5. Honest conclusion

The laptop is **CPU-bound on the single NVN→Vulkan translation thread (~20.4 ms/frame)**, not on the RTX 5070 or its driver
(6.3 %). The kept gains (SIMD +2 %, plus the thread-id cache and `wb_gpu` already in the build) leave co-op at ~44–46 FPS. Real
1080p60 without frame generation requires moving the translation work off the critical path — i.e. parallelising the command
**decode/dispatch**, not just the draw recording (which is already prototyped and was parity-only). That is a substantial
architectural change and is the identified next effort; it is not a small fix, and it is not yet demonstrated.

## 6. 2026-11-21 afternoon: the translation thread profiled on its own, and the first real cut

`profile=1` now samples the NVN translation thread on its own (`plat_prof_add_focus_thread`), with the runtime caller of
every sample it spends in `ucrtbase` / the NVIDIA driver (SEH unwind); `tools/claude_laptop/prof_symbolize.py` maps it to
functions. Same co-op path, 220-230 s, % of the thread's active time:

| Before | share | After lazy shadows | share |
|---|---|---|---|
| `guest_copy` (memcpy) | **21.1 %** | `guest_copy` | 4.9 % |
| descriptors (`write_set_` + driver under it) | 16.7 % | descriptors | 19.6 % |
| memory sync (`vkm_use_`, `pool_sync`, `nvn_dirty_since_span`, `pool_find`, `gpu_pending`) | ~20 % | memory sync | ~28 % |
| `draw` + driver under it | 9.5 % | `draw` + driver | 12.3 % |

**Lazy write-back shadows (commit 59a8249).** Each recorded GPU write copied its pages into "shadows" (8,700 pages = 35 MB
a frame) for a merge that needs ~55 words a frame. The pages are synced and write-protected at that moment, so they are now
listed and copied only if the dirty tracker is about to make one writable (copy-on-write). Check mode
(`NXRT_VK_SHADOW_LAZY=2`): 0 failures; 8,450 pages listed a frame, 5-48 copied on a write, ~300 copied at once (hot).

| ue_fps=60, co-op 1080p, 190-238 s | FPS | p50 | p95 | translation CPU / frame |
|---|---:|---:|---:|---:|
| eager shadows (2 runs) | 46.77 / 46.50 | 20.9 / 21.2 | 26.8 / 26.9 | 18.85 / 18.81 ms |
| **lazy shadows** (2 runs) | **51.19 / 52.22** | 19.3 / 18.7 | 23.6 / 22.3 | **16.37 / 16.12 ms** |

Tried and not kept: a 64K-entry `vkm_use` range table (slot misses 14.6k -> 8.2k a frame, but no faster: the remaining
ranges are new each frame, ring-buffer uniforms). Next: descriptor-set reuse is 11 %; dynamic uniform-buffer offsets would
let a set serve draws that differ only by their uniform offsets (descriptors ~20 % + part of memory sync ~28 %).
