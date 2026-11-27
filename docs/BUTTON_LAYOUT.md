# Button layouts

Orbitals.ini supports two opt-in settings (restart after changing them):

```ini
button_layout=playstation
button_accept_bottom=1
```

`button_layout` accepts `nintendo` (default), `xbox`, or `playstation`. Nintendo
installs no button hooks and creates no overlay. `button_accept_bottom` defaults
to `0`; with Xbox or PlayStation, `1` uses bottom accept and right back without
moving jump from the bottom button. Other runtime defaults are unchanged.
Controller drawings on the join screen remain Nintendo; this changes prompts,
not controller artwork. Keyboard prompts are preserved.

## Build and integration

Rebuild the runtime **and regenerate the game code module** with this checkout's
`switchrecomp.py`. A runtime-only update cannot redirect the game's direct calls.
The two prompt targets (main+0x40c5020 and main+0x40c5ce0) use `CALLDYN`, including
tail calls; the module exports `swr_dynamic_calls`. An older module without that
capability logs that prompts were not applied and need regeneration. Static code
modules without a dynamically loaded capability export also fail closed.
Hooks require the supported Orbitals build ID and checked instruction words.

The dedicated `runtime/orbitals_buttons.c` API is independent of gyro. Its private
helper header is compiled by the real-C regression fixtures. The action wrapper
collects bounded, validated icon pairs before calling the game and subsequently
touches only the caller's output slot. Missing, NULL, ambiguous or malformed
replacements retain the original icon. The separate per-key lookup falls back to
the original platform when the selected layout has no usable texture.

Bottom acceptance swaps the checked EKeys accept/back copies after their static
initializer; it does not swap physical face-button input. Enhanced Input redirects
are made identity mappings before the original virtual call, excluding destructors,
with no object reads after that call. A generated Game.ini overlay supplies the PC
UI contexts only when bottom acceptance and a non-Nintendo layout are both enabled.
Selecting Nintendo on restart stops applying that overlay.

**Limitation:** the redirect wrappers cover shared UObject virtual functions, so
unrelated objects also pay the receiver check. This is the original implementation's
broad hook, not a verified narrow Enhanced Input consumer hook. The observed paths
worked, but that does not prove every future context is covered.

## Evidence and limits

Extracted from `d393b41` on `night/orbitals-20261126`. The original implementation's
`docs/dev4k/BUTTON_LAYOUT.md` records live PlayStation/Xbox prompts, bottom accept,
right back, both players' pause/settings flows, seat exits and bottom-button jumps.
That source also records the unsuccessful controller-artwork experiment; its hook
is excluded here. Historical screenshots and benchmark logs are not distributed
with this extraction.

The source's `docs/dev4k/LAYOUT_BENCH.md` records eight alternating Nintendo/PlayStation
co-op runs: mean FPS differences of approximately +0.14% at 1800p and -0.21% at 2160p,
within repeated-run variation. These are historical results for the original full
runtime, not performance measurements of this branch or evidence of stable 60 FPS.

**This extracted branch has not been live-tested.** Asset-free tests exercise real C
wrappers and generated A64 caller fixtures, including fallback, malformed maps,
object retirement, preserved registers/output bytes and bounded trace logging.
Run `python3 -m unittest discover -s tests -p test_button_layout.py -v`.
Set `ORBITALS_MAIN_BIN` to your own main.bin to additionally verify instruction
signatures against the game image; otherwise that test reports a skip. No game
assets are included. `SWR_ICON_TRACE=1` enables bounded prompt diagnostics.
