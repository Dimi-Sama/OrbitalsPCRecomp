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

from launcher import core, graphics, look, page_settings, page_tools, ui
from launcher.neo import TitleScreen
from launcher.tasks import Stopped
from launcher.ui import Launcher
from launcher.tests.test_launcher import build_fixture

PAGES = ("Home", "Profiles", "Graphics", "Controls", "Settings", "Files", "Tools")


class LauncherWindow(unittest.TestCase):
    def setUp(self):
        try:
            self.tk = tk.Tk()
        except tk.TclError as error:
            self.skipTest(f"no display for Tk: {error}")
        self.tk.withdraw()
        self.root = Path(tempfile.mkdtemp(prefix="orbitals-ui-"))
        self.addCleanup(shutil.rmtree, self.root, ignore_errors=True)
        self.addCleanup(self.tk.destroy)
        # no network while the pages are built
        for name in ("check_update",):
            p = patch.object(ui, name, return_value=None); p.start(); self.addCleanup(p.stop)

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

    def row(self, app, caption):
        return next(row for row in app.view.rows.items if row.caption == caption)


class LauncherWindowTest(LauncherWindow):
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


    def test_title_entries_are_enabled_again_after_any_job(self):
        app = self.window()
        done = []
        app.background("Copying…", lambda: time.sleep(0.2), done.append)
        self.spin(0.05)
        self.assertFalse(self.title(app).entries[0].enabled, "PLAY while a job runs")
        self.assertIsNone(self.title(app).card)
        self.spin(0.8)
        self.assertTrue(done)
        self.assertTrue(self.title(app).entries[0].enabled, "PLAY after it")

    def test_chips_and_controllers_lead_to_their_pages(self):
        app = self.window()
        app.pad_names = ["Pad"]
        app.show("Home")
        for pick, page in ((lambda s: s.chips[0], "Files"), (lambda s: s.chips[2], "Profiles"), (lambda s: s.pads_spot, "Controls")):
            app.show("Home"); self.spin(0.1)
            screen = self.title(app)
            with patch.object(page_settings, "gamepad_inventory", return_value=("XInput", [])):
                screen.take(pick(screen))
            self.assertEqual(app.active_page, page)

    def test_the_controllers_line_comes_with_their_first_answer(self):
        app = self.window()
        app.pad_names = None
        app.show("Home")
        self.assertIsNone(self.title(app).pads_spot)
        self.tk.after_cancel(app.pads_timer)
        with patch.object(app.pads, "names", return_value=["Pad"]):
            app.watch_pads()
            self.assertEqual(self.title(app).pads[0], "Pad")

    def test_the_arrows_reach_everything_on_the_title_screen(self):
        app = self.window()
        app.pad_names = ["Pad", "Other pad"]
        app.show("Home"); self.spin(0.2)
        screen = self.title(app)
        self.assertEqual(screen.pads[0], "2 controllers: Pad, Other pad")
        reached, todo = {screen.selected}, [screen.selected]
        while todo:
            start = todo.pop()
            for x, y in ((0, -1), (0, 1), (-1, 0), (1, 0)):
                screen.selected = start
                screen.go(x, y)
                if screen.selected not in reached:
                    reached.add(screen.selected); todo.append(screen.selected)
        self.assertEqual(reached, {spot for spot in screen.spots if spot.enabled})
        screen.selected = screen.buttons[0]
        screen.go(1, 0); self.assertIs(screen.selected, screen.buttons[1])

    def test_cards_say_the_most_important_thing_once(self):
        app = self.window()
        self.assertEqual(app.card().title, "Shaders are not prepared")
        with patch.object(ui, "outdated_release", return_value="0.1.0"):
            self.assertEqual(app.card().title, "Your game can be updated")
            app.keep_old_game()
            self.assertEqual(app.card().title, "Shaders are not prepared")
        app.show_update({"latest": "v9.0.0", "newer": True, "url": "https://github.com/x", "notes": "", "assets": {}}, None, True)
        self.assertEqual(self.title(app).card.title, "Version v9.0.0 is available")
        app.not_now()
        self.assertEqual(app.card().title, "Shaders are not prepared")
        app.skip_shaders()
        self.assertIsNone(app.card())

    def test_a_failed_long_job_is_a_card_with_its_retry(self):
        app = self.window()
        tried = []

        def fails():
            raise core.LauncherError("The disk is full.")

        with patch.object(ui.dialogs, "error") as dialog:
            app.background("Installing…", fails, None, demo="RECOMPILING ORBITALS", retry=lambda: tried.append(1))
            self.spin(0.5)
        dialog.assert_not_called()
        card = self.title(app).card
        self.assertTrue(card.alarm)
        self.assertEqual((card.title, card.text), ("Recompiling Orbitals failed", "The disk is full."))
        self.assertEqual([label for label, _ in card.buttons], ["Try again", "Open logs", "Dismiss"])
        card.buttons[0][1]()
        self.assertEqual(tried, [1])
        self.assertIsNone(app.notice)

    def buttons(self, widget):
        found = {}
        for child in widget.winfo_children():
            if child.winfo_class() == "TButton":
                found[child.cget("text")] = child
            found |= self.buttons(child)
        return found

    def test_files_page_takes_a_copy_and_installs_it(self):
        app = self.window(game=False)
        app.show("Files"); self.spin(0.1)
        self.assertTrue(self.buttons(app.page)["INSTALL"].instate(["disabled"]))
        holder = self.root / "extracted"   # holds the copy, as some tools make it
        (holder / "game" / "exefs").mkdir(parents=True)
        app.set_source(holder)
        self.assertEqual(app.source(), holder, "not a copy yet")
        (holder / "game" / "romfs").mkdir()
        for name in ("main", "main.npdm"):
            (holder / "game" / "exefs" / name).write_bytes(b"x")
        app.set_source(holder)
        self.assertEqual(app.source(), holder / "game")
        app.refresh(); self.spin(0.1)
        install = self.buttons(app.page)["INSTALL"]
        self.assertTrue(install.instate(["!disabled"]))
        native = self.root / "game"
        build_fixture(native)

        def setup(source, on_progress, task, rebuild=False):
            for done in range(3):
                on_progress(4, 5, f"compiled {done * 100}/400 (1s)"); time.sleep(0.15)
            return core.installation(native)

        with patch.object(ui, "install_from_files", side_effect=setup):
            install.invoke()
            self.spin(0.1)
            self.assertEqual(app.active_page, "Home")   # its demo
            self.assertIn("Stop", self.buttons(app.page))
            app.show("Files"); self.spin(0.3)
            self.assertTrue(app.view.steps[2][1].cget("text").startswith("✓"))
            self.assertTrue(app.view.steps[3][1].cget("text").startswith("▶"))
            self.spin(0.6)
        self.assertEqual(app.game.root, native.resolve())
        self.assertEqual((app.active_page, app.card().title), ("Home", "Shaders are not prepared"))

    def test_files_page_shows_a_failure_with_its_retry(self):
        app = self.window()
        app.show("Files")
        with patch.object(ui, "install_from_files", side_effect=core.LauncherError("The installation failed (code 1).")):
            app.set_source(self.root / "game")
            app.start_install()
            app.show("Files")
            self.spin(0.4)
        self.assertEqual(app.active_page, "Files")
        self.assertIn("Try again", self.buttons(app.page))

    def test_a_long_job_can_be_stopped_and_closing_asks(self):
        app = self.window()
        app.set_source(self.root / "game")

        def setup(source, on_progress, task, rebuild=False):
            while not task.stopped:
                time.sleep(0.02)
            raise Stopped("The installation was stopped. What is compiled is kept.")

        with patch.object(ui, "install_from_files", side_effect=setup), patch.object(ui.dialogs, "confirm", return_value=False) as ask:
            app.start_install(); self.spin(0.1)
            app.stop_job()
            self.assertFalse(app.task.stopped, "not confirmed")
            app.close()
            self.assertTrue(self.tk.winfo_exists())
            ask.return_value = True
            app.stop_job(); self.spin(0.5)
        self.assertIsNone(app.job)
        self.assertIsNone(app.notice, "a stop is not a failure")
        self.assertIn("kept", app.page_state.get())
        self.assertEqual(app.card().title, "Shaders are not prepared")

    def test_a_stop_that_leaves_the_game_incomplete_says_so(self):
        app = self.window()
        (self.root / "game" / core.MODULE).unlink()
        app.check_game()
        self.assertIsNone(app.game)
        self.assertEqual(app.card().title, "The game is not complete")

    def test_profiles_as_rows(self):
        app = self.window()
        app.show("Profiles")
        self.assertFalse(self.row(app, "Delete this profile").on, "the only one")
        with patch.object(page_tools.dialogs, "ask_text", return_value="Second"):
            self.row(app, "New profile").press()
        active = self.row(app, "Active profile")
        self.assertEqual(active.value.cget("text"), "Second")
        active.move(-1)
        self.assertEqual(app.profiles.profile["name"], "Player")
        self.assertTrue(self.row(app, "Delete this profile").on)

    def test_a_job_that_ends_leaves_the_player_where_they_were(self):
        app = self.window()
        app.show("Profiles")
        app.view.rows.choose("Back up")
        app.background("Copying…", lambda: time.sleep(0.1), lambda _: None)
        self.spin(0.5)
        self.assertEqual(app.view.rows.selected.caption, "Back up")
        app.show("Settings")
        row = self.row(app, "GitHub issues page")
        row.entry.delete(0, "end"); row.entry.insert(0, "https://github.com/someone/project/issues")
        app.refresh()
        self.assertEqual(app.profiles.data["issues"], "https://github.com/someone/project/issues")

    def test_add_to_steam_says_what_it_did(self):
        app = self.window()
        app.show("Tools")
        with patch.object(page_tools.steam, "add", side_effect=core.LauncherError("Steam was not found on this PC.")) as add:
            self.row(app, "Add to Steam").press()
            self.spin(0.6)
        self.assertEqual(set(add.call_args.args[0]), {"p.png", ".png", "_hero.png"})
        self.assertIn("not found", app.view.rows.text.cget("text"))

    def test_a_long_card_stays_above_the_chips(self):
        app = self.window()
        for size in ("880x650", "1160x755"):
            self.tk.geometry(size)
            app.fail("A failure with quite a long title that does not fit", "One long explanation of it. " * 30, ("Try again", lambda: None),
                     ("Open logs", lambda: None))
            app.show("Home"); self.spin(0.2)
            screen = self.title(app)
            self.assertLess(screen.card_box[3], screen.chips[0].box[1])
            for spot in screen.buttons:
                self.assertLess(spot.box[2], screen._split(spot.box[3]))

    def test_controller_scan_neither_blocks_saving_nor_loops_on_errors(self):
        app = self.window()
        with patch.object(page_settings, "gamepad_inventory", side_effect=RuntimeError("unexpected")) as scan, \
                patch.object(ui.dialogs, "error") as dialog:
            app.show("Controls")
            self.assertIsNone(app.job)
            app.keep(keyboard=2)
            self.spin(0.6)
        self.assertEqual(scan.call_count, 1)
        dialog.assert_not_called()
        self.assertEqual(app.profiles.settings["keyboard"], 2)

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
                    if left < screen.w * 0.4 and "spots" not in screen.gettags(item):
                        self.assertLessEqual(right, screen._split((top + bottom) / 2) + 2, screen.itemcget(item, "text"))

    def test_chips_stay_left_of_the_diagonal(self):
        app = self.window("880x650")
        app.profiles.rename("A profile name of 32 characters")
        for game in (app.game, None):
            app.game = game
            app.show("Home"); self.spin(0.2)
            screen = self.title(app)
            for spot in screen.chips:
                self.assertLess(spot.box[2], screen._split(spot.box[3]))

    def test_pages_and_title_fit_at_150_percent(self):
        with patch.object(ui, "scale_to", lambda root: look.scale_to(root, dpi=144)):
            app = self.window("1320x975")
        self.addCleanup(setattr, look, "SCALE", 1.0)
        if look.SCALE < 1.5:
            self.skipTest("the screen is too small for 150 %")
        self.assertEqual(look.px(100), 150)
        self.spin(0.2)
        screen = self.title(app)
        for spot in screen.chips + screen.buttons:
            self.assertLess(spot.box[2], screen._split(spot.box[3]))
        self.assertLess(screen.entries[-1].box[3], screen.h)
        with patch.object(page_settings, "gamepad_inventory", return_value=("XInput", [])):
            for page in PAGES[1:]:
                app.show(page); self.spin(0.1)
                self.assertGreaterEqual(app.page.winfo_width(), app.page.winfo_reqwidth(), page)

    def test_the_scale_never_outgrows_the_screen(self):
        with patch.object(self.tk, "winfo_screenwidth", return_value=1280), patch.object(self.tk, "winfo_screenheight", return_value=800):
            look.scale_to(self.tk, dpi=215)   # a small dense screen
        self.addCleanup(setattr, look, "SCALE", 1.0)
        self.assertLessEqual(look.px(650), 800 - 72 + 1)
        self.assertLessEqual(look.px(880), 1280)
        look.scale_to(self.tk, dpi=72)
        self.assertEqual(look.SCALE, 1.0)

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
