# Launcher controls and output resolution

Liftoff exposes these settings as rows in the scrollable Controls and Graphics pages.

Controls were adapted from `night/launcher-layout-selection` (`18ebfae`). Nintendo
and gyro Off remain the defaults, including profiles created before these settings.
Xbox and PlayStation select the prompt graphics and request bottom-button accept/back;
Nintendo clears both overrides, including a retired independent accept checkbox.

The candidate includes the button layout runtime and [gyro support](https://github.com/Dimi-Sama/OrbitalsPCRecomp/pull/12).
Gyro requires SDL and a controller with motion sensors. Update the installed runtime and module through Game Files.
Calibration is consumed after a successful process start with gyro enabled; keep the
controller still. A failed process start leaves the request pending.

Settings belong to each save profile. A launch writes an isolated session INI,
replaces only owned keys, preserves unknown settings, and leaves the installation's
INI untouched. Settings are locked during a game or background operation.

## TV output resolution

The TV resolution options include console 1080p, 1440p, 1620p, 1800p, 2160p and
the 2560×1080 and 3440×1440 ultrawide modes. The runtime applies the chosen
width and height to the FParse hook and the AM and VI display services.
This is the game's TV output/HUD resolution, separate from internal 3D resolution
and window size. Portable mode ignores it. Low forces Portable regardless of the
previous mode selection, so its TV output setting has no effect. Use a preset
whose effective mode is TV, or Custom with a TV rendering mode.

**Rebuild both runtime and game module.** The source hook changed `g_disp` only,
but `codegen.emit_function` emits direct C calls for known BL targets. The shared build-ID keyed
`DYNAMIC_CALLS` table routes the validated main build's `0x35d1740` and button prompt targets through
`CALLDYN`, for BL and external tail calls. Other builds retain direct calls.
The loader strips trailing zero bytes from NSO build IDs; dispatch matching uses
the first 16 bytes, tested through the real loader with a synthetic NSO.
The runtime requires the module capability export before installing the hook or
changing AM/VI dimensions. Old and statically linked modules without that export
retain console output. The runtime also validates build ID, text bounds, writable outputs and entry
signature, and preserves failed parses, abnormal returns and non-1080p results.

`python3 -B -m unittest discover -s tests -p test_display_resolution.py -v`
compiles a generated direct BL with the actual runtime hook and dispatch macro,
then executes it: original 1920×1080 becomes the requested output; negative cases
remain unchanged. This proves synthetic dispatch reachability, **not an observed
full-game 4K image**. Existing modules must be recompiled: a new runtime alone does
not rewrite their direct calls. A runtime bind log alone is not proof of execution.

Local checks: `xvfb-run -a python3 -B -m unittest discover -s launcher/tests`;
`python3 switchrecomp.py --build-runtime --target linux --backend headless --cc gcc`.
## Validation scope

The tests exercise the per-profile launcher settings and compiled dispatch hooks with
synthetic fixtures. For hardware coverage, use the validation record of the specific
release candidate under test.
