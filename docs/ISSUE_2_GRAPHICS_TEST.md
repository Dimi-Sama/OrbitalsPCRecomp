# v0.1.6 preview · ship rendering test

The [issue #2 investigation by KingsmanZer0](https://github.com/Dimi-Sama/OrbitalsPCRecomp/issues/2#issuecomment-7183991749)
identified two separate artefacts on an RTX 4090. This preview applies the memory-order experiment to the three compute passes of
the particle sort and disables floating-point contraction on the hull material `e97d65cf4844ecdb`. On NVIDIA's proprietary
driver, these two changes are enabled by default and the previous `Volatile` override is off. On other drivers, both new
changes are opt-in. The warp change requires 32-lane compute subgroups.

The warp pass adds subgroup execution barriers for read/write transitions within a basic block, and subgroup memory barriers for
stores reaching shared accesses across block boundaries. An execution barrier orders the invocations in the same dynamic subgroup
tangle. The cross-block memory barrier does not wait for lanes that are executing a different path. Check sort output or gameplay on
each driver before generalizing the result. [SPIR-V barrier instructions](https://registry.khronos.org/SPIR-V/specs/unified1/SPIRV.html#_barrier_instructions)

## Compare on RTX 3060 or RTX 4090

Run the same intro, including the rainbow curtain and burning ship, through the cockpit and into the first playable space shot.
Use a test profile and the same camera, resolution, graphics preset and original save state. Restart Liftoff and the game for each
row. Start at 30 FPS Reference, record at least 2,000 frames per row when practical, and count one-frame flashes separately from
hull contours. The game log records the effective driver, subgroup size and workarounds at startup, and counts the changes per shader.

| Comparison | `NXRT_VK_WARP_SYNC` | `NXRT_VK_NO_CONTRACT` |
| --- | ---: | ---: |
| Both changes | 1 | 1 |
| Hull only | 0 | 1 |
| Particle sort only | 1 | 0 |
| Baseline | 0 | 0 |

Set `NXRT_VK_SHARED_VOLATILE=0` for all four NVIDIA comparisons. In a Windows command prompt, for example:

```bat
set "NXRT_VK_SHARED_VOLATILE=0"
set "NXRT_VK_WARP_SYNC=0"
set "NXRT_VK_NO_CONTRACT=1"
Orbitals-Launcher.bat --data-dir "%LOCALAPPDATA%\OrbitalsPreview016Graphics"
```

## Steam Deck and performance

Prepare shaders once in a fresh test profile and let it finish before timing. Each combination of the two flags has its own Vulkan
pipeline cache. Run one untimed pass with each configuration, then compare at least three repetitions per configuration and two
12-second windows per repetition at the same checkpoints. Keep the Steam Deck's normal Volatile and subgroup settings in all runs.
On the Deck the default row is `0/0`; force `1/1` for the combined comparison, and then use the two single-change rows to isolate
any regression. Record the mean FPS, p95 frame time, visible artefacts and the Vulkan startup lines. The offline translation cache
stores the SPIR-V inputs and can be shared across flag combinations after preparation.

For the flash detector, run a separate capture with `tools/claude_laptop/flash_repro.py` and a scenario that stops stepping on the
cockpit shot. Flight recording adds work of its own. Use a timing run with flight recording and frame capture off for FPS.
