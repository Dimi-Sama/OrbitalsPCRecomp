# Launcher controls and output resolution

The upstream Tk launcher keeps its existing colors, surfaces, three-column fields,
header and tabs. Controls and Graphics scroll vertically when their rows exceed the
window. This is a desktop UI (minimum 880×650), not a phone layout. Do not import the
night branch's typography, navigation, assets or page redesign.

Controls were adapted from `night/launcher-layout-selection` (`18ebfae`). Nintendo
and gyro Off remain the defaults, including profiles created before these settings.
Xbox/PlayStation select both glyph layout and western bottom-button accept/back;
Nintendo clears both overrides, including a retired independent accept checkbox.

**Companion runtimes required:** the layout selectors require the separate button
layout runtime change. Gyro requires the gyro runtime (PR #12), SDL and a controller
with motion sensors. This launcher commit does not implement either runtime feature
or upgrade an installed runtime. Its Controls page states these dependencies.
Calibration is consumed after a successful process start with gyro enabled; keep the
controller still. A failed process start leaves the request pending.

Settings belong to each save profile. A launch writes an isolated session INI,
replaces only owned keys, preserves unknown settings, and leaves the installation's
INI untouched. Settings are locked during a game or background operation.

## TV output resolution

The second commit adapts `launcher-tvres` (`b5b1a75`) choices: console/0, 1440,
1620, 1800 and 2160. Runtime integration is extracted from `display-4k`
(`32348e0`): INI parsing, AM/VI display size and the Orbitals FParse resolution
hook. No environment-variable forwarding or Vulkan changes are included.
This is the game's TV output/HUD resolution, separate from internal 3D resolution
and window size. Portable mode ignores it; select a TV rendering mode to use it.

**Rebuild both runtime and game module.** The source hook changed `g_disp` only,
but `codegen.emit_function` emits direct C calls for known BL targets. The small
codegen exception routes only the validated main build's `0x35d1740` entry through
`CALLDYN`, for BL and external tail calls. Other builds retain direct calls.
The runtime also validates build ID, text bounds, writable outputs and entry
signature, and preserves failed parses, abnormal returns and non-1080p results.

`python3 -B -m unittest discover -s tests -p test_display_resolution.py -v`
compiles a generated direct BL with the actual runtime hook and dispatch macro,
then executes it: original 1920×1080 becomes the requested output; negative cases
remain unchanged. This proves synthetic dispatch reachability, **not an observed
full-game 4K image**. Existing modules must be recompiled: a new runtime alone does
not rewrite their direct calls. A runtime bind log alone is not proof of execution.

Local checks: `xvfb-run -a python3 -B -m unittest discover -s launcher/tests`;
`python3 switchrecomp.py --build-runtime --target linux --backend headless --cc gcc`.
The upstream fixture failures are recorded separately in the handoff evidence.

## Local verification limits

The full launcher gate ran 75 tests: 72 passed, two failed and one errored. The
same three failures occur on unmodified upstream `3bfcb3c` (59 tests):
`test_shader_preparation_relays_progress_and_records_the_summary`,
`test_shader_preparation_error_is_reported` (fixture lacks `nxshader/nxs_deps.py`),
and `test_command_is_copied` (Linux dependency command expectation).
All three compiled resolution tests pass.

Full runtime builds were attempted, but no distributable binary was produced:
- Linux headless: unresolved hidden `fmodl` from `glibc_compat.c`. Linking that
  unchanged upstream file in isolation reproduces the failure.
- Windows headless: unresolved `backend_game_settings_show` (the upstream settings
  widget hook references the desktop implementation).
- Windows win32: unresolved `g_swr_presents` in `backend_win32.c`; the optional NVN
  library is absent in this worktree. This build configuration remains unverified.

Tk screenshots were captured with Xvfb at 1160×800 and the supported minimum
880×650, including scrolled Save controls. Visual inspection was self-review only:
this task explicitly forbids children. No game, controller, installed PC or SSH
session was used. In-game resolution and companion runtime integration are NOT
OBSERVED. UI lint finds no supported frontend files in this Tk-only change.
