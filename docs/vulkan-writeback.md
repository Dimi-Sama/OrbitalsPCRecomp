# Optional device-local writeback snapshots

Dispatch writeback compares GPU results with a snapshot so concurrent CPU words that the shader did not change can survive. Previously the snapshot was copied into host-visible memory and then read by GPU comparison. `NXRT_VK_WB_BASE_DEVICE=1` keeps that snapshot in a 256 MiB device-local ring; compact comparison records remain host-visible. It requires `NXRT_VK_WB_GPU>=1` and is **off by default**. No GPU/CPU tuning defaults are changed.

This contribution also fixes snapshot COPY-to-COMPUTE ordering, prepares landing resources before dispatch, protects ring reservations until posted and handles completion-queue allocation failure explicitly instead of using an unchecked realloc result. The ordering and lifetime corrections apply with the optimization disabled as well.

## Safety rules (why the code is shaped this way)
- One plan per dispatch range, made in `vkm_wb_prepare` before the shader is recorded (`wbp_prepare` / `wbp_plan` in
  `vk_wb_core.h`), in this order: device plan (snapshot in `g_wrd`, GPU comparison), host GPU plan (snapshot in the
  host ring, GPU comparison), host CPU plan (snapshot and the range after the shader in the host ring, CPU comparison),
  none (no snapshot: the whole range goes back, as before when the ring was full). A plan takes every piece of ring
  room it needs (snapshot, records, the wb_gpu 2 copy or the CPU plan's "after"), its landing record (`wb_t`, with the
  wb_gpu 2 check's block masks) and one completion post (`vks_post_reserve`), or it keeps none of them: a device plan
  that cannot be completed (forced by `NXRT_VK_WB_BASE_DEVICE_FAIL` before any room is taken, ring full, no memory for
  its record) is rewound before the host plan is tried, so it never costs the host plan its room. After the shader
  each range takes exactly the path planned for it; nothing there allocates, and nothing degrades to the whole range.
- No memory for a completion effect (any submission, flag on or off): an ordinary post (event, counter, write-back,
  or a reserved token from another submission) that finds the queue full and cannot grow it ends the run
  (`post_fatal` in `vk_submit.c`, via `postq_push_must`) while the submission is still being recorded, so no fence value
  is ever published as done with an effect missing. An intermediate development revision dropped the effect with a log line and the guest saw
  the submission complete without it (review finding: 16 posts in 16 entries, then a landing and an event lost).
  Posts into reserved room never allocate.
- Ring reclamation: a landing releases the ring up to the end it was posted with, and landings run in post order. A
  range's room is taken before the shader but its landing is posted after it, after the landings of earlier ranges
  and copies, so a plan is *held* from when its room is taken until its landing is posted (or the plan is given up:
  a range planned again by a later dispatch, `vkm_wb_drop` at a submission's start). A landing's end stops at the
  oldest held plan (`wring_end`), so the first landing of a dispatch can no longer release the room of the second
  range's records before that range lands (review finding: two 256 B ranges, B's records at 800, both landings ending
  at 1088). The tail never moves back (`wring_released`); `wr_land` publishes it after its last read.
- The ring must really be device memory: `vk_alloc_mem` may hand out system memory over the budget. `wrd_init` refuses
  anything with `sys` set or without a device-local type and keeps host snapshots (log: `[RED] wb_base_device: ...`).
- Write after read: the snapshot copies read what the shader writes. The dispatch waits for them (COPY -> COMPUTE
  execution dependency after the snapshot batch), in both modes.
- wb_gpu 2 stays an independent oracle: with a device plan the host ring also gets a snapshot, and the CPU compares the
  GPU's records (made from the device snapshot) against its own word-by-word comparison of host copies.

## Switches and log
| env | meaning |
|---|---|
| `NXRT_VK_WB_BASE_DEVICE=1` | device snapshots (default 0) |
| `NXRT_VK_WB_BASE_DEVICE_FAIL=<n>` | test: every n-th range that could take a device snapshot gets the host one (1 = all) |

Log lines (every 60 frames when wb_gpu or the switch is on):
`wb_base per frame: snapshots X MB in host memory, Y MB in device memory, Z ranges given the host snapshot instead of the device one; so far F such (K forced), D device-snapshot write-backs dropped`.
At first use: `wb_base_device: dispatch snapshots in device memory (256 MB ring, wb_gpu N)`. The first 5 fallbacks
log their reason (`a range gets the host plan (...)`). D counts planned write-backs whose landing could not be posted;
the current posting API returns success or terminates, so this legacy defensive counter cannot increment. Its label says device snapshots but its defensive branch also covers host plans. With wb_gpu 2: `wb_gpu per frame: ... checked N ranges so far, M blocks differing` (M must stay 0).

## Reproducing host validation

```sh
gcc -O1 -g -Wall -Wextra -fsanitize=address,undefined -fno-sanitize-recover=all -Iruntime/nvn/vk tests/test_wb_core.c -o /tmp/orbitals-wb-core
/tmp/orbitals-wb-core
```

The real allocator/planner/post-queue helpers cover the two-range premature reuse regression, 200,000 modeled mixed dispatches, transactional fallback and allocation failure with a full completion queue. The original-rule model overlaps live records; the held-plan model ends with zero overlaps and zero holds. This is a host model, not a Vulkan execution or race-detector proof.

## Prior game validation and remaining gate

The source implementation was built and exercised on Windows with a copied launcher test profile, not the active user save. GPU differential mode (`WB_GPU=2`, device snapshots enabled) compared 1,832,592 ranges with zero differing blocks and zero dropped writebacks. Forced-host fallback compared 1,672,583 ranges, with 1,767,109 forced fallbacks and zero differing blocks/drops. These finite runs do not establish correctness on every driver, level or allocation failure.

The independent upstream extraction has not been booted on the PC. Before merge, build the NVN archive and runtime, repeat the GPU differential check with device bytes nonzero, repeat with forced fallback, then compare identical scenes with the flag off/on in alternating runs and inspect screenshots. Keep all other settings fixed; inspect p95 and long frames as well as averages.

The original experiment used a 9800X3D/RTX 5090, 185-second co-op ship runs, measuring seconds 120–180, with DEFER=1, SPLIT_MS=2, WB_GPU=1 and 256 MiB staging (non-default benchmark settings). Two alternating runs per variant at each resolution gave:

| Resolution | Host snapshots FPS | Device snapshots FPS | Host p95 ms | Device p95 ms |
| --- | --- | --- | --- | --- |
| 1800p | 49.69, 50.38 | 58.12, 58.18 | 24.62, 24.20 | 20.09, 20.01 |
| 2160p | 44.02, 44.04 | 51.77, 52.13 | 27.97, 27.40 | 27.65, 27.83 |

At 2160p the p95 ranges overlap. The proportion above 30 ms increased at both resolutions. Neither resolution reached the stable-60 target. No obvious visual change was seen in the matched source-run screenshots; this is not a claim for all content or for the extracted branch. Other pre-existing development-tree changes were present in both source variants, so these measurements are not an upstream-base benchmark.

## Costs and rollback

The optional ring consumes 256 MiB additional device memory. It is allocated lazily on first use during recording, which can cause a one-time hitch. Host-ring pressure is unchanged: its corresponding room remains reserved. Low-memory GPUs may evict textures sooner. Genuine device-local allocation is required, otherwise the host path remains active. Dirty tracking and full-page reuploads are deliberately unchanged.

Set `NXRT_VK_WB_BASE_DEVICE=0` (or remove it) to disable the optimization. Use process environment variables with the normal runtime launch path; this PR does not introduce `env=` INI parsing. Removing the option keeps the correctness fixes. Reverting the PR restores the prior implementation. No game assets or saves are included.

Extraction checks: GCC ASan/UBSan host test completed with `OK`; MinGW syntax checks passed for vk_mem.c, vk_replay.c and vk_submit.c using placeholder generated shader arrays only for syntax. The existing SetThreadDescription declaration warning remains. Placeholder arrays were not linked or executed; a full shader build and runtime boot are still required.
