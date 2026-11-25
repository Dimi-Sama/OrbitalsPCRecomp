# Orbitals PC Recomp, a work based on SwitchRecomp by MZ Labs. GNU AGPL v3.0 with the additional terms of NOTICE.txt (LICENSE.txt).
"""The Game files page: how to set the game up, what is installed, the running job, or what failed."""

import shutil
import tkinter as tk
from tkinter import filedialog, ttk

from .core import REPO, WINDOWS, game_release, game_source, outdated_release, setup_log, shader_preparation, source_lacks
from .look import BG, CYAN, INK, LINE, MUTED, PANEL, PEACH, RED, label, px, surface

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
    def card(self, title=None, line=LINE):
        card = surface(self.page)
        card.configure(highlightbackground=line)
        card.pack(fill="x", pady=(0, px(12)))
        body = tk.Frame(card, bg=PANEL)
        body.pack(fill="x", padx=px(16), pady=px(13))
        if title:
            label(body, title, bg=PANEL, size=13, bold=True, font_family=self.app.heading_font).pack(anchor="w", pady=(0, px(4)))
        return body

    def text(self, parent, words, color=MUTED, **pack):
        text = label(parent, words, bg=parent.cget("bg"), color=color, wraplength=px(TEXT_WIDTH))
        text.pack(anchor="w", **pack)
        return text

    def buttons(self, parent, *buttons, first=False):
        """[(title, run, main, enabled)] in a row."""
        row = tk.Frame(parent, bg=parent.cget("bg"))
        row.pack(anchor="w", pady=(px(10), 0))
        for title, run, main, enabled in buttons:
            button = self.app.button(row, title, run, style="Play.TButton" if main else "TButton")
            button.pack(side="left", padx=(0, px(8)))
            if not enabled:
                button.state(["disabled"])
            elif first and self.first is None:
                self.first = button

    # ---- states
    def notice(self, card):
        body = self.card(card.title, line=RED)
        self.text(body, card.text, color=INK)
        self.buttons(body, *((title, run, False, True) for title, run in card.buttons), first=True)

    def working(self):
        app = self.app
        body = self.card(app.spoken(app.demo_title))
        self.bar = ttk.Progressbar(body, mode="determinate", maximum=100)
        self.bar.pack(fill="x", pady=(px(6), px(8)))
        self.timing = self.text(body, "")
        if app.install_step is not None:
            self.steps = []
            for name in SETUP_NAMES:
                line = label(body, name, bg=PANEL)
                line.pack(anchor="w", pady=(px(4), 0))
                self.steps.append((name, line))
        self.said = self.text(body, "", pady=(px(8), 0))
        self.buttons(body, ("Stop", app.stop_job, False, app.stoppable and not app.task.stopped), first=True)
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
        for number, (name, line) in enumerate(self.steps or (), 1):
            done, now = number < app.install_step, number == app.install_step
            line.configure(text=("✓   " if done else "▶   " if now else "○   ") + name, fg=CYAN if done else INK if now else MUTED)

    def setup(self):
        """The three steps of a first installation, or of another one."""
        app = self.app
        busy = bool(app.process or app.job)
        source = app.source()
        lacks = source_lacks(source) if source else None
        if not app.game:
            self.text(self.page, "The game does not come with this launcher: it needs your own copy, extracted to a folder with exefs and romfs. "
                      "Setting it up recompiles that copy on this PC.", color=INK, pady=(0, px(12)))
        body = self.step(1, "Your copy", lacks == [])
        if source:
            self.text(body, str(source), color=INK)
        if lacks:
            self.text(body, "Not the folder of a copy: " + ", ".join(lacks) + (" is" if len(lacks) == 1 else " are") + " missing.", color=PEACH)
        else:
            self.text(body, "Keep this folder in place: the installation links to it." if source else "Choose the folder that holds exefs and romfs.")
        self.buttons(body, ("Choose another folder" if source else "Choose folder", self.choose, False, not busy), first=lacks != [])

        free = shutil.disk_usage(REPO).free / 2**30
        body = self.step(2, "This PC", free >= DISK_GIB)
        self.text(body, f"{free:.0f} GB free on the disk of {REPO}. About {DISK_GIB} GB are needed.", color=MUTED if free >= DISK_GIB else PEACH)
        self.text(body, "The build tools are downloaded from their official servers and checked (SHA-256), into the launcher's folder; nothing is "
                  "installed system-wide." if WINDOWS else "GCC, SPIRV-Tools and the .NET 10 runtime come from your distribution; if one is "
                  "missing, its package is named.")

        body = self.step(3, "Set up again" if app.game else "Set up", False)
        self.text(body, "20 to 60 minutes, once. You can use the launcher meanwhile, and stop: what is compiled is kept.")
        self.buttons(body, ("INSTALL", app.start_install, True, lacks == [] and not busy),
                     *((("Use an installation made before", app.locate, False, not busy),) if not app.game else ()), first=lacks == [])

    def step(self, number, title, done):
        card = surface(self.page)
        card.pack(fill="x", pady=(0, px(10)))
        mark = label(card, "✓" if done else str(number), bg=CYAN if done else BG, color=BG if done else CYAN, bold=True, size=12, width=3,
                     anchor="center")
        mark.pack(side="left", anchor="n", padx=(px(16), px(6)), pady=px(13), ipady=px(3))
        body = tk.Frame(card, bg=PANEL)
        body.pack(side="left", fill="x", expand=True, padx=px(8), pady=px(13))
        label(body, title, bg=PANEL, size=13, bold=True, font_family=self.app.heading_font).pack(anchor="w")
        return body

    def choose(self):
        app = self.app
        app.guard()
        path = filedialog.askdirectory(parent=app.root, title="Folder extracted from your copy (with exefs and romfs)")
        if path:
            app.set_source(path)
            app.refresh()

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
        self.buttons(body, *((("Update the game", app.recompile_game, True, not busy),) if old else ()),
                     ("Open folder", lambda: app.open_folder(game.root), False, True),
                     ("Use another installation", app.locate, False, not busy), first=True)

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
        self.buttons(row, (("▾  " if app.setup_open else "▸  ") + "Set up again from a copy", self.fold, False, True),
                     *((("Open setup log", lambda: app.open_file(setup_log()), False, True),) if setup_log().is_file() else ()))
        if app.setup_open:
            self.setup()

    def fold(self):
        self.app.setup_open = not self.app.setup_open
        self.app.refresh()
