# Orbitals PC Recomp, a work based on SwitchRecomp by MZ Labs. GNU AGPL v3.0 with the additional terms of NOTICE.txt (LICENSE.txt).
"""A controller drives the launcher: its buttons become the keys every page already takes. Only while the launcher's window is in front
and no game runs, so a button never reaches both."""

import os
import time
import tkinter as tk
from pathlib import Path

from . import dialogs

POLL_MS, REST_MS = 40, 250
REPEAT_AFTER, REPEAT_EVERY = 0.40, 0.11   # seconds a direction is held before it repeats, and between repeats
KEYS = {"up": "<Up>", "down": "<Down>", "left": "<Left>", "right": "<Right>", "south": "<Return>", "east": "<Escape>"}
MODES = {"auto": "Automatic", "on": "On", "off": "Off"}


def steam_deck():
    try:
        return Path("/sys/devices/virtual/dmi/id/product_name").read_text().strip() in ("Jupiter", "Galileo")
    except OSError:
        return False


def gaming_mode():
    return os.environ.get("XDG_CURRENT_DESKTOP") == "gamescope" or os.environ.get("SteamGamepadUI") == "1"


def wanted(mode):
    """Automatic: everywhere but on the Steam Deck's desktop, where Steam already turns the controls into keys and a mouse."""
    return mode == "on" or mode != "off" and (gaming_mode() or not steam_deck())


class Navigation:
    def __init__(self, app, clock=time.monotonic):
        self.app, self.clock = app, clock
        self.held, self.repeating, self.repeat_at = None, None, 0
        self.timer = None

    def active(self):
        app = self.app
        if not app.pads.available or app.process is not None or not wanted(app.profiles.data.get("pad_navigation", "auto")):
            return False
        try:
            return app.root.focus_displayof() is not None
        except KeyError:   # a native dialog (a folder to choose) has the focus
            return False

    def tick(self):
        active = self.active()
        self.timer = self.app.root.after(POLL_MS if active else REST_MS, self.tick)   # (first: a press can open a dialog, which waits)
        if active:
            self.poll(self.app.pads.held())
        else:
            self.held, self.repeating = None, None

    def poll(self, held):
        if self.held is None:   # what is already held when the window comes to the front was not meant for it
            self.held = held
            return
        pressed, self.held = held - self.held, held
        if self.repeating not in held:
            self.repeating = None
        for button in pressed:
            if button in ("up", "down", "left", "right"):
                self.repeating, self.repeat_at = button, self.clock() + REPEAT_AFTER
            self.press(button)
        if self.repeating and not pressed and self.clock() >= self.repeat_at:
            self.repeat_at = self.clock() + REPEAT_EVERY
            self.press(self.repeating)

    def press(self, button):
        app = self.app
        if button in KEYS:
            if dialogs.focused(app.root) in (None, app.root):
                app.focus_main()
            widget = dialogs.focused(app.root) or app.stage
            try:
                widget.event_generate(KEYS[button])
            except tk.TclError:   # gone meanwhile
                pass
        elif dialogs.open_dialogs or app.root.grab_current():
            return
        elif button in ("left shoulder", "right shoulder"):
            app.next_tab(-1 if button == "left shoulder" else 1)
        elif button == "start":
            screen = app.title_screen()
            if screen:
                screen.take(screen.entries[0])
