# Orbitals PC Recomp, a work based on SwitchRecomp by MZ Labs. GNU AGPL v3.0 with the additional terms of NOTICE.txt (LICENSE.txt).
"""The Game files page: how to set the game up, what is installed, the running job, or what failed."""

import shutil
import tkinter as tk
from tkinter import filedialog, ttk

from .core import REPO, WINDOWS, game_release, game_source, outdated_release, setup_log, shader_preparation, source_lacks
from . import paint
from .look import BG, BLUE, CYAN, INK, MUTED, PANEL, PEACH, RED, card, headline, label, px

DISK_GIB = 5
TEXT_WIDTH = 690
SETUP_NAMES = (("Python and GCC", "g++, the Vulkan tools, .NET and SDL", "The Vulkan layer and the runtime", "Your copy's code, the longest",
                "The game's folder") if WINDOWS else
               ("The build tools and your files, checked", "The links to your files", "The Vulkan layer and the runtime",
                "Your copy's code, the longest", "The game's folder"))


class FilesPage:
    def __init__(self, app):
        self.app, self.page, self.first = app, app.page, None
        self.bar = self.steps = self.said = self.timing = None
        self.stop_control = None
        if app.job and app.demo_title:
            self.working()
        else:
            if app.notice:
                self.notice(app.notice)
            if app.game:
                self.installed()
                self.shaders()
                self.again()
            else:
                self.setup()
        if self.first:
            self.first.focus_set()

    # ---- pieces
    def card(self, title=None, strip=BLUE):
        frame, body = card(self.page, strip)
        frame.pack(fill="x", pady=(0, px(12)))
        if title:
            headline(body, title, size=18).pack(anchor="w", pady=(0, px(4)))
        return body

    def text(self, parent, words, color=MUTED, **pack):
        text = label(parent, words, bg=parent.cget("bg"), color=color, wraplength=px(TEXT_WIDTH))
        text.pack(anchor="w", **pack)
        return text

    def buttons(self, parent, *buttons, first=False):
        """[(title, run, main, enabled)] in a row."""
        row = tk.Frame(parent, bg=parent.cget("bg"))
        row.pack(anchor="w", pady=(px(10), 0))
        controls = []
        for title, run, main, enabled in buttons:
            button = self.app.button(row, title, run, style="Play.TButton" if main else "TButton")
            controls.append(button)
            button.pack(side="left", padx=(0, px(8)))
            if not enabled:
                button.state(["disabled"])
            elif first and self.first is None:
                self.first = button
        return controls

    # ---- states
    def notice(self, card):
        body = self.card(card.title, strip=RED)
        self.text(body, card.text, color=INK)
        self.buttons(body, *((title, run, not number, True) for number, (title, run) in enumerate(card.buttons)), first=True)

    def working(self):
        app = self.app
        body = self.card(app.spoken(app.demo_title), strip=CYAN)
        self.bar = ttk.Progressbar(body, mode="determinate", maximum=100)
        self.bar.pack(fill="x", pady=(px(6), px(8)))
        self.timing = self.text(body, "")
        if app.install_step is not None:
            self.steps = []
            for name in SETUP_NAMES:
                line = label(body, name, compound="left", padx=0)
                line.pack(anchor="w", pady=(px(5), 0))
                self.steps.append((name, line))
        self.said = self.text(body, "", pady=(px(8), 0))
        self.stop_control, = self.buttons(body, ("Stop", app.stop_job, False, app.can_stop()), first=True)
        self.progress()

    def progress(self):
        """The job went on (Launcher.poll_job)."""
        app = self.app
        if not self.bar:
            return
        fraction, step, said = app.demo_state
        self.bar.configure(value=100 * fraction)
        self.timing.configure(text=f"{100 * fraction:.0f} %  ·  {app.pace.text()}")
        self.said.configure(text=said)
        if self.stop_control:
            self.stop_control.state(["!disabled" if app.can_stop() else "disabled"])
        for number, (name, line) in enumerate(self.steps or (), 1):
            done, now = number < app.install_step, number == app.install_step
            line.configure(text="   " + name, fg=CYAN if done else INK if now else MUTED,
                           image=paint.shape("dot", px(12), CYAN) if done else paint.shape("next", px(12), RED) if now else paint.shape("ring", px(12), "#5a64a8"))

    def setup(self):
        """The three steps of a first installation, or of another one."""
        app = self.app
        busy = bool(app.process or app.job)
        source = app.source()
        from_nup = app.source_is_nup()
        lacks = (["a readable NUP archive"] if not source.is_file() else []) if from_nup else source_lacks(source) if source else None
        if not app.game:
            self.text(self.page, "Setup recompiles your own copy of Orbitals on this PC.", color=INK, pady=(0, px(12)))
        body = self.step(1, "Your copy", lacks == [])
        if source:
            self.text(body, str(source), color=INK)
        if lacks:
            self.text(body, "Missing " + ", ".join(lacks) + ".", color=PEACH)
        elif from_nup:
            self.text(body, "Liftoff verifies and extracts the base game into the installation folder.")
        else:
            self.text(body, "Keep this folder in place: the installation links to it." if source else
                      "Choose a NUP containing the base game or the folder that holds exefs and romfs.")
        self.buttons(body, ("Choose NUP file", self.choose_nup, False, not busy),
                     ("Choose ExeFS / RomFS folder", self.choose, False, not busy), first=lacks != [])

        destination = app.install_destination()
        volume = next((p for p in (destination, *destination.parents) if p.is_dir()), REPO)
        free = shutil.disk_usage(volume).free / 2**30
        body = self.step(2, "Installation folder", free >= DISK_GIB)
        self.text(body, str(destination), color=INK)
        self.text(body, f"{free:.0f} GiB free. Allow space for the build and, with NUP, the extracted game.",
                  color=MUTED if free >= DISK_GIB else PEACH)
        self.buttons(body, ("Choose installation folder", self.choose_destination, False, not busy),
                     ("Use default", self.default_destination, False, not busy and app.install_target is not None))
        self.text(body, "The build tools are downloaded from their official servers and checked (SHA-256), into the launcher's folder; nothing is "
                  "installed system-wide." if WINDOWS else "GCC, SPIRV-Tools and the .NET 10 runtime come from your distribution; if one is "
                  "missing, its package is named.")

        body = self.step(3, "Set up again" if app.game else "Set up", False)
        self.text(body, "Allow 20 to 60 minutes for recompilation. You can stop a NUP extraction before recompilation starts.")
        self.buttons(body, ("INSTALL", app.start_install, True, lacks == [] and not busy),
                     *((("Select an existing installation folder", app.locate, False, not busy),) if not app.game else ()), first=lacks == [])

    def step(self, number, title, done):
        frame, inside = card(self.page, CYAN if done else PEACH)
        frame.pack(fill="x", pady=(0, px(10)))
        mark = headline(inside, "OK" if done else str(number), size=15, color=BG, compound="center", anchor="center",
                        image=paint.leaning(px(46), px(30), px(8), CYAN if done else PEACH))
        mark.pack(side="left", anchor="n", padx=(0, px(16)))
        body = tk.Frame(inside, bg=PANEL)
        body.pack(side="left", fill="x", expand=True)
        headline(body, title, size=18).pack(anchor="w")
        return body

    def choose(self):
        app = self.app
        app.guard()
        path = filedialog.askdirectory(parent=app.root, title="Folder extracted from your copy (with exefs and romfs)")
        if path:
            app.set_source(path)
            app.refresh()

    def choose_nup(self):
        app = self.app
        app.guard()
        path = filedialog.askopenfilename(parent=app.root, title="NUP containing your copy of the base game",
                                          filetypes=[("NUP archives", ("*.nup", "*.NUP"))])
        if path:
            app.set_source(path, from_nup=True)
            app.refresh()

    def choose_destination(self):
        app = self.app
        app.guard()
        path = filedialog.askdirectory(parent=app.root, title="Choose the installation folder")
        if path:
            app.install_target = Path(path)
            app.refresh()

    def default_destination(self):
        self.app.guard()
        self.app.install_target = None
        self.app.refresh()

    def installed(self):
        app, game = self.app, self.app.game
        busy = bool(app.process or app.job)
        old = outdated_release(game)
        body = self.card("Installed")
        grid = tk.Frame(body, bg=PANEL)
        grid.pack(anchor="w")
        source = game_source(game)
        if source and source.is_relative_to(game.root):   # copied into it, not linked
            source = None
        release = game_release(game)
        facts = (("Game", (f"{game.version} · " if game.version else "") + f"build {game.ids['main'][:16]}"),
                 ("Compiled by", (release or "a development build") + (f" (this launcher is {app.version})" if old else "")),
                 ("Folder", str(game.root)), ("Your copy", str(source) if source else "copied into the installation"))
        for row, (name, value) in enumerate(facts):
            label(grid, name, bg=PANEL, color=MUTED).grid(row=row, column=0, sticky="nw", padx=(0, px(16)), pady=px(1))
            label(grid, value, bg=PANEL, color=PEACH if old and name == "Compiled by" else INK,
                  wraplength=px(TEXT_WIDTH - 110)).grid(row=row, column=1, sticky="w", pady=px(1))
        from . import code_update

        update = ("Check installed code", app.recompile_game, bool(code_update.kit_differs(game)), not busy)
        restore = (("Restore previous version", app.restore_game, False, not busy),) if code_update.can_restore(game.root) else ()
        self.buttons(body, ("Open folder", lambda: app.open_folder(game.root), False, True),
                     ("Use another installation", app.locate, False, not busy), update, *restore, first=True)

    def shaders(self):
        app = self.app
        ready = shader_preparation(app.game, app.profiles)
        body = self.card("Shaders")
        self.text(body, app.shader_state_text())
        self.buttons(body, ("Prepare again" if ready else "Prepare shaders", app.prepare_shaders, not ready, not (app.process or app.job)))

    def again(self):
        app = self.app
        row = tk.Frame(self.page, bg=BG)
        row.pack(fill="x", pady=(0, px(10)))
        self.buttons(row, ("Hide the set up" if app.setup_open else "Set up again from a copy", self.fold, False, True),
                     *((("Open setup log", lambda: app.open_file(setup_log()), False, True),) if setup_log().is_file() else ()))
        if app.setup_open:
            self.setup()

    def fold(self):
        self.app.setup_open = not self.app.setup_open
        self.app.refresh()
