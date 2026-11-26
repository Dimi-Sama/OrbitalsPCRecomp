# Gyro aiming

Optional direct camera input for Orbitals, disabled by default. Windows SDL3
sensor-capable gamepads supply motion to their own local player (two slots).
XInput has no sensors; Linux/headless builds compile the camera logic but do not
acquire motion. Use a legally obtained copy of the game; tests need no game assets.

## Settings

Set these keys in the game's INI and restart:

| Key | Default | Values / meaning |
| --- | --- | --- |
| `gyro` | `off` | `off`, `always`, `aim` (left trigger held) |
| `gyro_delivery` | `samples` | Per-sample angular integrals; `latest` holds velocity on the camera clock |
| `gyro_sensitivity_x`, `gyro_sensitivity_y` | `1.5` | Camera degrees per controller degree, greater than 0 through 20 |
| `gyro_tightening` | `3` | Soften turns below this speed in degrees/s; 0 disables, maximum 30 |
| `gyro_button` | `touchpad` | `touchpad`, `mute`, `l3`, `r3`, `paddle_left`, `paddle_right`, `none` |
| `gyro_button_mode` | `pause` | Hold to pause, or `toggle` on each press |
| `gyro_invert` | `0` | 1 horizontal, 2 vertical, 3 both |
| `gyro_calibrate` | `0` | 1 requests two seconds of stillness, stores bias, then resets |
| `gyro_log` | `0` | 1 logs gate changes and per-pad bias/drift diagnostics |
| `gyro_test` | `0` | 1 arms the synthetic camera-integral diagnostic |
| `gyro_test_delay` | `0` | Additional seconds after arming before a synthetic test (0–600) |

Holding the gyro button still for three seconds also calibrates. Automatic
calibration uses a 1.5-second still window. Bias is keyed by controller vendor and
product, not serial number. Calibration lives in `gyro_calibration.txt` beside
the resolved `save` directory, never inside it. Profile-like save links retain
calibration across sessions and isolate profiles; unresolvable or unexpectedly
named targets store nothing. Concurrent processes sharing a profile are not a
supported calibration-writing workflow.

## Boundaries

Hooks target main build ID `0f8ef52cf4eee37628f366a539d5d6ad` and checked camera
entry instructions. Other builds receive no hooks. Input goes through the game's
AddYawInput/AddPitchInput and UpdateRotation, preserving normal stick input.
Checked controller/actor classes, ownership, view target, cinematic state and
shared world pause gate both players independently. Focus loss and PC panels also
suppress motion. Invalid or unreadable metadata fails closed.

`samples` integrates sensor timestamps. `latest` uses the newest calibrated rate,
expires it after 50 ms and caps each camera step at 50 ms. Gaps over 100 ms discard
waiting motion; gates, toggles and device replacement invalidate held velocity.
This cannot reconstruct missing reports and may continue a previous rate until
expiry. Once sensor events have worked, silence does not refresh cached data.
There is no extra frontend polling loop. Synthetic diagnostics always use sample
integrals, even with `latest` configured.

## Validation and human trial

The source implementation was tried with DualSense Edge and regular DualSense
Bluetooth. The owner accepted Edge motion with `latest`, sensitivity 1.0 on both
axes and touchpad toggle; subsequently accepted a regular DualSense trial with
configured tightening 1.5. That last trial's session INI was not inspected after
restart. These are optional subjective tuning reports, not defaults, latency
measurements, or live validation of this extracted upstream tree. Bridge software
compatibility, other game builds and broader gameplay remain unverified.

Asset-free checks:

```sh
python3 tests/test_gyro_gate.py
python3 tests/test_gyro_calibration.py
python3 -m unittest discover -s tests -p 'test_*.py'
python3 switchrecomp.py --build-runtime --target win64 --backend win32 --cc x86_64-w64-mingw32-gcc
```

The real-C harness covers per-player routing, allowed/refused gameplay and
malformed types, shared pause, no resume jump, delivery boundaries, synthetic
success/failure/inconclusive results and mutations of key rules. Storage tests
cover standalone and linked saves, profile/model isolation, save replacement,
failed writes and clock discontinuities. They simulate engine state and do not
prove physical sensor acquisition or in-game feel.

Extraction-host verification: 63 Python tests completed with two upstream skips
requiring .NET 10/SPIRV-Tools; the gyro gate and eight calibration tests passed.
MinGW syntax checks and a Windows PE link of the real gyro C harness passed;
the PE was not executed. Audio and recording-time C tests passed with sanitizers.
Full Windows desktop linking lacks `g_swr_presents` without the optional NVN
archive; Linux headless linking fails at the existing `fmodl` compatibility shim.
Both failures reproduce on the upstream base. Windows headless also lacks the
existing `backend_game_settings_show` implementation. Renderer feedback tests
could not compile without EGL headers. No full game boot is claimed here.

Before accepting a build, use a copied save: verify title/menu/cinematic and shared
pause rejection, each co-op camera independently, on-foot and ship aiming, axis
direction, focus loss, toggle/hold, reconnect and no resume jump. Let each pad lie
still to check drift, then assess slow turns and stops. For diagnostics, enable
`gyro_test=1` with enough `gyro_test_delay` to pass loading: it waits for three
unbroken seconds of an open gate. A break produces INCONCLUSIVE, never acceptance;
require a measured PASS (within 2%) for each tested player plus physical trials.
Disable diagnostics afterwards.

Rollback: set `gyro_delivery=samples` to undo latest delivery, restore sensitivity
1.5/tightening 3 for defaults, or set `gyro=off` and diagnostics/calibration requests
to 0 to disable motion. Calibration is separate from saves; restoring the previous
runtime and INI does not require changing game saves.
