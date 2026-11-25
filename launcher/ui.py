# SwitchRecomp - Copyright 2026 MZ Labs

import os
import queue
import re
import subprocess
import threading
import tkinter as tk
import webbrowser
from pathlib import Path
from tkinter import filedialog, messagebox, simpledialog, ttk

from . import VERSION
from .core import (DEFAULT_SETTINGS, LOG, REPO, WINDOWS, LauncherError, Profiles, carry_saves, check_update, detect_installation,
                   download_update, finish_session, game_source, install_fraction, install_from_files, installation, json_bytes,
                   latest_run, launch, launch_kit, outdated_release, prepare, prepare_shaders, runtime_info, shader_preparation,
                   validate_settings)
from .demo import DemoScreen
from .look import BG, CYAN, MUTED, PANEL, PEACH, RAIL, RED, ScrollPage, label, px, surface, theme
from .neo import Card, HeaderStrip, TitleScreen
from .pads import Pads
from .page_settings import REMOVED, ControlsPage, GeneralPage, GraphicsPage
from .report_form import ReportForm, show_text
from .reports import gpu_info, system_info
from .rows import TextRow
from .shader_text import SHADER_PREP_TEXT, shader_progress, shader_progress_text


def open_folder(path):
    if not path.is_dir():
        raise LauncherError("This folder appears after the first session.")
    if WINDOWS:
        os.startfile(path)
    else:
        subprocess.Popen(["xdg-open", str(path)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


class Launcher:
    def __init__(self, root, local, selected=None):
        self.root = root
        self.local = local
        self.profiles = Profiles(local)
        self.game = None
        self.template = None
        self.notice = None           # a Card the title screen shows until it is dismissed (a failure)
        self.update_info = self.update_kit = None; self.update_answer = ""; self.update_later = False
        self.retry = None            # what starts the running job again, if it fails
        self.job = None
        self.process = None
        self.run = None
        self.active_page = "Home"
        self.demo = None; self.demo_title = None; self.demo_state = (0.0, "", "")   # the demo screen of a long task (demo.py)
        self.page_state = tk.StringVar()
        self.events = queue.Queue()
        self.calls = queue.Queue()   # functions other threads want run on this one (post)
        self.pending = {}            # settings changed and not written yet (keep, flush)
        self.flush_timer = None
        self.font, self.heading_font = theme(root)
        assets = Path(__file__).with_name("assets")
        self.icon = tk.PhotoImage(file=str(assets / "orbitals-icon.png"))
        root.iconphoto(True, self.icon)
        root.title("Liftoff · Orbitals PC Recomp")
        root.configure(bg=BG)
        root.minsize(880, 650)
        width = min(1160, root.winfo_screenwidth() - 60)
        height = min(755, root.winfo_screenheight() - 75)
        root.geometry(f"{width}x{height}")
        root.protocol("WM_DELETE_WINDOW", self.close)
        root.bind("<Destroy>", self.closed, add="+")
        root.report_callback_exception = self.callback_error

        configured = self.profiles.data.get("install")
        candidate = selected or (Path(configured) if configured else None)
        if candidate:
            try:
                self.game = installation(candidate)
            except (OSError, LauncherError) as error:
                self.fail("The installation was not opened", f"{error}\n{candidate}", ("Use another installation", self.locate))
        else:
            self.game = detect_installation()
        self.template = self.game
        LOG.info("event=detect ready=%s", self.game is not None)
        self.pads = Pads([*((self.game.root,) if self.game else ()), REPO / "bin"])
        self.pad_names = None
        self.pads_timer = root.after(50, self.watch_pads)
        self.build_shell()
        self.show("Home")
        self.pump()
        if self.profiles.data.get("update_check", True):   # on unless turned off in Settings; one request to GitHub's releases API
            threading.Thread(target=lambda: self.update_result(quiet=True), daemon=True).start()

    def closed(self, event):
        if event.widget is self.root:
            for timer in filter(None, (self.pump_timer, self.pads_timer, self.flush_timer)):
                self.root.after_cancel(timer)
            self.pads.close()

    def watch_pads(self):
        """The controllers for the title screen's line; not while a game runs, they are its own then."""
        if self.process:
            self.pads.close()
            names = self.pad_names
        else:
            self.pads.open()
            names = self.pads.names()
        if names != self.pad_names:
            self.pad_names = names
            screen = self.title_screen()
            if screen and screen.pads_spot is None:   # the first answer: its line is there from now on
                self.show("Home")
            elif screen:
                screen.set_pads(*self.pads_line())
        self.pads_timer = self.root.after(1000, self.watch_pads)

    def pads_line(self):
        names = self.pad_names or []
        if not names:
            return "No controller connected", False
        more = f" and {len(names) - 2} more" if len(names) > 2 else ""
        return (f"{len(names)} controllers: " if len(names) > 1 else "") + ", ".join(names[:2]) + more, True

    def title_screen(self):
        return next((w for w in self.page.winfo_children() if isinstance(w, TitleScreen)), None) if self.active_page == "Home" else None

    def fail(self, title, text, *buttons):
        """Something failed: the title screen says it until it is dismissed."""
        self.notice = Card(title, text, [(label_text, lambda run=run: (self.dismiss(), self.action(run))) for label_text, run in buttons]
                           + [("Dismiss", self.dismiss)], alarm=True)

    def dismiss(self):
        self.notice = None
        if self.active_page == "Home":
            self.show("Home")

    def post(self, function):
        """From any thread: run function on the Tk thread (Tk calls from another thread can fail while a window closes)."""
        self.calls.put(function)

    def pump(self):
        while True:
            try:
                function = self.calls.get_nowait()
            except queue.Empty:
                break
            self.action(function)
        self.pump_timer = self.root.after(90, self.pump)

    def probe(self, worker, done):
        """A short question asked on a worker thread, whose answer goes to done. Unlike background(), nothing waits for it."""
        def work():
            try:
                result = worker()
            except Exception as error:   # a failed probe is an answer too: never a dialog of its own
                LOG.error("event=probe_failed type=%s", type(error).__name__)
                result = error
            self.post(lambda: done(result))

        threading.Thread(target=work, daemon=True).start()

    # ---- settings: kept as they change
    def settings(self):
        """The active profile's settings, with the changes not written yet."""
        settings = self.profiles.settings
        for key, value in self.pending.items():
            if value is not REMOVED:
                settings[key] = value
            elif key in DEFAULT_SETTINGS:
                settings[key] = DEFAULT_SETTINGS[key]
            else:
                settings.pop(key, None)
        return settings

    def keep(self, **values):
        """Change settings of the active profile. They are written a moment later, together: a held key changes many."""
        if self.process:
            raise LauncherError("The game is running: use its own PC settings, they are read when it closes.")
        before, self.pending = self.pending, self.pending | values
        try:
            validate_settings(self.settings())
        except LauncherError:
            self.pending = before
            raise
        if self.flush_timer:
            self.root.after_cancel(self.flush_timer)
        self.flush_timer = self.root.after(250, lambda: self.action(self.flush))

    def flush(self):
        if self.flush_timer:
            self.root.after_cancel(self.flush_timer)
            self.flush_timer = None
        if not self.pending:
            return
        stored = dict(self.profiles.profile["settings"]) | self.pending
        self.profiles.update_active(settings={key: value for key, value in stored.items() if value is not REMOVED})
        self.pending = {}
        self.page_state.set("Settings saved.")

    def settings_note(self):
        text = ("The game is running: its own PC settings apply, and are kept when it closes." if self.process else
                f"For {self.profiles.profile['name']}. Changes are saved as you make them and apply when you press PLAY.")
        label(self.note_bar, text, color=PEACH if self.process else MUTED).pack(anchor="w")

    def ask_text(self, title, prompt, value=""):
        return simpledialog.askstring(title, prompt, parent=self.root, initialvalue=value)

    @staticmethod
    def open_folder(path):
        open_folder(path)

    def focus_header(self):
        if self.header:
            self.header.focus_set()

    def focus_page(self):
        """From the header down to the page: its selected row, or its first widget."""
        rows = getattr(self.view, "rows", None)
        if rows and rows.selected:
            rows.selected.focus_set()
        elif self.header:
            self.header.tk_focusNext().focus_set()

    def check_now(self):
        self.update_answer = "Checking…"
        threading.Thread(target=self.update_result, daemon=True).start()

    def old_game(self):
        """The older release the game was compiled by, unless keeping it was already chosen for this launcher version."""
        old = outdated_release(self.game) if self.game else None
        return old if old and self.profiles.data.get("recompile_declined") != f"{old}->{VERSION}" else None

    def keep_old_game(self):
        self.profiles.update(recompile_declined=f"{self.old_game()}->{VERSION}")
        self.refresh()

    def recompile_game(self):
        """Recompile the current game's own files with this kit; the old installation (and its saves) stays untouched."""
        self.guard()
        old = self.game
        source = game_source(old) if old else None
        if source is None:
            path = filedialog.askdirectory(parent=self.root, title="Folder extracted from your copy (with exefs and romfs)")
            if not path:
                return
            source = Path(path)
        in_place = (REPO / "games" / "Orbitals").resolve() == old.root.resolve() if old else False

        def done(game):
            try:
                if carry_saves(old, game):
                    self.page_state.set("Saves copied from the previous installation.")
            except OSError as error:
                messagebox.showwarning("Saves", f"The saves could not be copied ({error}). They are still in {old.saves}.",
                                       parent=self.root)
            self.installed(game)

        self.background("Recompiling…",
                        lambda: install_from_files(source, on_progress=lambda s, n, t: self.events.put(("progress", (s, n, t))),
                                                   rebuild=in_place),
                        done, demo="RECOMPILING ORBITALS", retry=self.recompile_game)

    def update_result(self, quiet=False):
        """Runs on a worker thread: asks GitHub for the latest release and hands the answer to the Tk thread."""
        try:
            info, error = check_update(), None
        except LauncherError as err:
            info, error = None, str(err)
        self.post(lambda: self.show_update(info, error, quiet))

    def show_update(self, info, error, quiet):
        """The answer: on the title screen when there is a newer version, and on the General page that asked."""
        if error or info is None:
            self.update_answer = error or "No update repository is set in this version of the launcher."
        elif not info["newer"]:
            self.update_answer = f"You have the latest version ({VERSION})."
            self.page_state.set(f"Launcher up to date (version {VERSION}).")
        else:
            self.update_info, self.update_later = info, False
            self.update_answer = f"Version {info['latest']} is available (you have {VERSION})."
            self.page_state.set(self.update_answer)
        rows = getattr(self.view, "rows", None)
        if rows:
            rows.sync()
        elif self.active_page == "Home" and not self.job:
            self.show("Home")

    def download_update(self):
        self.guard()
        info = self.update_info
        self.background(f"Downloading {info['latest']}…",
                        lambda: download_update(info, on_progress=lambda d, t: self.events.put(("progress", (d, t)))),
                        self.update_ready, demo="DOWNLOADING UPDATE", retry=self.download_update)

    def update_ready(self, kit):
        self.update_kit = kit
        self.update_answer = f"Version {self.update_info['latest']} is ready in {kit}."
        self.page_state.set(self.update_answer)
        self.refresh()

    def open_update(self):
        self.guard()
        launch_kit(self.update_kit)
        self.close()

    def update_notes(self):
        notes = self.update_info["notes"].strip() or "The release has no notes."
        show_text(self.root, f"What's new in {self.update_info['latest']}", f"{notes}\n\n{self.update_info['url']}")

    def not_now(self):
        self.update_later = True
        self.refresh()

    def card(self):
        """What the title screen's card says, the most important first; nothing while a job or the game runs."""
        if self.process or self.job:
            return None
        act = lambda f: (lambda: self.action(f))
        if self.notice:
            return self.notice
        if self.update_kit and not self.update_later:
            return Card(f"Version {self.update_info['latest']} is ready", "It opens in its own folder and offers to recompile your game. "
                        "Your saves and this version stay as they are.", [("Open it", act(self.open_update)), ("Later", self.not_now)])
        if self.update_info and not self.update_later:
            return Card(f"Version {self.update_info['latest']} is available", f"You have {VERSION}. It is checked (SHA-256) and unpacked "
                        "beside this one; nothing is replaced.",
                        [("Update", act(self.download_update)), ("What's new", act(self.update_notes)), ("Later", self.not_now)])
        old = self.old_game()
        if old:
            return Card("Your game can be updated", f"It was compiled by version {old}; this launcher is {VERSION}. Recompiling takes 20 to "
                        "60 minutes, once. Your saves are kept.",
                        [("Update the game", act(self.recompile_game)), ("Not now", act(self.keep_old_game))])
        if self.game and not shader_preparation(self.game, self.profiles) and not self.profiles.data.get("shader_prep_declined"):
            return Card("Shaders are not prepared", "The first session pauses for each new one. Preparing them all takes about 15 minutes, "
                        "once.", [("Prepare now", act(self.prepare_shaders)), ("Not now", act(self.skip_shaders))])
        return None

    def skip_shaders(self):
        self.profiles.update(shader_prep_declined=True)
        self.refresh()

    def callback_error(self, error_type, error, stack):
        LOG.error("event=ui_error type=%s", error_type.__name__)
        messagebox.showerror("Liftoff", str(error), parent=self.root)

    def action(self, callback):
        try:
            callback()
        except (OSError, LauncherError, subprocess.SubprocessError, tk.TclError) as error:
            LOG.error("event=action_failed type=%s", type(error).__name__)
            self.copy_from(error)
            messagebox.showerror("Liftoff", str(error), parent=self.root)

    def copy_from(self, error):
        """An error that carries a command (a package install): on the clipboard, ready to paste in a terminal."""
        command = getattr(error, "copy", None)
        if command:
            try:
                self.root.clipboard_clear(); self.root.clipboard_append(command)
            except tk.TclError:
                pass

    def guard(self):
        if self.process or self.job:
            raise LauncherError("Wait for the current session or operation to finish.")
        self.flush()

    def button(self, parent, title, callback, *, style="TButton"):
        button = ttk.Button(parent, text=title, style=style, command=lambda: self.action(callback))
        button.bind("<Return>", lambda _: button.invoke())
        return button

    def build_shell(self):
        self.root.rowconfigure(0, weight=1)
        self.root.columnconfigure(0, weight=1)
        self.tabs = {}
        self.content = tk.Frame(self.root, bg=BG)
        self.content.grid(row=0, column=0, sticky="nsew")
        self.status_bar = tk.Frame(self.content, bg=BG)
        self.status_bar.pack(side="bottom", fill="x", padx=18, pady=(4, 8))
        self.status = label(self.status_bar, textvariable=self.page_state, color=MUTED, size=9)
        self.status.pack(side="left")
        self.progress = ttk.Progressbar(self.status_bar, length=134, mode="determinate", maximum=100)
        self.stage = tk.Frame(self.content, bg=BG)
        self.stage.pack(fill="both", expand=True)
        self.page = tk.Frame(self.stage, bg=BG)
        self.scroll = None   # the ScrollPage shown, if any
        self.header = self.view = self.side = None   # a sub-screen's header, its page object, what stands beside it
        for event in ("<MouseWheel>", "<Button-4>", "<Button-5>"):
            self.root.bind_all(event, lambda e: self.scroll and self.scroll.wheel(e))
        self.root.bind_all("<FocusIn>", lambda e: self.scroll and self.scroll.reveal(e), add="+")
        self.root.bind("<Escape>", lambda _e: self.show("Home") if self.active_page != "Home" else None)
        self.root.bind("<F11>", lambda _e: self.root.attributes("-fullscreen", not self.root.attributes("-fullscreen")))
        self.root.bind("<Control-Tab>", lambda _e: self.next_tab(1))
        self.root.bind("<Control-Shift-Tab>" if WINDOWS else "<Control-ISO_Left_Tab>", lambda _e: self.next_tab(-1))

    TABS = (("Graphics", "GRAPHICS"), ("Controls", "CONTROLS"), ("Settings", "GENERAL"))
    SETTINGS_PAGES = {"Graphics": GraphicsPage, "Controls": ControlsPage, "Settings": GeneralPage}
    SUBSCREENS = {"Profiles": "PROFILES", "Support": "HELP"}

    def next_tab(self, direction):
        names = [name for name, _ in self.TABS]
        if self.active_page in names:
            self.show(names[(names.index(self.active_page) + direction) % len(names)])
        return "break"

    def show(self, name):
        self.flush()
        for row in getattr(getattr(self.view, "rows", None), "items", ()):   # what is being typed is not lost
            if isinstance(row, TextRow):
                row.keep()
        self.active_page = name
        self.scroll = self.header = self.view = self.side = None
        for child in self.stage.winfo_children():
            child.destroy()
        self.demo = None
        if name != "Home":   # a sub-screen: the title screen's header strip, its tabs, then the page itself
            settings = name in self.SETTINGS_PAGES
            self.header = HeaderStrip(self.stage, "SETTINGS" if settings else self.SUBSCREENS[name], self.TABS if settings else (), name,
                                      on_tab=self.show, on_back=lambda: self.show("Home"), on_down=self.focus_page)
            self.header.pack(fill="x")
            if settings:   # rows on the left, what the selected one does on the right
                self.note_bar = tk.Frame(self.stage, bg=BG)
                self.note_bar.pack(fill="x", padx=px(34), pady=(px(12), 0))
                body = tk.Frame(self.stage, bg=BG)
                body.pack(fill="both", expand=True, padx=(px(34), px(20)), pady=(px(6), 0))
                self.side = tk.Frame(body, bg=BG, width=px(300))
                self.side.pack(side="right", fill="y", padx=(px(22), 0))
                self.side.pack_propagate(False)
            else:
                body = self.stage
            self.scroll = ScrollPage(body)
            self.scroll.pack(side="left" if settings else "top", fill="both", expand=True,
                             padx=0 if settings else (px(34), px(20)), pady=0 if settings else (px(14), 0))
            self.page = self.scroll.body
            if settings:
                self.view = self.SETTINGS_PAGES[name](self)
                return
            self.header.focus_set()
        else:
            self.page = tk.Frame(self.stage, bg=BG)
            self.page.pack(fill="both", expand=True)
        if name == "Home" and self.job and self.demo_title:   # a long task: its demo screen, fed by poll_job
            self.demo = DemoScreen(self.page, title=self.demo_title)
            self.demo.pack(fill="both", expand=True)
            self.demo.set_progress(*self.demo_state)
            label(self.page, "You can keep using the other pages; this screen comes back on Home.", color=MUTED, size=9).pack(anchor="w", pady=(8, 0))
            return
        getattr(self, {"Home": "home", "Profiles": "profile_page", "Support": "support_page"}[name])()

    def refresh(self):
        """The page again, as the state is now; on a page of rows, where the player was."""
        rows = getattr(self.view, "rows", None)
        if not rows:
            self.show(self.active_page)
            return
        chosen, place = rows.selected and rows.selected.caption, self.scroll.view.yview()[0]
        self.show(self.active_page)
        self.root.update_idletasks()
        self.view.rows.choose(chosen)
        self.scroll.view.yview_moveto(place)

    def heading(self, title, subtitle):
        label(self.page, title, size=23, bold=True, font_family=self.heading_font).pack(anchor="w")
        label(self.page, subtitle, color=MUTED).pack(anchor="w", pady=(1, 14))

    def home(self):
        """The title screen: its menu holds places, its chips the state, its card what needs the player."""
        shaders = shader_preparation(self.game, self.profiles) if self.game else None
        busy = bool(self.process or self.job)
        act = lambda f: (lambda: self.action(f))
        places = [("SETTINGS", "Graphics, controls, general", lambda: self.show("Graphics"), True),
                  ("PROFILES", "Saves and settings per player", lambda: self.show("Profiles"), True),
                  ("HELP", "Game files, report a problem, logs, about", lambda: self.show("Support"), True),
                  ("QUIT", "", self.close, True)]
        if self.game:
            menu = [("PLAY", "The game is running" if self.process else "Start the game · two players: plug in a second controller",
                     act(self.play), not busy), *places]
        else:
            menu = [("INSTALL ORBITALS", "From your own game files: about 20 to 60 minutes, once", act(self.install_game), not busy),
                    ("USE AN INSTALLATION", "A folder this launcher or the setup script already made", act(self.locate), not busy),
                    places[0], *places[2:]]
        outdated = bool(self.game and outdated_release(self.game))
        files = lambda: self.show("Support")
        if self.game:
            game_tag = ("GAME", "RUNNING" if self.process else ("OUTDATED" if outdated else "READY"),
                        PEACH if outdated and not self.process else CYAN, files)
        else:
            game_tag = ("GAME", "PROBLEM" if self.notice else "NOT INSTALLED", PEACH, files)
        shader_tag = ("SHADERS", f"{shaders.get('validated', 0):,} READY".replace(",", " ") if shaders else "NOT PREPARED",
                      CYAN if shaders else PEACH, files)
        tags = [game_tag, *((shader_tag,) if self.game else ()), ("PROFILE", self.profiles.profile["name"], RED, lambda: self.show("Profiles"))]
        pads = (*self.pads_line(), lambda: self.show("Controls")) if self.pad_names is not None else None
        TitleScreen(self.page, menu, tags, subtitle="A cooperative adventure in space", card=self.card(), pads=pads,
                    footer=f"Arrows, Enter: choose  ·  F11: full screen  ·  v{VERSION}", still=lambda: self.process is not None,
                    animate=bool(self.profiles.data.get("animate", True))).pack(fill="both", expand=True)

    def locate(self):
        self.guard()
        path = filedialog.askdirectory(parent=self.root, title="Folder with the native Orbitals build")
        if not path:
            return
        detected = installation(Path(path), template=True)
        self.template = detected
        try:
            detected = installation(detected.root)
        except (LauncherError, OSError):
            self.fail("The game's data is missing", "Build found. Prepare the ExeFS / RomFS data to enable Play.")
            self.refresh()
            return
        self.set_game(detected)

    def set_game(self, game):
        self.profiles.update(install=str(game.root))
        self.game = self.template = game
        self.notice = None
        self.page_state.set("Local installation checked")
        LOG.info("event=install_selected version_detected=%s", bool(game.version))
        self.refresh()

    def prepare_game(self):
        self.guard()
        if self.template is None:
            raise LauncherError("First locate a native build with its compiled ExeFS.")
        path = filedialog.askdirectory(parent=self.root, title="Extracted folder with exefs and romfs")
        if not path:
            return
        template = self.template
        self.background("Preparing the data…", 
                        lambda: prepare(Path(path), template, self.local / "installs",
                                        lambda done, total: self.events.put(("progress", (done, total)))),
                        self.set_game, demo="PREPARING GAME DATA")

    def install_game(self):
        """Recompile the selected ExeFS and prepare a playable installation."""
        self.guard()
        path = filedialog.askdirectory(parent=self.root, title="Folder extracted from your copy (with exefs and romfs)")
        if not path:
            return
        tools = ("Windows setup downloads the build tools from their official servers and checks their SHA-256."
                 if WINDOWS else "Linux setup uses GCC, SPIRV-Tools and the .NET 10 runtime installed on this PC. See BUILDING.md for the dependencies.")
        if not messagebox.askokcancel("Install Orbitals", f"{tools}\n\n"
                "Installation recompiles your copy locally. Allow 20 to 60 minutes and keep the selected game folder in place. "
                "The installation links to its ExeFS and RomFS.\n\nContinue?", parent=self.root):
            return
        self.background("Installing…", 
                        lambda: install_from_files(Path(path), on_progress=lambda s, n, t: self.events.put(("progress", (s, n, t)))),
                        self.installed, demo="RECOMPILING ORBITALS", retry=self.install_game)

    def installed(self, game):
        self.set_game(game)
        self.page_state.set("Installation finished: Orbitals is ready to play.")
        if messagebox.askyesno("Liftoff", "Installation finished.\n\n" + SHADER_PREP_TEXT + "\n\nPrepare the shaders now?",
                               parent=self.root):
            self.prepare_shaders(confirm=False)

    def shader_state_text(self):
        info = shader_preparation(self.game, self.profiles) if self.game else None
        if not info:
            return ("Shaders: not prepared. Without preparation, the first session translates each shader the first time it is "
                    "used and the picture pauses for it.")
        failed = f", {info['failed']} not supported by the translator" if info.get("failed") else ""
        return (f"Shaders: {info.get('validated', 0):,} prepared and validated of {info['discovered']:,}{failed} "
                f"({info.get('at', '')[:10]}, {info.get('seconds', 0) / 60:.0f} min). Vulkan pipelines are still built by the "
                "graphics driver the first time a scene uses them.").replace(",", " ")

    def prepare_shaders(self, confirm=True, then=None):
        self.guard()
        if not self.game:
            raise LauncherError("Locate an installation.")
        if confirm and not messagebox.askokcancel("Prepare shaders", SHADER_PREP_TEXT + "\n\nContinue?", parent=self.root):
            return
        game, profiles = self.game, self.profiles
        self.background("Preparing shaders…", 
                        lambda: prepare_shaders(game, profiles, on_progress=lambda event: self.events.put(("progress", event))),
                        lambda summary: self.shaders_prepared(summary, then), demo="PREPARING SHADERS",
                        retry=lambda: self.prepare_shaders(confirm=False, then=then))

    def shaders_prepared(self, summary, then=None):
        failed = summary.get("failed", 0)
        self.page_state.set(f"Shaders prepared: {summary.get('validated', 0):,} validated, {failed} not supported."
                            .replace(",", " "))
        self.refresh()
        if then:
            then()

    def background(self, status, worker, complete, demo=None, retry=None):
        """One job at a time. A job with a demo is a long one: if it fails, the title screen says so and offers `retry`."""
        self.guard()
        self.notice, self.retry = None, retry
        self.page_state.set(status)
        self.demo_title = demo; self.demo_state = (0.0, status.rstrip("…"), "")
        self.progress.configure(value=0)
        self.progress.pack(side="right")
        self.job = complete

        def work():
            try:
                self.events.put(("done", worker()))
            except Exception as error:
                self.events.put(("error", error))

        threading.Thread(target=work, daemon=True).start()
        if demo or self.active_page == "Home":   # (its entries are disabled while the job runs)
            self.show("Home")
        self.root.after(90, self.poll_job)

    def poll_job(self):
        progress = None
        while True:
            try:
                kind, value = self.events.get_nowait()
            except queue.Empty:
                break
            if kind == "progress":
                progress = value
                continue
            complete, self.job = self.job, None
            self.progress.pack_forget()
            title, self.demo_title = self.demo_title, None
            if kind == "error":
                self.page_state.set("The operation failed.")
                LOG.error("event=background_failed type=%s", type(value).__name__)
                self.copy_from(value)
                if title:
                    self.fail(f"{title.capitalize()} failed", str(value), *((("Try again", self.retry),) if self.retry else ()),
                              ("Open logs", lambda: open_folder(self.local / "logs")))
                    self.show("Home")
                else:
                    self.refresh()   # (Home's entries are enabled again)
                    messagebox.showerror("Liftoff", str(value), parent=self.root)
            else:
                self.page_state.set("")
                if self.active_page == "Home":   # also after a job without a demo: its entries are enabled again
                    self.show("Home")
                self.action(lambda: complete(value))
            return
        if isinstance(progress, dict):   # prepare_shaders: nxs_prepare.py's events
            value = shader_progress(progress); text = shader_progress_text(progress)
            self.progress.configure(value=value)
            self.page_state.set(text[:150])
            self.demo_state = (value / 100, "Preparing shaders", text[:120])
        elif progress and len(progress) == 3:   # install_from_files: step, steps, last line
            step, total, text = progress
            value = max(self.demo_state[0] * 100 if self.demo_title else 0, 100 * install_fraction(step, total, text))   # never backwards
            self.progress.configure(value=value)
            self.page_state.set(f"Installation · step {step}/{total} · {text}"[:150])
            self.demo_state = (value / 100, f"Step {step}/{total}", str(text)[:120])
        elif progress:
            done, total = progress
            self.progress.configure(value=100 * done / max(1, total))
            self.page_state.set(f"Preparing · {done / 2**30:.2f} / {total / 2**30:.2f} GiB")
            self.demo_state = (done / max(1, total), "Preparing game data", f"{done / 2**30:.2f} / {total / 2**30:.2f} GiB")
        if progress is not None and self.demo is not None:
            try:
                self.demo.set_progress(*self.demo_state)
            except tk.TclError:
                self.demo = None
        self.root.after(90, self.poll_job)

    def play(self):
        self.guard()
        if not self.game:
            raise LauncherError("Locate an installation.")
        if (not shader_preparation(self.game, self.profiles) and not self.profiles.data.get("shader_prep_declined")):
            answer = messagebox.askyesnocancel("Prepare shaders", SHADER_PREP_TEXT + "\n\nPrepare them before playing? "
                                               "(No: play now and translate them during the session.)", parent=self.root)
            if answer is None:
                return
            if answer:
                self.prepare_shaders(confirm=False, then=self.play)
                return
            self.profiles.update(shader_prep_declined=True)
        self.background("Starting Orbitals…", lambda: launch(self.game, self.profiles), self.started)

    def started(self, result):
        self.process, self.run = result
        self.page_state.set("Orbitals is running.")
        self.refresh()
        self.root.after(500, self.poll_game)

    def poll_game(self):
        code = self.process.poll()
        if code is None:
            self.root.after(500, self.poll_game)
            return
        run = self.run
        self.process = self.run = None
        finish_session(run, code, self.profiles)
        self.page_state.set("Session finished." if code == 0 else f"Unexpected stop · code {code}")
        if code:
            self.fail("Orbitals stopped unexpectedly", f"Exit code {code}. The logs of this session are available for a report.",
                      ("Report it", self.report), ("Open logs", lambda: open_folder(run)))
        self.refresh()

    def profile_page(self):
        self.heading("Profiles", "Each profile has its own settings and save folder.")
        card = surface(self.page)
        card.pack(fill="x", pady=(0, 14))
        rows = tk.Frame(card, bg=PANEL)
        rows.pack(fill="x", padx=14, pady=12)
        names = {item["name"]: key for key, item in self.profiles.entries.items()}
        selected = tk.StringVar(value=self.profiles.profile["name"])
        label(rows, "Active profile", bg=PANEL, bold=True).pack(side="left", padx=(0, 12))
        picker = ttk.Combobox(rows, textvariable=selected, values=tuple(names), state="readonly", width=19)
        picker.pack(side="left", padx=(0, 10))

        def select():
            self.guard()
            self.profiles.select(names[selected.get()])
            self.refresh()

        picker.bind("<<ComboboxSelected>>", lambda _: self.action(select))
        self.button(rows, "Create", lambda: self.name_profile(False)).pack(side="left", padx=(0, 6))
        self.button(rows, "Rename", lambda: self.name_profile(True)).pack(side="left", padx=(0, 6))
        self.button(rows, "Delete…", self.archive_profile).pack(side="left")
        label(self.page, "Saves", bold=True, size=15).pack(anchor="w", pady=(8, 5))
        for title, help_text, button, callback in (
            ("Active folder", "Files saved by the recomp.", "Open", lambda: open_folder(self.profiles.saves)),
            ("Backup copy", "A timestamped copy in the active profile.", "Create a copy",
             lambda: self.save_operation(self.profiles.backup)),
            ("Import or restore", "Select a save folder or a copy made by the launcher.",
             "Choose a folder", self.restore),
            ("Export", "Copy the profile files to another folder.", "Export", self.export),
        ):
            row = surface(self.page, RAIL)
            row.pack(fill="x", pady=(0, 7))
            self.button(row, button, callback).pack(side="right", padx=11, pady=7)
            labels = tk.Frame(row, bg=RAIL)
            labels.pack(fill="x", padx=12, pady=7)
            label(labels, title, bg=RAIL, bold=True).pack(anchor="w")
            label(labels, help_text, bg=RAIL, color=MUTED, size=9, wraplength=402).pack(anchor="w")

    def name_profile(self, rename):
        self.guard()
        label_text = "Rename the profile" if rename else "New profile"
        name = simpledialog.askstring(label_text, "Name", parent=self.root,
                                      initialvalue=self.profiles.profile["name"] if rename else "")
        if name is not None:
            (self.profiles.rename if rename else self.profiles.create)(name)
            self.refresh()

    def archive_profile(self):
        self.guard()
        if messagebox.askyesno("Delete the profile", "Remove this profile from the list and archive its files?",
                               parent=self.root):
            self.profiles.archive()
            self.refresh()

    def save_operation(self, operation):
        self.background("Copying the saves…", operation,
                        lambda path: self.page_state.set(f"Copy finished · {path.name}"))

    def restore(self):
        self.guard()
        path = filedialog.askdirectory(parent=self.root, title="Folder to import into the active profile")
        if path and messagebox.askyesno("Restore the save",
                                        "Replace the active files after keeping a copy of them?",
                                        parent=self.root):
            self.save_operation(lambda: self.profiles.restore(Path(path)))

    def export(self):
        self.guard()
        path = filedialog.askdirectory(parent=self.root, title="Destination folder")
        if path:
            self.save_operation(lambda: self.profiles.export(Path(path)))

    def support_page(self):
        self.heading("Support", "Read the logs or prepare a diagnostic report.")
        panel = surface(self.page)
        panel.pack(fill="x", pady=(0, 13))
        label(panel, "Report a problem", bg=PANEL, size=17, bold=True).pack(anchor="w", padx=15, pady=(12, 3))
        label(panel, "Create a local ZIP to check before attaching it to a GitHub issue.", color=MUTED,
              bg=PANEL, wraplength=500).pack(anchor="w", padx=15)
        self.button(panel, "Create a report", self.report, style="Play.TButton").pack(anchor="w", padx=15, pady=13)
        files = tk.Frame(self.page, bg=BG)   # what the title screen leaves out: the installation's own actions
        files.pack(fill="x", pady=(0, 13))
        label(files, "Game files", color=MUTED, size=9, bold=True).pack(side="left", padx=(0, 10))
        if self.game and outdated_release(self.game):
            self.button(files, "Update the game", self.recompile_game).pack(side="left", padx=(0, 6))
        if self.game:
            self.button(files, "Reinstall from my files", self.install_game).pack(side="left", padx=(0, 6))
        self.button(files, "Use another installation", self.locate).pack(side="left", padx=(0, 6))
        if self.game:
            self.button(files, "Open the game folder", lambda: open_folder(self.game.root)).pack(side="left", padx=(0, 6))
            self.button(files, "Prepare shaders again", self.prepare_shaders).pack(side="left")
        detected = runtime_info((latest_run(self.profiles), self.game.root if self.game else None)) if self.game else None
        about = surface(self.page)   # the technical details the Home page no longer shows
        about.pack(fill="x", pady=(0, 13))
        label(about, "About this installation", bg=PANEL, bold=True).pack(anchor="w", padx=15, pady=(10, 2))
        lines = [f"Launcher {VERSION}"]
        if self.game:
            lines.append("Game build " + self.game.ids["main"][:16] + (f" ({self.game.version})" if self.game.version else ""))
            lines.append(str(self.game.root))
        if detected:
            lines.append("Runtime " + " ".join(filter(None, (detected.get("release"), detected.get("commit")))) if detected.get("release")
                         else "Recomp " + detected.get("recomp_version", "?"))
        label(about, "\n".join(lines), bg=PANEL, color=MUTED, size=9).pack(anchor="w", padx=15, pady=(0, 10))
        # (prepare_game: another copy of the same game version paired with a build already recompiled here, a development
        # shortcut: not shown to players, "Install Orbitals" does the whole thing)
        for title, callback in (("Last session", lambda: open_folder(
                latest_run(self.profiles) or (self.game.root if self.game else self.local / "logs"))),
                ("Launcher logs", lambda: open_folder(self.local / "logs")),
                ("Saves", lambda: open_folder(self.profiles.saves)),
                ("Reports folder", self.open_reports),
                ("Issues GitHub", self.issues), ("System information", self.inspect_system)):
            self.button(self.page, title, callback).pack(anchor="w", pady=(0, 5))

    def open_reports(self):
        directory = self.local / "reports"
        directory.mkdir(parents=True, exist_ok=True)
        open_folder(directory)

    def issues(self):
        url = self.profiles.data.get("issues")
        if not url or not re.fullmatch(r"https://github\.com/[\w.-]+/[\w.-]+/issues", url):
            raise LauncherError("Set the issues URL in Settings.")
        webbrowser.open(url)

    def inspect_system(self):
        self.background("Reading the system information…",
                        lambda: {"System": system_info(), "Vulkan": gpu_info(),
                                 "Recomp": runtime_info((latest_run(self.profiles),
                                                         self.game.root if self.game else None))},
                        lambda info: show_text(self.root, "System information", json_bytes(info).decode()))

    def report(self):
        self.guard()
        ReportForm(self)

    def close(self):
        if self.job or self.process:
            messagebox.showinfo("Liftoff", "Close the game first or wait for the operation to finish.",
                                parent=self.root)
            return
        self.action(self.flush)
        self.root.destroy()
