# Offline shader cache prewarm

`nxs_live.py --offline` prepares SPIR-V and reflection from completed NVN2 `.ctl` and `.code` pairs. It verifies the default NVN2 shader key against each pair, uses the same translator as the live path, and validates modules with `spirv-val` for Vulkan 1.3 before publishing them.

Run the command before starting the renderer, with a dedicated cache directory and the same translator and shader options as the intended consumer. Use .NET 10 and install `spirv-val` and `spirv-opt` on `PATH` or set `NXSHADER_TOOLS` to their folder.

```text
python -B tools/nxshader/nxs_live.py --offline --dump captures --cache shader-cache --dotnet /path/to/dotnet
```

Repeat `--dump` to add captures from later sessions. Each pair must be complete within one folder. Duplicate pairs are translated once. If their translator inputs disagree, the command reports the conflict for that key.

Each stdout line is a JSON object. `analysis` counts the discovered keys and completed pairs. `cache` identifies the shader chain. `translation` reports cumulative totals after each batch, and `shader_error` identifies individual failures. `finished` includes the elapsed time. `prepared` counts published modules and `reused` counts existing validated modules whose input and output hashes match. A restart can reuse the completed entries. Use a fresh cache directory when the shader chain changes.

The exit code is `0` for a completed run, `2` for a completed run with individual failures, `1` for setup or cache errors, and `130` for an interruption. This developer command supports captures that already exist. The renderer still translates misses as it encounters them. Vulkan pipeline prewarm uses the renderer's recorded pipeline manifest and the device's pipeline cache compatibility fields. [Vulkan pipeline cache format](https://docs.vulkan.org/refpages/latest/refpages/source/VkPipelineCacheHeaderVersionOne.html)

Mario Kart World Recomp shows how shader translation can be a visible setup stage. Hookshot and Donkey Kong Bananza Recomp reuse a shader translator in the runtime path. This prototype exposes setup progress while sharing the existing translation path. [Mario Kart World Recomp](https://github.com/adriadam10/mkw-recomp/blob/main/README.md) · [Hookshot](https://github.com/NotRexed/Hookshot/) · [Bananza devlog](https://github.com/Lucas-blip-png/dkb-pc-recomp/blob/bananza/docs/devlog.md)

## Windows setup step

`tools\release\setup-windows.ps1` can run the prewarm as its last step on capture folders that you supply. The step is optional. Without `-ShaderCaptures`, setup runs the same five steps as before and does not create or change a shader cache.

```text
powershell -ExecutionPolicy Bypass -File tools\release\setup-windows.ps1 -GameData D:\MyDump\Orbitals -ShaderCaptures "D:\My Captures\nvn2"
```

From a PowerShell prompt, pass an array to include captures from several sessions.

```powershell
& .\tools\release\setup-windows.ps1 -GameData D:\MyDump\Orbitals -ShaderCaptures @('D:\Captures\first', 'D:\Captures\second')
```

Use folders with `<key>.ctl` and `<key>.code` pairs that the runtime wrote, such as `Orbitals_nvn\cache\dumps` from earlier sessions. Paths may contain spaces. Setup checks each folder before the long build steps. Step 6 runs `tools\nxshader\nxs_live.py --offline` with the installed `toolchain\dotnet10\dotnet.exe` and the `spirv-val` and `spirv-opt` from `toolchain\vulkan-bin`. It writes to the cache the runtime opens by default, `<InstallDir>\Orbitals\Orbitals_nvn\cache`. It uses the same translator options as the runtime's live translator, with the default `xlate_bin` and `--facts` unset. A shader missing from the cache can still be translated during play. If `NXRT_SHADER_CACHE` is set, setup warns that the game will use a different cache.

The step publishes only modules that pass validation. It reuses existing verified entries and can refresh entries from the same chain that need validation or repair. The JSON progress lines are passed through to setup's standard output, mixed with setup's own text lines. To read them, parse each line that starts with `{`. The step counts as complete only if `nxs_live.py` exits with `0`, ends with `finished`, found at least one pair and has `failed` equal to `0`. Otherwise setup prints `SHADER PREWARM INCOMPLETE` with the reason, leaves the game folder ready and exits with code `3`. Possible reasons include no pairs found, individual `shader_error` failures (exit `2`), an interruption (`130`) and setup or cache errors (`1`). The runtime still translates cache misses on demand.

If `Orbitals_nvn\cache\vk\CHAIN` was written by a different translator build, the prewarm stops with `cache belongs to another shader chain` and preserves the published modules. A cache with a different `LAYOUT` is also rejected. When the live translator starts, it adopts its own chain and recompiles stale entries as they are requested. After that session, setup can prewarm using the new chain. Moving the old cache aside before running setup is also an option.

Supply archive-derived NVN2 pairs from the next section with `-ShaderCaptures` to use the same setup step on a fresh installation.

## Validation

Run `python -B -m unittest discover -s tests -p test_nxs_prewarm.py`. `python -B -m unittest discover -s tests -p test_setup_prewarm.py` checks that the setup step stays optional, uses the runtime's default cache and live translator options, and never reports an incomplete prewarm as complete. It reads the files as text and runs neither PowerShell nor the toolchain. Set `NXSHADER_TEST_DOTNET` to the .NET 10 executable to run the translator integration tests as well. The tests generate their own inputs and cover the cache from empty to warm, bytewise equality with live translation, rejected input and validation failures, recovery from a damaged published module, and a competing writer.

A Windows sample used 48 synthetic compute dumps with varied workgroup sizes and three workers. Across three empty-cache runs paired with three warm reruns, median tool times were 0.975 and 0.349 seconds, respectively. All 48 offline modules passed validation and matched live translation byte for byte. The warm runs reused all 48 modules. These times cover the command's CPU-side work.

## First v0.1.5 measurement on Windows

The setup step validated and published 694 real NVN2 capture pairs in 50.19 s. A second setup reused all 694 in 9.59 s. Setup with an empty capture folder returned `3` and retained the installation. Setup with the option omitted left its shader cache empty.

Two isolated installations used the identical v0.1.0 runtime, AOT module, copied QA save and scripted controller route. Each started with an empty Vulkan pipeline cache. The RTX 5070 Laptop GPU ran the 30 FPS reference mode. The table covers one launch per state and uses the runtime clock at each capture.

| Metric | Empty shader cache | Prewarmed shader cache |
| --- | ---: | ---: |
| Main menu reached | 55.29 s | 50.92 s |
| Repair the Ship split screen reached | 193.28 s | 126.61 s |
| Logged shader waits through split screen | 111 | 8 |
| Cumulative shader waits through split screen | 67.5 s | 2.6 s |
| Longest logged shader wait through split screen | 3.31 s | 0.59 s |
| Draws skipped for missing shaders in the last replay summary | 0 | 0 |

Both sessions exited normally. Both characters and both lit views were visible. At the corridor gate, mean luma was 46.6 versus 46.6 in the left view and 54.0 versus 53.8 in the right view. The respective correlations on the comparison grid were 1.000 and 0.999. The prewarmed run translated 18 additional modules during play. The first 77 present intervals from the corridor gate had p50/p95/p99 of 33.33/446.68/1,787.32 ms with the empty cache and 33.21/36.46/40.88 ms with prewarm. These are first-entry intervals, including shader stalls and scripted movement. They describe this short window on this device.

The local RomFS inventory contains the expected IoStore containers. Both `.utoc` headers match the IoStore signature and have a version byte of 8. The `Content` tree contained no loose files with the `.ushaderbytecode`, `.ushadercode` or `.bnsh` extensions. The next discovery step is to identify shader-library metadata inside the containers and verify its relationship to the NVN2 programs observed at runtime.

## IoStore shader inventory

`tools/nxshader/nxs_iostore.py` is a developer command. It counts the shader chunk IDs that IoStore TOCs list, can compare two capture folders, and can copy the shader chunks of one container into a new directory. It uses only the Python standard library and does not open any shader cache. Only `extract` writes, and only into the output directory you name.

```text
python -B tools/nxshader/nxs_iostore.py inventory <container>.utoc [...]
python -B tools/nxshader/nxs_iostore.py coverage <captures A> <captures B>
python -B tools/nxshader/nxs_iostore.py extract <container>.utoc <container>.ucas <new directory> [--max-bytes N]
python -B tools/nxshader/nxs_iostore.py payloads <new directory>
```

`inventory` and `coverage` write nothing. `inventory` reads the TOC header and chunk ID table in fixed-size blocks. It checks the magic, requires TOC version 8 and a header size from 28 bytes to 64 KiB, and confirms that the file holds all entries the header declares. Chunk type 8 is counted as `shader_code_library` and type 9 as `shader_code`. `coverage` counts `<key>.ctl` and `<key>.code` pairs with a 0xE0- or 0x880-byte control block and code shorter than 16 MiB. It compares content for keys in both folders. Full NVN2 validation is performed during offline prewarm. [Unreal Engine chunk types](https://dev.epicgames.com/documentation/unreal-engine/API/Runtime/Core/EIoChunkType)

Each stdout line is a JSON object with counts only. Containers and folders are identified by position (`container` 1, 2, … and `folder` `a` or `b`), never by path. Chunk IDs, shader keys and content hashes are not printed. The exit code is `0` when every input was read and `1` when any input was rejected. Rejected inputs are reported as `container_error` or `capture_error` with a reason.

The two local version-8 TOCs indexed 33,498 chunks in total. The global TOC had one other chunk. The content TOC had two shader libraries and 2,718 shader-code chunks. `python -B -m unittest discover -s tests -p test_nxs_iostore.py` tests all four commands with synthetic containers.

### Shader chunk extraction

`extract` reads one version 8 TOC from start to end in bounded pieces. It reads the header, chunk IDs, offsets and lengths, skips the perfect hash tables, and reads only the compression block entries used by type 8 and 9 chunks. It rejects these inputs as `unsupported`: an encrypted container, more than one partition, a block entry other than 12 bytes, a shader block that uses a compression method (such as Oodle), and blocks that are not stored in increasing `.ucas` order. Blocks of other chunk types can use any method. A truncated TOC or `.ucas`, a chunk outside the block table, a method index outside the method table, or an uncompressed block whose sizes disagree is reported as `malformed`. Exceeding the entry, block, chunk count or chunk size limit, or `--max-bytes` (default 4 GiB of chunk data), is reported as `limit`. A chunk can start inside a block, span several blocks and share a block with its neighbours. The `.ucas` is read once, forward, with one block held in memory.

The output directory must not exist yet. Files are written to a hidden sibling directory, which is renamed to the output only after every chunk was copied. On any error, the sibling directory is removed and nothing is published. Files are named by kind and ordinal in TOC order: `library/000001.bin` and `code/000001.bin`. Neither the input paths nor chunk contents determine the names. `report.json` holds the aggregate report also printed as the `extracted` line: header fields, counts and bytes per kind, empty, multi-block and partial-block chunks, and blocks read and reused. `manifest.json` lists, for each file, its TOC entry, chunk ID, size and SHA-256. These per-file values stay in the output directory and are never printed.

`payloads` re-hashes every file the manifest lists and reports `verified`, `mismatched` and `missing` counts. It accepts only manifest file names in the `library/` or `code/` form, with no other paths. Each library chunk of up to 32 MiB is parsed as an IoStore shader code archive: a `uint32` version from 1 to 16, then int32-counted arrays of shader map hashes, shader hashes, group chunk IDs, shader map entries, shader entries, group entries (index offset, shader count, uncompressed and compressed size) and shader indices. A `library` line reports `valid` with counts and group byte totals only when the counts pair up, every index and range is inside its table, every group ID is a shader code ID and the data ends with the last array. Otherwise, it reports `invalid` with a reason. `groups_raw` counts groups with equal compressed and uncompressed sizes. `groups_compressed` counts smaller compressed sizes, and the command does not identify their codec. The `payloads` line matches group IDs to extracted code chunks and their stored sizes. The exit code is `1` when a file is missing or changed or the manifest is invalid. An invalid library layout is reported but does not fail the run. The command does not decompress groups, interpret shader bytes, or pass anything to `nxs_live.py`.

### NVN2 pairs from shader groups

`tools/nxshader/nxs_ue_nv2.py` turns an extraction into `<key>.ctl` and `<key>.code` pairs for `nxs_live.py --offline --dump <new directory>`. Pass the path to your installed Oodle shared library.

```text
python -B tools/nxshader/nxs_ue_nv2.py <extraction> <new directory> --oodle <Oodle library> [--keys FILE] [--max-bytes N]
```

The converter verifies each library and code chunk against the extraction manifest. Version 1 archives use seven arrays with strides 20, 20, 12, 8, 8, 16 and 4. Each shader entry is a `uint64` that stores the frequency in bits 0..3, its group in bits 4..33 and its decoded group offset from bit 34. The converter checks group ownership and bounds, then uses the sorted distinct offsets to split each group into records. It matches groups to code chunks by ID and stored length. For compressed groups, `OodleLZ_Decompress` must return the exact decoded length. The converter checks both the 64 MiB limit per group and the `--max-bytes` limit for the run.

In a record, each NVN2 marker `34 12 76 98 C9 00 00 00` starts a candidate control. The `uint32` at +0x30 gives the declared control size (0xE0..0x880 accepted, with observed sizes 224..424), and the word at +0x44 gives the code length. The code ends 4 bytes before the control, so it starts at `control - 4 - code length`. A byte comparison of 1,131 matched records found this layout in all of them, with variable binding metadata before the code and 22 bytes after the declared control. A candidate is valid when its control and code lie inside the record, `nxs_live.verify_nvn2_dump` accepts the first 0xE0 control bytes and the code under the runtime key (SHA-256 with the control size field zeroed), and `nxs_live.stage_of` names a stage. Records with no valid candidate or more than one are rejected. Records with one key are counted as duplicates when their code and their controls, with the size field zeroed, agree. Otherwise the key is `conflicting` and is not published.

`--keys` selects runtime keys from a local file with one 16-digit key per line and optional `#` comments. The tool writes pairs and `report.json` into a temporary sibling before renaming it to a new output directory. Stdout reports aggregate counts of verified groups, valid and rejected records, stages, unique keys, duplicates, conflicts and selected pairs. Exit code `0` means the output was published, `1` means an input was rejected, and `130` means the run was interrupted.

The local content container holds two version 1 libraries with 2,718 groups and 40,375 shader records. All groups decoded successfully through the installed local Oodle library. The converter found 40,370 structurally valid records and 23,144 distinct keys with no conflicts. Five records were rejected by their control size. All 720 keys selected for the co-op route were present. The offline translator prepared all 720 archive-derived modules in 62.38 seconds and validated them with SPIRV-Tools. `python -B -m unittest discover -s tests -p test_nxs_ue_nv2.py` tests the conversion with synthetic archives and an injected decoder in place of Oodle. [Unreal Engine IoStore shader archives](https://dev.epicgames.com/documentation/en-us/unreal-engine/API/Runtime/RenderCore/FIoStoreShaderCodeArchive)

## Additional capture coverage in Windows co-op

The original session had 694 complete pairs. The follow-up session recorded 18 distinct additional pairs. Passing both capture folders to the offline translator prepared and validated all 712 modules in a fresh cache in 53.58 seconds.

Two isolated installations used the same Windows executable, AOT DLL, pipeline cache seed, save, input route and experimental 60 FPS setting. The reference cache used the 694 corresponding modules from the same translation batch. The extended cache contained all 712. Each installation was run once down the Repair the Ship route, through the split-screen HUD gate.

| Through the co-op HUD gate | 694 prewarmed | 712 prewarmed |
| --- | ---: | ---: |
| Logged shader misses | 22 | 5 |
| Shader wait events | 9 | 3 |
| Sum of logged shader waits | 3.47 s | 0.96 s |
| Longest wait | 0.50 s | 0.36 s |

Both runs reached the gate and continued playing after opening and closing PC Settings. The gate can match while the camera transition is still settling. These runs measure shader stalls on PC. A fidelity comparison needs an aligned capture from Switch 2.

## Fresh Windows installs with archive prewarm

The two test directories used the same Windows Vulkan executable, AOT DLL, copied save and scripted input. Both started with an empty Vulkan pipeline cache. One shader cache was empty and the other contained 720 validated SPIR-V modules built entirely from IoStore. The script waited for the character-select screen to disappear before advancing and played the opening movies in both runs. These are single runs on the RTX 5070 Laptop.

| From launch to the co-op HUD | Empty shader cache | Archive prewarm |
| --- | ---: | ---: |
| Main menu reached | 55.55 s | 49.73 s |
| Repair the Ship split screen reached | 445.05 s | 365.58 s |
| Distinct shader cache misses | 633 | 0 |
| Logged shader waits | 33 | 0 |
| Sum of logged shader waits | 36.17 s | 0 s |
| Longest logged shader wait | 3.73 s | 0 s |

Both runs showed two lit views and exited normally. Through the 12-second settled windows, the average frame rates were 51.14 and 50.95 FPS. Luma correlations across the two views were 0.999 and 0.997 at the start of those windows. The renderer reported zero draws skipped for missing shaders in the last replay summaries. The full archive contained all 633 keys missed by the cold run. The five beyond the 720-key seed matched the five misses from the earlier archive-prewarm trial. All five translated and passed SPIR-V validation in a separate empty cache. The tested route can exercise different shader subsets across runs.

The shader wait total measures time spent in explicit waits. The full time to the HUD includes the opening movies and other scene transitions. The test harness failed to close the prewarmed process automatically and returned an error after its final capture. The window then closed normally, and the frame-rate result was recovered from the saved present timestamps.

## Full archive translation on Windows

The offline translator processed all 23,144 distinct archive-derived pairs in three disjoint empty caches. It translated, validated and published 23,134 SPIR-V modules with their reflection files. Ten inputs failed in the translator, seven at an unsupported form of Ampere opcode `0x925` and three at the unimplemented opcode `0x3A9`. The output contains one module and one reflection for each of the 23,134 successful keys. The five library records rejected during NVN2 extraction are outside these totals. Validation covers SPIR-V and cache publication for the full archive. Gameplay coverage is limited to the co-op route above.

## Shader preparation in the launcher (v0.1.5)

**Prepare shaders** in the launcher's Game files panel translates every shader of the installed game before the first session, from the
player's own files. The launcher offers it after an installation and before the first Play; it can be stopped and resumed. The step runs
`tools/nxshader/nxs_prepare.py`:

1. **Extract** the shader code chunks of each IoStore container in the RomFS (`nxs_iostore.py extract`) into the launcher's work folder.
2. **Decode** the shader groups into NVN2 pairs (`nxs_ue_nv2.py`). The groups are Kraken-compressed. A pair is published only when the
   SHA-256 of its control and code gives the key the runtime computes for that shader.
3. **Translate** the pairs that have no current cache entry, split into disjoint shards that several `nxs_live.py --offline` processes
   translate at once. Every module is validated with SPIRV-Tools.
4. **Publish** the shards into the profile's shader cache under the translator chain id. Entries of another chain are removed first,
   because a new translator, front or edit version makes them stale. The runtime's own captures (`dumps/`) are kept. The `final/` stage
   is removed and `xlate/` stays, so `nxs_reedit.py` can apply a new edit version without translating again.

Steps 1 and 2 are kept while their inputs (container sizes and times, decoder hash) are unchanged. Shard caches keep what they
translated, so a rerun after an interruption does only the rest. The cache's `PREPARED` file records the last summary: chain,
translator, counts and time. The launcher shows it.

### The decoder

The launcher builds the decoder on the player's PC with `tools/nxshader/nxs_kraken.py`. It downloads `kraken.cpp` of
[ooz](https://github.com/powzix/ooz) by Powzix (GPL-3.0-or-later) at a pinned commit, checks its SHA-256, keeps only its decoder part,
and compiles it with `tools/nxshader/kraken/ooz_compat.h` (in place of the Windows-only `stdafx.h`) and `kraken_shim.cpp`, which exposes
`OodleLZ_Decompress`'s calling convention. The compiler is MinGW g++ on Windows and g++ or clang++ on Linux. LZNA and BitKnit are left
out because their ooz files carry no license notice, and Orbitals' archives use neither. This project ships no ooz binary and no Oodle
library. The decoded game data and the built decoder stay on the player's PC.

Checks on the RTX 5070 Laptop installation:

- All 2,718 groups decoded to their exact declared sizes (433.8 MB), with no decode failure or size mismatch.
- 40,370 valid records gave 23,144 distinct keys, with no conflict. This is the same count the converter found with a licensed Oodle
  library.
- The 997 shaders the runtime captured in Windows co-op and the 74 captured on the Steam Deck are all among them, and their code is byte
  for byte the captured code.
- The Windows (MinGW) and Linux (clang, run on the Steam Deck) decoders produce identical pairs. A digest over all 46,288 files matches.
  Decoding takes 55 s on Windows and 4.3 s on the Deck. The difference is mostly antivirus file scanning on Windows.

### Translation time and size

One `nxs_live.py --offline` process translated about 3.7 shaders per second. The Python edit passes and reflection run in threads that
share one interpreter lock, and the .NET translator is about a sixth of the time. Eight shard processes translated and validated
23,131 of 23,144 shaders in 847 s. A resumed run that finds everything current takes 92 s, most of it to re-check the decoding.

The prepared cache takes 3.7 GB: 2.7 GB of modules, 151 MB of reflection and 1 GB of translator output. The modules are the translator's
unoptimised SPIR-V, about 112 KB each.

Thirteen shaders fail:

- Ten fail in the translator: Ampere `0x925` form 3 outside a covered pixel's read, and the unimplemented `0x3A9`.
- Three are compute shaders whose shared-memory (Workgroup) array reused a buffer array type with its `ArrayStride`. Current SPIRV-Tools
  rejects that (VUID-StandaloneSpirv-None-10684). The `wg_layout` edit gives such variables their own undecorated type. After that edit, `nxs_reedit.py` moved the 23,131 published entries to the new chain without translating them again, in 814 s on one process (`--workers`, default half the logical processors up to 8, splits the entries between processes: a pass over the whole cache with nothing to redo took 164 s on one process and 39 s on eight). A rerun of the preparation then translated the three shaders in 104 s. Validated modules: 23,134 of 23,144.

Through the launcher (`launcher/core.py` `prepare_shaders`), on an installed build with a new profile, the whole step took 863 s: the decoder download, check and build, extraction, decoding and the translation of 23,134 shaders, with 10 failures in the translator.

### First launch: empty cache against prepared shaders

Both installations used the same Windows Vulkan runtime, AOT DLL and copied save, with an empty Vulkan pipeline cache. The route was the
title, menu and co-op character selection with the opening films skipped, then the owner's recorded route from the colony corridor to
the space scene around the ship, replayed on the game clock (`SWR_INPUT_CLOCK=game`). One run each, RTX 5070 Laptop.

| First launch | Empty shader cache | Prepared shaders |
| --- | ---: | ---: |
| Shader cache misses | 720 | 0 |
| Translation waits | 159, 94.9 s in all | 0 |
| Frames over 500 ms | 72 | 5 |
| Frames over 100 ms | 138 | 30 |
| 99th percentile frame time | 275 ms | 39 ms |
| Longest frame | 5.1 s | 1.9 s |
| Co-op corridor reached | 197 s | 128 s |
| Last 60 s (space route): longest frame | 1.9 s | 80 ms |
| Vulkan pipelines built in the session | 614, worst 201 ms | 599, worst 14 ms |

### What the preparation does not cover: Vulkan pipelines

A translated module is not a pipeline. The driver compiles a graphics pipeline the first time a draw needs a combination of shaders,
vertex layout, blend and target formats. The runtime keeps pipelines in its pipeline cache (`NXRT_VK_CACHE_DIR`) and prewarms the
ones its lists know at later starts.

In the prepared first launch, 599 pipelines were built for 1.5 s in all. On a few frames the builds added 100 to 170 ms, mostly behind
loading screens. The other remaining long frames were the first frames after start and the 1.9 s level load after character selection.
That load is CPU work: it spent 10 ms on pipelines and 10 ms on GPU waits.

### Pipeline seed for the first session

`tools/nxshader/pipeline_seeds/<main build id>.tsv` lists pipeline states recorded in earlier sessions: shader keys and fixed-function
state, with no shader code. The launcher passes the installed build's list as `NXRT_VK_PIPELINE_SEED`. The runtime's two prewarm threads
then build those pipelines while the game boots.

The v0.1.5 seed has 853 pipelines from Windows sessions. Those sessions covered the menus, the corridor, the cockpit and the space
scene. The two runs below were left out of it. Both used prepared shaders and an empty pipeline cache, on the same recorded route.

| First launch, prepared shaders | Without seed | With seed |
| --- | ---: | ---: |
| Pipelines built at first use | 599 (1.75 s) | 0 |
| Slow frames with pipeline builds | 45 | 0 |
| Frames over 100 ms | 29 | 8 |
| 99th percentile frame time | 43.2 ms | 35.7 ms |
| Last 60 s: longest frame | 116 ms | 84 ms |

The prewarm built all 853 listed pipelines in 4.2 s of creation on its two threads, and finished 12 s after start. The remaining long
frames are the first frames and the level load after character selection. Both are CPU work. A scene that the seed does not cover still
builds its pipelines at first use. Later sessions prewarm everything they recorded.

## Shader preparation on Linux and the Steam Deck

On Linux, `tools/nxshader/nxs_deps.py` installs into the launcher's private folder (`tools/shader-deps`) what preparation needs. It
needs no administrator rights and changes nothing on the system:

- **.NET runtime 10.0.15 for linux-x64** from Microsoft, checked against the SHA-512 Microsoft publishes.
- **SPIRV-Tools 2026.4** from conda-forge (linux-64), checked by SHA-256. It needs glibc 2.17 or later and GCC 15's libstdc++.
- **Zig 0.15.2**, checked by SHA-256. It comes from the Zig project's wheel on PyPI, with ziglang.org's tarball as fallback. Its bundled
  clang builds the archive decoder, because SteamOS has no compiler.

Each download is checked before it is unpacked and kept for resuming. A later run is offline. `--offline` reports a missing component
instead of downloading it. The launcher runs this before the decoder build on Linux.

Tests on a Steam Deck OLED (SteamOS 3.8, glibc 2.41), on a clean folder:

- **Setup:** the three components took 32 s. ziglang.org served this Deck at about 110 KB/s, so the wheel is tried first.
- **Decoder:** Zig built it in 20 s.
- **Preparation:** 23,134 of 23,144 shaders translated and validated in 1,375 s on 4 processes. The cache is 3.6 GB, with the same chain
  as on Windows.
- **The game on that cache:** the scripted co-op route ran with no missing shader and no GPU reset.
- **Pipeline seed:** the prewarm built the 853 seeded pipelines in 1.2 s, done 3.5 s after start.

Frame rates on the Deck vary from run to run with the GPU clock (920 to 1,110 MHz under the 15 W limit):

| Steam Deck, co-op 230-320 s | Runs | FPS |
| --- | ---: | --- |
| `stable` build | 1 | 15.8 |
| v0.1.5, shader cache copied from Windows | 3 | 17.8, 17.6, 16.6 |
| v0.1.5, shader cache prepared on the Deck (seed in 2 runs) | 3 | 15.9, 18.4, 18.4 |
