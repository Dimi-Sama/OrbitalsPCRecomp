# Orbitals PC Recomp, a work based on SwitchRecomp by MZ Labs. GNU AGPL v3.0 with the additional terms of NOTICE.txt (LICENSE.txt).
"""Graphics settings that reach the game: presets and what each one changes at launch.

Only settings measured to change the rendering are offered (GRAPHICS_SETTINGS.md). The settings include the game's TV and handheld
profiles and a fixed scene resolution using Unreal's secondary screen percentage.
Unreal's scalability groups (sg.*) reach the game too, through its user config layer, but every level replaces the Switch 2 device
profile's tuning: darker picture, and slower on the Intel GPU (3.7 vs 4.0 FPS). Console variables put in the user layer's
Scalability.ini sections do apply (r.MipMapLODBias visibly did) without that change of look, but none of the quality ones measured
(shadows, ambient occlusion, bloom, depth of field, motion blur, SSR, refraction, volumetric fog, subsurface) changed the GPU work or
the frame rate (Intel UHD 4.0 vs 4.0 FPS): none is offered.
"""

ORIGINAL = "Original"
GUS = "Orbitals/Saved/Config/Switch2/GameUserSettings.ini"
ENGINE = "Orbitals/Saved/Config/Switch2/Engine.ini"
RENDER_SCALE = {"960x540": "50", "1280x720": "66.6667", "1600x900": "83.3333"}
RENDER_MODES = ("TV", "Portable", *RENDER_SCALE)

# individual options beyond the 3D resolution: none validated in v0.1 (kept as a table so a measured one can be added with its preset values)
OPTIONS = {}

PRESET_ORDER = ("High", "Low", "Performance", "Custom")
PRESET_MODE = {"High": "TV", "Low": "Portable", "Performance": "1280x720"}   # the game's 3D resolution each preset uses; Custom: the profile's own "mode"
PRESETS = {"High": {}, "Low": {}, "Performance": {}}
PRESET_NOTES = {
    "High": "High: the game's own rendering, 3D at 1920×1080 (2 × 960×1080 in co-op). Recommended.",
    "Low": "Low: 3D at 1600×900 (2 × 800×900 in co-op), the game's own handheld resolution; HUD and final picture stay 1080p. "
           "Helps slower GPUs; no change on a GPU that is already fast enough.",
    "Performance": "Performance: 3D at 1280×720 (2 × 640×720 in co-op); HUD and final picture stay at the output size. "
                   "Same effects as High, fewer pixels: faster on handhelds and smaller GPUs. The picture is softer than High.",
    "Custom": "Custom: choose the 3D resolution yourself below.",
}

# frame pacing (the launcher's "fps" setting): Orbitals.ini ue_fps 0 / 30 / 60. 120 and unlimited are not offered: the 60 mode already
# presents every vblank and the co-op measured here stays below 60 (GRAPHICS_SETTINGS.md)
FPS_MODES = {"30 (reference)": 0, "30 (async replay)": 30, "60 (experimental)": 60}
FPS_CHOICES = tuple(FPS_MODES)
FPS_WARNINGS = {
    "30 (reference)": "30 FPS: the game's own pace. Recommended.",
    "30 (async replay)": "30 FPS with Vulkan replay on a separate thread. It can reduce cinematic slowdowns on busy CPUs. "
                         "Timing is experimental.",
    "60 (experimental)": "60 FPS EXPERIMENTAL: real frames at the game's normal speed. Co-op may stay below 60, and stutter or "
                         "timing glitches remain possible.",
}
MODE_NOTES = {
    "TV": "TV 3D resolution: the game renders its 3D at 1920×1080 (2 × 960×1080 in co-op).",
    "Portable": "Handheld 3D resolution: the game renders its 3D at 1600×900 (2 × 800×900 in co-op), then the picture at 1080p.",
    **{size: f"{size.replace('x', '×')} scene resolution with the TV profile. The game composites the HUD at 1080p." for size in RENDER_SCALE},
}
# TV resolution (the launcher's "tv_resolution" setting): Orbitals.ini display_resolution, the TV size the game is told about in TV mode.
# The game then makes its picture (HUD, text, final image) at that size instead of the console's 1920x1080; the 3D keeps its own size.
TV_RESOLUTIONS = {"1080p (console)": 0, "1440p": 1440, "1620p": 1620, "1800p": 1800, "2160p (4K)": 2160}
TV_CHOICES = tuple(TV_RESOLUTIONS)
TV_NOTE = ("The size of the game's own picture in TV mode: menus, text and the final image are made at this size. The console uses 1080p. "
           "Higher costs GPU time: on a 4K monitor 1800p is a good middle.")
# Output sizes are the physical window/swapchain dimensions.
OUTPUT_SIZES = ("960x540", "1280x720", "1280x800", "1600x900", "1920x1080", "2560x1440", "3840x2160")


def output_sizes(native=None):
    """The output sizes to offer: the usual ones up to the monitor's, and the monitor's own (native) first when it is known."""
    sizes = list(OUTPUT_SIZES)
    if native:
        w, h = native
        sizes = [s for s in sizes if int(s.split("x")[0]) <= w and int(s.split("x")[1]) <= h] or sizes
        own = f"{w}x{h}"
        sizes = [own] + [s for s in sizes if s != own]
    return tuple(sizes)


def option_values(name):
    return tuple(OPTIONS[name][1])


def resolve(settings):
    """The option values a profile's graphics settings stand for: a preset's, or the custom ones."""
    preset = settings.get("preset", "High")
    if preset not in PRESET_ORDER:
        raise ValueError(f"unknown preset {preset!r}")
    chosen = {name: ORIGINAL for name in OPTIONS}
    if preset == "Custom":
        for name in OPTIONS:
            value = settings.get(name, ORIGINAL)
            if value not in OPTIONS[name][1]:
                raise ValueError(f"{name}: {value!r} is not one of {option_values(name)}")
            chosen[name] = value
    else:
        chosen |= PRESETS[preset]
    return chosen


def validate(settings):
    resolve(settings)


def effective_mode(preset, mode):
    """The preset's scene resolution, or the profile's own with Custom."""
    return PRESET_MODE.get(preset, mode)


def launch_changes(settings):
    """(scalability groups, Orbitals.ini keys, overlay files {relative path: text}) of a session"""
    sg, ini = {}, {}
    for name, value in resolve(settings).items():
        effect = OPTIONS[name][1][value]
        sg |= effect.get("sg", {})
        ini |= effect.get("ini", {})
    files = {}
    if sg:
        files[GUS] = ("; Written by the Orbitals PC Recomp launcher for this session only (launcher/graphics.py).\n[ScalabilityGroups]\n"
                      + "".join(f"{k}={v}\n" for k, v in sorted(sg.items())))
    mode = effective_mode(settings.get("preset", "High"), settings.get("mode", "Portable"))
    if mode in RENDER_SCALE:
        files[ENGINE] = f"[SystemSettings]\nr.SecondaryScreenPercentage.GameViewport={RENDER_SCALE[mode]}\n"
    return sg, ini, files
