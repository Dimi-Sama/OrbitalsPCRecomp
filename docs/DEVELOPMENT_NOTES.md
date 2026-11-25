# Development notes (v0.1)

The findings behind v0.1 that are not obvious from the code, kept short. The detailed investigation logs of the development branches
(in French, with the development machines' paths) are not part of the public tree.

## Game clock: 31.25 MHz (the 30 FPS slow motion)

The game's SDK converts system ticks with a fixed 31,250,000 Hz base (`nn::os::GetSystemTickFrequency`); the runtime first counted at the
Switch 1's 19.2 MHz. Unreal's time, the animations, the camera, physics and cutscenes then ran at 19.2 / 31.25 = 0.614× real time while
the host-paced audio kept its speed. Switch 2 titles (title id `0x04…`) now get a 31.25 MHz counter for `CNTVCT`/`CNTPCT`,
`svcGetSystemTick`, `GetInfo 0xF0000002`, `CNTFRQ_EL0` and the presentation timestamps given to Unreal (`SWR_TICK_19M2=1` restores the
old clock for comparisons). Checked: logos to title 1.53–1.57× sooner (1.63 expected, the rest is loading).

## Frame pacing

The game moves its clock by its present interval (vblanks at 60 Hz) each frame, so a frame is not shown before that much time has passed
since the previous one (`nvn_glue.c swr_present_pace`, `SWR_PACE=0` turns it off). In the 30 FPS reference mode the game's clock moves
two vblanks a frame whatever interval it last set; without that, its 60 FPS mode ran at about 30 FPS, half speed. `ue_fps=60` is the
experimental mode: real frames at the normal game speed.

## Audio

Unreal's AudioMixer opens an output stream through `audsmx:u` (`nn::audio::sysmix`), which did not exist: the SDK retried forever and
the `IAudioRenderer` created at start only ever plays silence. The PCM does not go through IPC: the SDK writes into a ring inside the
work buffer given to `CreateStream`, and the server (the ADSP on the console) moves a read index in that buffer. The runtime now serves
the sessions, streams and events, reads the ring at 48 kHz in 5 ms steps of the guest clock (int8/16/24/32/float, 5.1 → stereo), and
keeps the output queue short (~50 ms instead of 262 ms). Measured: 48,048 frames/s consumed, no underrun in menus, cutscenes or play;
a level load freezes the game ~2 s (silence). Not measured: the exact audio/video sync of cutscenes.

## Cutscenes (Bink 2)

Cutscenes are played by the game's own recompiled Bink player: no third-party video codec is shipped or needed. The intro video's
first 72 frames are uniform black (3 s at the start of the file, part of the media). The audio of the intro leads the picture by 2–3 s
(KNOWN_ISSUES.md); the guest player opens the file, decodes its first slices, then waits for an asset load before showing frames.
Native decoders (an LGPL FFmpeg patch, Mobipeg under GPL/AGPL) and hardware transcodes were studied for speed and are not used: a
replacement would have to drive Unreal's video textures and playback states from the same Wwise start.

## Upscaling

The finished picture can be scaled by the presentation pass (bilinear, sharp, or FSR 1 EASU when the window is larger than the picture).
DLSS / XeSS / frame generation were studied (motion vectors and depth are available in the game's passes) and are not part of v0.1: no
spatial filter is presented as DLSS.

## Shaders on a first session

The live translator (`tools/nxshader/nxs_live.py`, Ryujinx-derived, needs .NET 10) turns each NVN shader into SPIR-V the first time it
is used. Skipping draws while a shader was missing left one-time work wrong for the whole session (a much darker colony corridor until
the next start); the replay now waits for the translation (`NXRT_SHADER_WAIT_MS`). Dumping shaders as soon as the game creates its
programs (before their first draw) did not help: the lighting work that went wrong runs during loading, right after creation.
Precompiling every shader before the first session is the first item after v0.1 (PERFORMANCE_ROADMAP.md).

## Tests without a person at the controls

`tools/visual_suite/stepper.py` drives a session in steps, each sent when the game shows the screen it expects (captures compared with
signatures of known screens). Its input clock leaves out the renderer's shader waits, so a first session follows the same path as a
later one. `tools/claude_laptop/run-orbitals.ps1` / `rerun.ps1` replay recorded runs with other settings; `gfx_report.py` and
`ab_stats.py` summarise them.

## Vulkan replay and GPU memory (v0.1.5 phase 2, RTX 5070 Laptop co-op unless noted)

Critical path with the flight recorder off (`SWR_TRACE`): the game submits its main command list about 1.4 ms into a frame; its replay
takes about 11 ms on one thread (handed to the GPU every 4 ms); the GPU finishes about 6.5 ms after the replay ends, and the game waits for
that in `nvnSyncWait` before its next frame. The replay thread is busy about 14 ms of an 18.7 ms frame. The game's blocking waits are its
own queue fences (about nine a frame, the first one blocks), never the sync handed out at texture acquire.

Measured and not merged (branches kept):

| Change | Result |
|---|---|
| Replay micro-optimisations (`vkc_int` cache, no TLS pipeline memo, static arrays) | about 1 % of the replay thread's CPU time |
| No barrier before a compute dispatch (unsafe, measurement) | no FPS change; the dispatches themselves take 0.27 ms of GPU time a frame |
| Write-backs grouped per guest page | host pre-write calls -80 %, the same time and FPS |
| Push descriptors on NVIDIA | replay 14 → 17 ms: slower |
| No dispatch write-back of 1 MB or more (unsafe, measurement) | 53 → 56 FPS: 7 ranges, 41 MB a frame, cost about 5 % |
| Parallel recording of a pass's draws (`exp/opus-parallel`, ported from the earlier `pc-parallel-replay`) | 3,050 of ~4,500 draws a frame on workers, lock waits 0.2–0.9 ms, but a worker's draw costs 2× (2 workers) to 3.2× (4) a serial one, on P-cores as well (CPU sets): no speed-up. Each binding validates its memory range against page tracking shared with the game, the replay and the completion thread |
| Dirty tracker: 64-page group maxima | no change |

Guest memory imported as Vulkan memory (`VK_EXT_external_memory_host`, branch `exp/opus-host-import`): a pool's buffer is the guest memory
itself, so nothing is copied before a use and nothing back after a GPU write, as on NVN. Replay CPU time 18 → 10 ms a frame on the RTX, but
the discrete GPU then reads system memory over PCIe: 6.6 FPS (41 FPS with only pools of 1 MB or less). On the laptop's Intel UHD (one
memory) co-op goes 4.6 → 5.5 FPS (replay 38.9 → 26.9 ms) with the same picture. The branch imports by default on integrated GPUs only; it
was then tested on the Steam Deck (RADV, 2026-11-25): with the pools still write-protected by the dirty tracker the GPU stopped
4.2 s after start (device lost at a submit: RADV imports host memory as amdgpu user pointers, which a read-only page invalidates); with the
imported pools left out of the tracker it runs, but frames reach 3.6 s and the scripted route never gets to co-op (19.7 → 3.9 presents/s
over 200 s, texture uploads 50 ms of a 3.6 s frame): the user pointers, about 2.2 GB in 757 pools, are likely revalidated at every
submission. Not merged. A usable form would import only small buffer-only pools that turn hot, converted at run time, and leave every
pool holding textures mirrored and tracked.
