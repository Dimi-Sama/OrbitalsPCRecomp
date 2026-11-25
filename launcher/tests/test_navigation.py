# Orbitals PC Recomp, a work based on SwitchRecomp by MZ Labs. GNU AGPL v3.0 with the additional terms of NOTICE.txt (LICENSE.txt).
"""The controller in the launcher (pads.py, navigation.py) and the dialogs it answers (dialogs.py)."""
import unittest
from unittest.mock import patch

from launcher import dialogs, navigation, page_settings, pads
from launcher.tests.test_ui import LauncherWindow


class PadsTest(unittest.TestCase):
    def test_stick_directions(self):
        self.assertEqual(pads.stick_directions(0, 0), set())
        self.assertEqual(pads.stick_directions(9000, -9000), set())
        self.assertEqual(pads.stick_directions(30000, 12000), {"right"})
        self.assertEqual(pads.stick_directions(-17000, 30000), {"down"})
        self.assertEqual(pads.stick_directions(0, -32768), {"up"})

    def test_xinput_buttons_names_and_empty_slots(self):
        class Library:
            @staticmethod
            def XInputGetState(slot, state):
                if slot != 1:
                    return 1167   # ERROR_DEVICE_NOT_CONNECTED
                state._obj.buttons, state._obj.ly = 0x1000 | 0x0200, 32767
                return 0

        backend = pads.XInput(Library)
        self.assertEqual(backend.held(), set())
        backend.scan()
        self.assertEqual(backend.names(), ["Controller 2"])
        self.assertEqual(backend.held(), {"south", "right shoulder", "up"})

    def test_only_known_folders_are_loaded_from(self):
        with patch.object(pads, "WINDOWS", True):
            for _, library in pads.backends(["C:/not/there"]):
                self.assertIn("system32", library.lower())

    def test_nothing_that_loads_is_not_an_error(self):
        with patch.object(pads, "backends", return_value=[(pads.SDL3, "no-such-library")]):
            found = pads.Pads()
            found.open()
            self.assertFalse(found.available)
            self.assertIsNone(found.names())
            self.assertEqual(found.held(), set())

    def test_automatic_is_off_on_the_decks_desktop_only(self):
        for deck, gaming, on in ((False, False, True), (True, False, False), (True, True, True)):
            with patch.object(navigation, "steam_deck", return_value=deck), patch.object(navigation, "gaming_mode", return_value=gaming):
                self.assertEqual(navigation.wanted("auto"), on)
                self.assertTrue(navigation.wanted("on"))
                self.assertFalse(navigation.wanted("off"))


class NavigationTest(LauncherWindow):
    def navigate(self, app, *buttons):
        """Press and let go of each button."""
        for button in buttons:
            app.navigation.held = set()
            app.navigation.poll({button})
            app.navigation.poll(set())
            self.spin(0.06)

    def focused(self, app):
        """The window in front, whatever the desktop gives the focus to meanwhile."""
        self.tk.focus_force()
        self.spin(0.15)
        if self.tk.focus_displayof() is None:
            self.skipTest("the window cannot be brought to the front here")

    def test_the_title_screen_the_settings_and_back(self):
        app = self.window()
        self.focused(app)
        self.navigate(app, "down")
        self.assertEqual(self.title(app).selected.label, "SETTINGS")
        self.navigate(app, "south")
        self.assertEqual(app.active_page, "Graphics")
        self.navigate(app, "right")
        self.assertEqual(app.settings()["gfx_preset"], "Low")
        with patch.object(page_settings, "gamepad_inventory", return_value=("XInput", [])):
            self.navigate(app, "right shoulder")
            self.assertEqual(app.active_page, "Controls")
            self.navigate(app, "left shoulder")
        self.navigate(app, "down", "down")
        self.assertEqual(app.view.rows.selected.caption, "Frame rate")
        self.navigate(app, "east")
        self.assertEqual(app.active_page, "Home")

    def test_start_plays(self):
        app = self.window()
        self.focused(app)
        with patch.object(app, "play") as play:
            app.show("Home"); self.spin(0.1)
            self.navigate(app, "start")
        play.assert_called_once_with()

    def test_the_buttons_of_game_files(self):
        app = self.window()
        self.focused(app)
        app.show("Files"); self.spin(0.2)
        first = self.tk.focus_get()
        self.assertEqual(first.cget("text"), "Open folder")
        self.navigate(app, "right")
        self.assertEqual(self.tk.focus_get().cget("text"), "Use another installation")
        self.navigate(app, "down")
        self.assertEqual(self.tk.focus_get().cget("text"), "Prepare shaders")
        self.navigate(app, "up", "up")
        self.assertIs(self.tk.focus_get(), app.header)
        self.navigate(app, "south")
        self.assertEqual(app.active_page, "Home")

    def test_a_dialog_takes_the_buttons_and_the_page_under_it_none(self):
        app = self.window()
        self.focused(app)
        app.show("Graphics"); self.spin(0.1)
        seen = []

        def press():
            dialog = dialogs.open_dialogs[-1]
            self.navigate(app, "right shoulder")
            seen.append(app.active_page)
            self.navigate(app, "right")
            seen.append(self.tk.focus_get() is dialog.buttons[1])
            app.refresh(); self.spin(0.1)   # a job ends under it
            seen.append(self.tk.focus_get() in dialog.buttons)
            self.navigate(app, "east")

        self.tk.after(100, press)
        self.assertFalse(dialogs.confirm(self.tk, "Sure?", "Really?"))
        self.assertEqual(seen, ["Graphics", True, True])
        self.assertEqual(app.active_page, "Graphics")
        self.assertFalse(dialogs.open_dialogs)

    def test_a_dialog_checks_what_is_typed(self):
        app = self.window()
        self.focused(app)
        said = []

        def answer():
            dialog = dialogs.open_dialogs[-1]
            dialog.entry.delete(0, "end"); dialog.entry.insert(0, "player")
            dialog.take(0)
            said.append(dialog.error.cget("text"))
            dialog.entry.delete(0, "end"); dialog.entry.insert(0, "Someone")
            dialog.take(0)

        self.tk.after(100, answer)
        name = dialogs.ask_text(self.tk, "New profile", "Name", check=lambda text: app.profiles.validate_name(text, exclude=None))
        self.assertEqual(name, "Someone")
        self.assertIn("already used", said[0])

    def test_held_directions_repeat_and_earlier_presses_are_not_taken(self):
        app = self.window()
        now, pressed = [0.0], []
        app.navigation.clock = lambda: now[0]
        with patch.object(app.navigation, "press", pressed.append):
            app.navigation.held = None
            app.navigation.poll({"south"})   # held since before the window came to the front
            app.navigation.poll({"south", "down"})
            self.assertEqual(pressed, ["down"])
            for step in range(1, 11):
                now[0] = step / 10
                app.navigation.poll({"south", "down"})
            self.assertEqual(pressed.count("south"), 0)
            self.assertIn(pressed.count("down"), (5, 6, 7))
            app.navigation.poll(set())
            count = len(pressed)
            now[0] += 5
            app.navigation.poll(set())
            self.assertEqual(len(pressed), count)

    def test_nothing_while_a_game_runs_or_when_turned_off(self):
        app = self.window()
        with patch.object(pads.Pads, "available", True), patch.object(self.tk, "focus_displayof", return_value=self.tk):
            self.assertTrue(app.navigation.active())
            app.process = object()
            self.assertFalse(app.navigation.active())
            app.process = None
            app.profiles.update(pad_navigation="off")
            self.assertFalse(app.navigation.active())

    def test_the_controllers_are_let_go_when_the_game_starts(self):
        app = self.window()

        class Game:
            pid = 1

            def poll(self):
                return None

        with patch.object(app.pads, "close") as close:
            app.started((Game(), self.root))
        close.assert_called_once_with()
        app.process = None



if __name__ == "__main__":
    unittest.main()
