# Vulkan pipeline seeds

One file per game build, named by the first 32 hex digits of its main module's build id. The launcher passes the installed build's file to the
runtime as `NXRT_VK_PIPELINE_SEED`. At start, the runtime's prewarm threads build every pipeline the file lists whose shaders are in the shader
cache, while the game boots. Without a seed, the first session builds each pipeline the first time a draw needs it, a few to a few hundred
milliseconds in that frame. Later sessions also prewarm the pipelines they recorded in `pipelines.tsv`.

Each line is a pipeline as `runtime/nvn/vk/vk_pipe.c` lists it in `pipelines.tsv`. `G` lines give the vertex, fragment, geometry and
tessellation shaders by their 16-hex-digit keys (hashes of the game's shader code), then the fixed-function state in hex: vertex layout,
blend, formats and samples. `C` lines give a compute shader's key. The files hold no shader code and no game data.

| Build | Lines | Made from |
| --- | ---: | --- |
| `0f8ef52cf4eee37628f366a539d5d6ad` (Orbitals 1.0.x, Switch 2) | 853 (725 graphics, 131 compute) | Windows co-op sessions: menus, the colony corridor, the cockpit scene, the space scene around the ship (2026-11-24) |

On the recorded route with prepared shaders and an empty pipeline cache, all 853 listed pipelines were built 12 s after start. The session
built no pipeline at first use, against 599 (1.75 s) without the seed. Frames over 100 ms fell from 29 to 8. See `docs/SHADER_PREWARM.md`.

To extend a seed, merge the `pipelines.tsv` of sessions that covered other scenes: unique lines, order kept.
