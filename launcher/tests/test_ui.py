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

from launcher import core, graphics, page_settings, ui
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
        with patch.object(page_settings, "gamepad_inventory", side_effect=RuntimeError("unexpected")) as scan, \
                patch.object(ui.messagebox, "showerror") as dialog:
            app.show("Controls")
            self.assertIsNone(app.job)
            app.keep(keyboard=2)
            self.spin(0.6)
        self.assertEqual(scan.call_count, 1)
        dialog.assert_not_called()
        self.assertEqual(app.profiles.settings["keyboard"], 2)

    def row(self, app, caption):
        return next(row for row in app.view.rows.items if row.caption == caption)

    def test_settings_are_kept_as_they_change(self):
        app = self.window()
        app.show("Settings")
        self.row(app, "Volume").move(-1)
        self.row(app, "Volume").move(-1)
        self.assertEqual(self.row(app, "Volume").value.cget("text"), "90 %")
        app.show("Graphics")   # another tab, before they are written
        self.assertEqual(app.profiles.settings["volume"], 90)
        self.row(app, "VSync").press()
        self.spin(0.5)
        self.assertFalse(app.profiles.settings["vsync"])
        self.assertEqual(core.Profiles(app.local).settings["volume"], 90)

    def test_a_preset_and_the_rows_under_it(self):
        app = self.window()
        app.show("Graphics")
        preset, resolution = self.row(app, "Preset"), self.row(app, "Internal 3D resolution")
        for name in graphics.PRESET_ORDER[:3]:
            preset.take(name)
            self.assertEqual(resolution.get(), graphics.PRESET_MODE[name])
        resolution.take("1600x900")
        self.assertEqual((preset.get(), resolution.get()), ("Custom", "1600x900"))
        app.flush()
        self.assertEqual(core.graphics_settings(app.profiles.settings)["preset"], "Custom")
        self.row(app, "All of this page").press()   # reset, then its undo
        self.assertEqual((preset.get(), app.profiles.profile["settings"]), ("High", {}))
        self.row(app, "All of this page").press()
        self.assertEqual((preset.get(), resolution.get()), ("Custom", "1600x900"))

    def test_a_value_of_its_own_is_shown_and_left(self):
        app = self.window()
        app.profiles.update_active(settings={"mouse_sensitivity": 147, "size": "1000x700"})   # from the game's own settings
        with patch.object(page_settings, "gamepad_inventory", return_value=("XInput", [])):
            app.show("Controls")
            self.assertEqual(self.row(app, "Mouse speed").value.cget("text"), "147 %")
            app.show("Graphics")
        self.assertEqual(self.row(app, "Window size").value.cget("text"), "1000×700")
        self.row(app, "Display").take("Borderless")
        self.assertFalse(self.row(app, "Window size").on)

    def test_rows_are_read_only_while_the_game_runs(self):
        app = self.window()
        app.process = object()
        app.show("Graphics")
        self.assertFalse(any(row.on for row in app.view.rows.items))
        self.row(app, "VSync").press()
        with self.assertRaises(core.LauncherError):
            app.keep(vsync=False)
        app.process = None
        self.assertTrue(app.profiles.settings["vsync"])

    def test_a_refused_text_is_said_under_its_field(self):
        app = self.window()
        app.show("Settings")
        row = self.row(app, "GitHub issues page")
        row.entry.delete(0, "end"); row.entry.insert(0, "https://example.com"); row.keep()
        self.assertIn("/issues", row.error.cget("text"))
        row.entry.delete(0, "end"); row.entry.insert(0, "https://github.com/someone/project/issues/"); row.keep()
        self.assertEqual((row.error.cget("text"), app.profiles.data["issues"]), ("", "https://github.com/someone/project/issues"))

    def test_the_keyboard_goes_through_rows_header_and_tabs(self):
        app = self.window()
        app.show("Graphics"); self.spin(0.1)
        rows = app.view.rows
        self.assertIs(rows.selected, rows.items[0])
        rows.step(rows.items[0], 1); self.spin(0.05)
        rows.step(rows.items[1], -1); self.spin(0.05)
        rows.step(rows.items[0], -1); self.spin(0.05)
        app.header._move(1)
        app.header.places[app.header.cursor]()
        self.assertEqual(app.active_page, "Controls")
        app.next_tab(1)
        self.assertEqual(app.active_page, "Settings")

    def test_every_page_can_be_seen_whole_at_the_minimum_size(self):
        app = self.window("880x650")
        with patch.object(page_settings, "gamepad_inventory", return_value=("XInput", [])):
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
