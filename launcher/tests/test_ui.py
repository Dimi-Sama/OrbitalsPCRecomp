# Orbitals PC Recomp, a work based on SwitchRecomp by MZ Labs. GNU AGPL v3.0 with the additional terms of NOTICE.txt (LICENSE.txt).
"""The launcher window itself: every page is built once, with no game installed and with a fixture installation.

A page that raises while it is built (v0.1.5-preview.1: the home page's shader line passed justify twice) leaves the launcher closed
for the player; the core tests do not build any widget. Skipped where Tk has no display."""
import shutil
import tempfile
import time
import tkinter as tk
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from launcher import core, ui
from launcher.neo import TitleScreen
from launcher.ui import Launcher
from launcher.tests.test_launcher import build_fixture

PAGES = ("Home", "Profiles", "Graphics", "Controls", "Settings", "Support")


class LauncherWindowTest(unittest.TestCase):
    def setUp(self):
        try:
            self.tk = tk.Tk()
        except tk.TclError as error:
            self.skipTest(f"no display for Tk: {error}")
        self.tk.withdraw()
        self.root = Path(tempfile.mkdtemp(prefix="orbitals-ui-"))
        self.addCleanup(shutil.rmtree, self.root, ignore_errors=True)
        self.addCleanup(self.tk.destroy)
        # no network and no background work while the pages are built
        for name in ("check_update",):
            if hasattr(core, name):
                p = patch.object(core, name, return_value=None); p.start(); self.addCleanup(p.stop)

    def build(self, game=None):
        local = self.root / "local"
        local.mkdir(exist_ok=True)
        with core.setup_logging(local):
            app = Launcher(self.tk, local, game)
            for page in PAGES:
                with self.subTest(page=page, game=bool(game)):
                    app.show(page)
                    self.tk.update_idletasks()

    def test_every_page_builds_without_a_game(self):
        self.build()

    def test_every_page_builds_with_an_installation(self):
        native = self.root / "game"
        build_fixture(native)
        self.build(native)


    def window(self, size="1160x755", game=True):
        """A launcher with a fixture installation, shown, with no update check."""
        if game:
            game = self.root / "game"
            if not game.exists():
                build_fixture(game)
        local = self.root / "local"
        local.mkdir(exist_ok=True)
        for p in (patch.object(Launcher, "update_result", lambda *a, **k: None), patch.object(ui, "detect_installation", return_value=None)):
            p.start(); self.addCleanup(p.stop)
        logs = core.setup_logging(local)
        logs.__enter__(); self.addCleanup(logs.__exit__, None, None, None)
        app = Launcher(self.tk, local, game or None)
        self.tk.geometry(size)
        self.tk.deiconify()
        self.spin(0.1)
        return app

    def spin(self, seconds):
        end = time.monotonic() + seconds
        while time.monotonic() < end:
            self.tk.update()
            time.sleep(0.01)

    def title(self, app):
        return next(w for w in app.page.winfo_children() if isinstance(w, TitleScreen))

    def test_title_entries_are_enabled_again_after_any_job(self):
        app = self.window()
        done = []
        app.background("Copying…", lambda: time.sleep(0.2), done.append)
        self.spin(0.05)
        self.assertFalse(self.title(app).menu[0][3], "PLAY while a job runs")
        self.spin(0.8)
        self.assertTrue(done)
        self.assertTrue(self.title(app).menu[0][3], "PLAY after it")

    def test_controller_scan_neither_blocks_saving_nor_loops_on_errors(self):
        app = self.window()
        with patch.object(ui, "gamepad_inventory", side_effect=RuntimeError("unexpected")) as scan, \
                patch.object(ui.messagebox, "showerror") as dialog:
            app.show("Controls")
            self.assertIsNone(app.job)
            self.spin(0.6)
        self.assertEqual(scan.call_count, 1)
        dialog.assert_not_called()

    def test_every_page_can_be_seen_whole_at_the_minimum_size(self):
        app = self.window("880x650")
        with patch.object(ui, "gamepad_inventory", return_value=("XInput", [])):
            for page in PAGES[1:]:
                with self.subTest(page=page):
                    app.show(page); self.spin(0.15)
                    self.assertEqual(app.scroll.overflows(), bool(app.scroll.bar.winfo_ismapped()))
                    app.scroll.view.yview_moveto(1.0); self.tk.update()
                    self.assertGreaterEqual(app.scroll.view.canvasy(app.scroll.view.winfo_height()), app.page.winfo_reqheight() - 20)

    def test_title_texts_stay_in_their_panels(self):
        app = self.window()
        app.profiles.rename("A profile name of 32 characters")
        for size in ("880x650", "1160x755", "1600x900"):
            self.tk.geometry(size)
            app.show("Home"); self.spin(0.2)
            screen = self.title(app)
            with self.subTest(size=size):
                for item in screen.find_all():
                    if screen.type(item) != "text":
                        continue
                    left, top, right, bottom = screen.bbox(item)
                    self.assertLessEqual(right, screen.w, screen.itemcget(item, "text"))
                    self.assertLessEqual(bottom, screen.h, screen.itemcget(item, "text"))
                    if left < screen.w * 0.4:
                        self.assertLessEqual(right, screen._split((top + bottom) / 2) + 2, screen.itemcget(item, "text"))

    def test_moving_the_mouse_repaints_nothing(self):
        app = self.window()
        screen = self.title(app)
        with patch.object(screen, "configure") as configure:   # any configure repaints a whole canvas
            for x in range(5, 60):
                screen._hover(SimpleNamespace(x=x, y=5))
        configure.assert_not_called()

    def test_title_screen_is_still_while_a_game_runs(self):
        app = self.window()
        screen = self.title(app)
        screen.moves = True
        with patch.object(screen, "focus_displayof", return_value=screen):
            self.assertTrue(screen._moving())
            app.process = object()
            self.assertFalse(screen._moving())
        app.process = None


class DemoScreenTest(unittest.TestCase):
    """Each long task's demo builds and draws frames (a Tk error in a frame would stop its animation)."""

    def test_every_demo_draws(self):
        try:
            root = tk.Tk()
        except tk.TclError as error:
            self.skipTest(f"no display for Tk: {error}")
        self.addCleanup(root.destroy)
        root.geometry("900x500")
        from launcher.demo import DemoScreen, style_for
        self.assertEqual([style_for(t) for t in ("RECOMPILING ORBITALS", "PREPARING SHADERS", "DOWNLOADING UPDATE")],
                         ["code", "shader", "stars"])
        for title in ("RECOMPILING ORBITALS", "PREPARING SHADERS", "DOWNLOADING UPDATE"):
            with self.subTest(title=title):
                demo = DemoScreen(root, title=title)
                demo.pack(fill="both", expand=True)
                demo.set_progress(0.5, "Step 2/5", "detail")
                root.update()
                demo._layout()
                for _ in range(3):
                    getattr(demo, "_frame_" + demo.style)()
                    demo._frame_common()
                    demo.t += 1
                demo.destroy()


if __name__ == "__main__":
    unittest.main()
