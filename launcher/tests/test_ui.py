# Orbitals PC Recomp, a work based on SwitchRecomp by MZ Labs. GNU AGPL v3.0 with the additional terms of NOTICE.txt (LICENSE.txt).
"""The launcher window itself: every page is built once, with no game installed and with a fixture installation.

A page that raises while it is built (v0.1.5-preview.1: the home page's shader line passed justify twice) leaves the launcher closed
for the player; the core tests do not build any widget. Skipped where Tk has no display."""
import shutil
import tempfile
import tkinter as tk
import unittest
from pathlib import Path
from unittest.mock import patch

from launcher import core
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
            ui = Launcher(self.tk, local, game)
            for page in PAGES:
                with self.subTest(page=page, game=bool(game)):
                    ui.show(page)
                    self.tk.update_idletasks()

    def test_every_page_builds_without_a_game(self):
        self.build()

    def test_every_page_builds_with_an_installation(self):
        native = self.root / "game"
        build_fixture(native)
        self.build(native)


if __name__ == "__main__":
    unittest.main()


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

class ControlsRowsTest(LauncherWindowTest):
    def test_controls_defaults_save_and_session_lock(self):
        from tkinter import ttk
        ui = Launcher(self.tk, self.root / 'controls', None)
        ui.job = True
        ui.show('Controls')
        def widgets(parent):
            for child in parent.winfo_children():
                yield child
                yield from widgets(child)
        combos = [w for w in widgets(ui.page) if isinstance(w, ttk.Combobox)]
        self.assertTrue(all(w.instate(['disabled']) for w in combos))
        self.assertIn('Nintendo', [w.get() for w in combos])
        self.assertIn('Off', [w.get() for w in combos])
        ui.job = None
        with patch.object(ui, 'background'):
            ui.show('Controls')
        combos = [w for w in widgets(ui.page) if isinstance(w, ttk.Combobox)]
        layout = next(w for w in combos if 'Nintendo' in w.cget('values'))
        layout.set('Xbox')
        next(w for w in widgets(ui.page) if isinstance(w, ttk.Button) and w.cget('text') == 'Save').invoke()
        self.assertEqual(ui.profiles.settings['button_layout'], 'Xbox')
        first = ui.profiles.active
        ui.profiles.create('Other player')
        self.assertEqual(ui.profiles.settings['button_layout'], 'Nintendo')
        ui.profiles.select(first)
        self.assertEqual(ui.profiles.settings['button_layout'], 'Xbox')

class ResolutionRowsTest(LauncherWindowTest):
    def test_mouse_wheel_scrolls_both_settings_pages(self):
        self.tk.deiconify()
        self.tk.geometry("880x650")
        ui = Launcher(self.tk, self.root / 'wheel', None)
        for page in ('Controls', 'Graphics'):
            ui.show(page)
            self.tk.update()
            canvas = ui.page.master
            canvas.yview_moveto(0)
            before = canvas.yview()[0]
            ui.page.event_generate('<Button-5>')
            self.tk.update()
            if canvas.winfo_height() < ui.page.winfo_reqheight() + 28:
                self.assertGreater(canvas.yview()[0], before, page)
            else:
                self.assertEqual(canvas.yview()[0], before, page)
            ui.page.event_generate('<MouseWheel>', delta=120)
            self.tk.update()
            self.assertEqual(canvas.yview()[0], before, page)

    def test_low_preset_explains_inactive_tv_output(self):
        from tkinter import ttk
        ui = Launcher(self.tk, self.root / 'low-tv', None)
        ui.show('Graphics')
        def widgets(parent):
            for child in parent.winfo_children():
                yield child
                yield from widgets(child)
        all_widgets = list(widgets(ui.page))
        combos = [w for w in all_widgets if isinstance(w, ttk.Combobox)]
        preset = next(w for w in combos if 'Low' in w.cget('values'))
        tv = next(w for w in combos if '1440p' in w.cget('values'))
        def warning():
            return '\n'.join(str(w.cget('text')) for w in all_widgets if isinstance(w, (tk.Label, ttk.Label)))
        preset.set('Low')
        tv.set('1440p')
        self.tk.update_idletasks()
        self.assertIn('TV output resolution has no effect', warning())
        preset.set('High')
        self.tk.update_idletasks()
        self.assertNotIn('TV output resolution has no effect', warning())

    def test_tv_selector_save_and_reset(self):
        from tkinter import ttk
        ui = Launcher(self.tk, self.root / 'resolution', None)
        ui.show('Graphics')
        def widgets(parent):
            for child in parent.winfo_children():
                yield child
                yield from widgets(child)
        combo = next(w for w in widgets(ui.page) if isinstance(w, ttk.Combobox) and '2160p (4K)' in w.cget('values'))
        self.assertEqual(combo.get(), '1080p (console)')
        combo.set('2160p (4K)')
        next(w for w in widgets(ui.page) if isinstance(w, ttk.Button) and w.cget('text') == 'Save').invoke()
        self.assertEqual(ui.profiles.settings['tv_resolution'], '2160p (4K)')
        next(w for w in widgets(ui.page) if isinstance(w, ttk.Button) and w.cget('text') == 'Reset').invoke()
        self.assertEqual(ui.profiles.settings['tv_resolution'], '1080p (console)')
