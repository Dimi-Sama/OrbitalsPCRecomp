# Orbitals PC Recomp, a work based on SwitchRecomp by MZ Labs. GNU AGPL v3.0 with the additional terms of NOTICE.txt (LICENSE.txt).
"""Pictures of every page of the launcher, with a stand-in installation and no network, to look at a change (not a test):

  python -B -m launcher.tests.shots OUT [--size 1160x755 --size 880x650] [--dpi 144]

Needs Pillow. On Windows it takes the window itself; elsewhere the screen where it is, so leave it in front."""
import argparse
import tempfile
import time
import tkinter as tk
from pathlib import Path
from unittest.mock import patch

from launcher import core, look, page_settings, ui
from launcher.tests.test_launcher import build_fixture


def picture(root, path):
    from PIL import ImageGrab
    end = time.monotonic() + 0.4
    while time.monotonic() < end:
        root.update(); time.sleep(0.01)
    if core.WINDOWS:
        import ctypes
        ImageGrab.grab(window=ctypes.windll.user32.GetAncestor(root.winfo_id(), 2)).save(path)
    else:
        x, y = root.winfo_rootx(), root.winfo_rooty()
        ImageGrab.grab(bbox=(x, y, x + root.winfo_width(), y + root.winfo_height())).save(path)


def cards(app):
    """The title screen's states: (name, what brings it there)."""
    update = {"latest": "v9.9.9", "newer": True, "url": "https://github.com/", "notes": "", "assets": {}}
    yield "shaders", lambda: None
    yield "update", lambda: app.show_update(update, None, True)
    yield "failed", lambda: app.fail("Recompiling Orbitals failed", "The installation failed (code 1). The details are in games/setup.log.",
                                     ("Try again", lambda: None), ("Open log", lambda: None))


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("out", type=Path)
    parser.add_argument("--size", action="append")
    parser.add_argument("--dpi", type=float, default=96)
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as folder, patch.object(ui.Launcher, "update_result", lambda *a, **k: None), \
            patch.object(ui, "detect_installation", return_value=None), patch.object(ui, "scale_to", lambda root: look.scale_to(root, args.dpi)), \
            patch.object(page_settings, "gamepad_inventory", return_value=("SDL3", [("A controller", True)])):
        game = Path(folder) / "game"
        build_fixture(game)
        for size in args.size or ("1160x755", "880x650"):
            for state, installed in (("game", game), ("new", None)):
                root = tk.Tk()
                local = Path(folder) / f"{state}-{size}"
                with core.setup_logging(local):
                    app = ui.Launcher(root, local, installed)
                    root.geometry(f"{size}+20+20"); root.update(); root.focus_force()
                    for name in ("Graphics", "Controls", "Settings", "Profiles", "Files", "Tools"):
                        app.show(name)
                        picture(root, args.out / f"{state}-{size}-{name}.png")
                    for name, bring in cards(app) if installed else (("setup", lambda: None),):
                        bring()
                        app.show("Home")
                        picture(root, args.out / f"{state}-{size}-Home-{name}.png")
                root.destroy()


if __name__ == "__main__":
    main()
