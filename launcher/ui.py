# SwitchRecomp - Copyright 2026 MZ Labs

import os
import queue
import re
import subprocess
import threading
import tkinter as tk
import webbrowser
from pathlib import Path
from tkinter import filedialog, ttk

from . import VERSION, dialogs
from .core import (DEFAULT_SETTINGS, LOG, REPO, WINDOWS, LauncherError, Profiles, carry_saves, check_update, detect_installation,
                   download_update, finish_session, game_source, install_fraction, install_from_files, installation, json_bytes,
                   latest_run, launch, launch_kit, outdated_release, prepare_shaders, runtime_info, setup_log, shader_preparation,
                   source_lacks, validate_settings)
from .demo import DemoScreen
from .look import BG, CYAN, MUTED, PEACH, RED, ScrollPage, label, px, theme
from .navigation import Navigation, wanted
from .neo import Card, HeaderStrip, TitleScreen
from .pads import Pads
from .page_files import FilesPage
from .page_settings import REMOVED, ControlsPage, GeneralPage, GraphicsPage
from .page_tools import ProfilesPage, ToolsPage
from .report_form import ReportForm, show_text
from .reports import gpu_info, system_info
from .rows import TextRow
from .shader_text import SHADER_PREP_TEXT, shader_progress, shader_progress_text
from .tasks import Pace, Stopped, Task, counted


def open_folder(path):
    if not path.is_dir():
        raise LauncherError("This folder appears after the first session.")
    if WINDOWS:
        os.startfile(path)
    else:
        subprocess.Popen(["xdg-open", str(path)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def spoken(title, first=True):
    """A demo's title ("RECOMPILING ORBITALS") in a sentence."""
    title = title.lower().replace("orbitals", "Orbitals")
    return title[0].upper() + title[1:] if first else title


class Launcher:
    version = VERSION
    spoken = staticmethod(spoken)

    def __init__(self, root, local, selected=None):
        self.root = root
        self.local = local
        self.profiles = Profiles(local)
        self.game = None
        self.notice = None           # a Card the title screen shows until it is dismissed (a failure)
        self.update_info = self.update_kit = None; self.update_answer = ""; self.update_later = False
        self.retry = None            # what starts the running job again, if it fails
        self.task, self.stoppable, self.pace = Task(), False, Pace()   # the running job's stop switch and time left (tasks.py)
        self.install_step = None     # of the installation that runs
        self.setup_open = self.closing = False
        self.job_bar = None
        self.job = None
        self.process = None
        self.run = None
        self.active_page = "Home"
        self.demo = None; self.demo_title = None; self.demo_state = (0.0, "", "")   # the demo screen of a long task (demo.py)
        self.page_state = tk.StringVar()
        self.events = queue.Queue()
        self.calls = queue.Queue()   # functions other threads want run on this one (post)
        self.pending = {}            # settings changed and not written yet (keep, flush)
        self.flush_timer = self.game_timer = None
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
        LOG.info("event=detect ready=%s", self.game is not None)
        self.pads = Pads([*((self.game.root,) if self.game else ()), REPO / "bin"])
        self.pad_names = None
        self.pads_timer = root.after(50, self.watch_pads)
        self.navigation = Navigation(self)
        self.navigation.tick()
        self.build_shell()
        self.show("Home")
        self.pump()
        if self.profiles.data.get("update_check", True):   # on unless turned off in Settings; one request to GitHub's releases API
            threading.Thread(target=lambda: self.update_result(quiet=True), daemon=True).start()

    def closed(self, event):
        if event.widget is self.root:
            for timer in filter(None, (self.pump_timer, self.pads_timer, self.flush_timer, self.navigation.timer, self.game_timer)):
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
                screen.set_pads(*self.pads_line(), self.keys_line())
        self.pads_timer = self.root.after(1000, self.watch_pads)

    def pads_line(self):
        names = self.pad_names or []
        if not names:
            return "No controller connected", False
        more = f" and {len(names) - 2} more" if len(names) > 2 else ""
        return (f"{len(names)} controllers: " if len(names) > 1 else "") + ", ".join(names[:2]) + more, True

    def keys_line(self):
        pads = self.pad_names and wanted(self.profiles.data.get("pad_navigation", "auto"))
        return ("A: choose  ·  Start: play" if pads else "Arrows, Enter: choose  ·  F11: full screen") + f"  ·  v{VERSION}"

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
        self.pump_timer = self.root.after(90, self.pump)   # (first: a function can open a dialog, which waits)
        while True:
            try:
                function = self.calls.get_nowait()
            except queue.Empty:
                break
            self.action(function)

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

    @staticmethod
    def open_folder(path):
        open_folder(path)

    @staticmethod
    def open_file(path):
        if not path.is_file():
            raise LauncherError("There is no such file yet.")
        if WINDOWS:
            os.startfile(path)
        else:
            subprocess.Popen(["xdg-open", str(path)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    def focus_header(self):
        if self.header:
            self.header.focus_set()

    def focus_main(self):
        """Nothing has the focus: what a page gives it to when it opens."""
        screen = self.title_screen()
        if dialogs.open_dialogs:
            dialogs.open_dialogs[-1].refocus()
        elif screen:
            screen.focus_set()
        elif self.header:
            self.focus_page()
        else:   # a job's demo
            self.stop_button.focus_set()

    def focus_page(self):
        """From the header down to the page: its selected row, or its first widget."""
        rows = getattr(self.view, "rows", None)
        if rows and rows.selected:
            rows.selected.focus_set()
        elif getattr(self.view, "first", None):
            self.view.first.focus_set()
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
        self.install_step = 1

        def done(game):
            try:
                if carry_saves(old, game):
                    self.page_state.set("Saves copied from the previous installation.")
            except OSError as error:
                dialogs.error(self.root, "Saves", f"The saves could not be copied ({error}). They are still in {old.saves}.")
            self.installed(game)

        self.background("Recompiling…",
                        lambda: install_from_files(source, on_progress=lambda s, n, t: self.events.put(("progress", (s, n, t))),
                                                   rebuild=in_place, task=self.task),
                        done, demo="RECOMPILING ORBITALS", retry=self.recompile_game, stoppable=True)

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
                        lambda: download_update(info, on_progress=lambda d, t: self.events.put(("progress", (d, t))), task=self.task),
                        self.update_ready, demo="DOWNLOADING UPDATE", retry=self.download_update, stoppable=True)

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
        dialogs.error(self.root, "Something went wrong", str(error) or error_type.__name__)

    def action(self, callback):
        try:
            callback()
        except (OSError, LauncherError, subprocess.SubprocessError, tk.TclError) as error:
            LOG.error("event=action_failed type=%s", type(error).__name__)
            self.copy_from(error)
            dialogs.error(self.root, "That did not work", str(error))

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
        for key, x, y in (("<Left>", -1, 0), ("<Right>", 1, 0), ("<Up>", 0, -1), ("<Down>", 0, 1)):
            button.bind(key, lambda e, x=x, y=y: dialogs.toward(button, x, y, button.winfo_toplevel()) and "break")
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
    ROWS_PAGES = SETTINGS_PAGES | {"Profiles": ProfilesPage, "Tools": ToolsPage}
    SUBSCREENS = {"Profiles": "PROFILES", "Files": "GAME FILES", "Tools": "TOOLS"}

    def next_tab(self, direction):
        if dialogs.open_dialogs:
            return "break"
        names = [name for name, _ in self.TABS]
        if self.active_page in names:
            self.show(names[(names.index(self.active_page) + direction) % len(names)])
        return "break"

    def show(self, name):
        self.build(name)
        self.keep_dialog()

    @staticmethod
    def keep_dialog():
        """A job ended under a question: the question keeps the keys."""
        if dialogs.open_dialogs:
            dialogs.open_dialogs[-1].refocus()

    def build(self, name):
        self.flush()
        for row in getattr(getattr(self.view, "rows", None), "items", ()):   # what is being typed is not lost
            if isinstance(row, TextRow):
                row.keep()
        self.active_page = name
        self.scroll = self.header = self.view = self.side = self.job_bar = None
        for child in self.stage.winfo_children():
            child.destroy()
        self.demo = None
        if name != "Home":   # a sub-screen: the title screen's header strip, its tabs, then the page itself
            settings, rows = name in self.SETTINGS_PAGES, name in self.ROWS_PAGES
            self.header = HeaderStrip(self.stage, "SETTINGS" if settings else self.SUBSCREENS[name], self.TABS if settings else (), name,
                                      on_tab=self.show, on_back=lambda: self.show("Home"), on_down=self.focus_page)
            self.header.pack(fill="x")
            if rows:   # rows on the left, what the selected one does on the right
                self.note_bar = tk.Frame(self.stage, bg=BG, height=px(1))
                self.note_bar.pack(fill="x", padx=px(34), pady=(px(12), 0))
                body = tk.Frame(self.stage, bg=BG)
                body.pack(fill="both", expand=True, padx=(px(34), px(20)), pady=(px(6), 0))
                self.side = tk.Frame(body, bg=BG, width=px(300))
                self.side.pack(side="right", fill="y", padx=(px(22), 0))
                self.side.pack_propagate(False)
            else:
                body = self.stage
            self.scroll = ScrollPage(body)
            self.scroll.pack(side="left" if rows else "top", fill="both", expand=True,
                             padx=0 if rows else (px(34), px(20)), pady=0 if rows else (px(16), 0))
            self.page = self.scroll.body
            self.header.focus_set()
            self.view = (self.ROWS_PAGES[name] if rows else FilesPage)(self)
            return
        self.page = tk.Frame(self.stage, bg=BG)
        self.page.pack(fill="both", expand=True)
        if self.job and self.demo_title:   # a long task: its demo screen, fed by poll_job
            self.build_job_bar()
            self.demo = DemoScreen(self.page, title=self.demo_title)
            self.demo.pack(fill="both", expand=True)
            self.demo.set_progress(*self.demo_state)
        else:
            self.home()

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
        self.keep_dialog()

    def build_job_bar(self):
        """Under a long task's demo: its time, the other pages, and Stop."""
        bar = tk.Frame(self.page, bg=BG)
        bar.pack(side="bottom", fill="x", padx=px(18), pady=(px(8), 0))
        self.stop_button = stop = self.button(bar, "Stopping…" if self.task.stopped else "Stop", self.stop_job)
        stop.pack(side="right")
        if not self.stoppable or self.task.stopped:
            stop.state(["disabled"])
        for title, page in (("Tools", "Tools"), ("Settings", "Graphics"), ("Game files", "Files")):
            self.button(bar, title, lambda page=page: self.show(page)).pack(side="right", padx=(0, px(8)))
        self.job_bar = label(bar, self.pace.text(), color=MUTED)
        self.job_bar.pack(side="left")
        stop.focus_set()

    def home(self):
        """The title screen: its menu holds places, its chips the state, its card what needs the player."""
        shaders = shader_preparation(self.game, self.profiles) if self.game else None
        busy = bool(self.process or self.job)
        go = lambda page: (lambda: self.show(page))
        files = go("Files")
        settings, tools = ("SETTINGS", "Graphics, controls, general", go("Graphics"), True), ("TOOLS", "Steam, updates, reports, logs", go("Tools"), True)
        if self.game:
            menu = [("PLAY", "The game is running" if self.process else "Start the game · two players: plug in a second controller",
                     lambda: self.action(self.play), not busy), settings, ("PROFILES", "Saves and settings per player", go("Profiles"), True),
                    ("GAME FILES", "What is installed, shaders", files, True), tools]
        else:
            menu = [("SET UP ORBITALS", "From your own copy: about 20 to 60 minutes, once", files, True), settings, tools]
        menu.append(("QUIT", "", self.close, True))
        outdated = bool(self.game and outdated_release(self.game))
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
                    footer=self.keys_line(), still=lambda: self.process is not None,
                    animate=bool(self.profiles.data.get("animate", True))).pack(fill="both", expand=True)

    def locate(self):
        self.guard()
        path = filedialog.askdirectory(parent=self.root, title="Folder with the native Orbitals build")
        if path:
            self.set_game(installation(Path(path)))

    def set_game(self, game):
        self.profiles.update(install=str(game.root))
        self.game = game
        self.notice = None
        self.page_state.set("Local installation checked")
        LOG.info("event=install_selected version_detected=%s", bool(game.version))
        self.refresh()

    def source(self):
        """The folder of the player's copy: the one chosen, else the one the installation was made from."""
        chosen = self.profiles.data.get("source")
        return Path(chosen) if chosen else (game_source(self.game) if self.game else None)

    def set_source(self, path):
        """A folder chosen as the copy; its only folder that is one, when it holds that instead."""
        path = Path(path)
        if source_lacks(path):
            inside = [child for child in path.iterdir() if child.is_dir() and not source_lacks(child)]
            if len(inside) == 1:
                path = inside[0]
        self.profiles.update(source=str(path))

    def start_install(self):
        """Recompile the chosen copy and prepare a playable installation."""
        self.guard()
        source = self.source()
        if source is None:
            raise LauncherError("Choose the folder extracted from your copy first.")
        self.install_step = 1
        self.background("Installing…",
                        lambda: install_from_files(source, on_progress=lambda s, n, t: self.events.put(("progress", (s, n, t))), task=self.task),
                        self.installed, demo="RECOMPILING ORBITALS", retry=self.start_install, stoppable=True)

    def installed(self, game):
        self.set_game(game)
        self.setup_open = False
        self.page_state.set("Installation finished: Orbitals is ready to play.")
        if self.active_page == "Files":
            self.show("Home")   # (its card offers to prepare the shaders)

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
        if confirm and not dialogs.confirm(self.root, "Prepare shaders", SHADER_PREP_TEXT, yes="Prepare"):
            return
        game, profiles = self.game, self.profiles
        self.background("Preparing shaders…", 
                        lambda: prepare_shaders(game, profiles, on_progress=lambda event: self.events.put(("progress", event)), task=self.task),
                        lambda summary: self.shaders_prepared(summary, then), demo="PREPARING SHADERS",
                        retry=lambda: self.prepare_shaders(confirm=False, then=then), stoppable=True)

    def shaders_prepared(self, summary, then=None):
        failed = summary.get("failed", 0)
        self.page_state.set(f"Shaders prepared: {summary.get('validated', 0):,} validated, {failed} not supported."
                            .replace(",", " "))
        self.refresh()
        if then and not self.closing:
            then()

    def background(self, status, worker, complete, demo=None, retry=None, stoppable=False):
        """One job at a time. A job with a demo is a long one: if it fails, the title screen says so and offers `retry`. A stoppable
        one runs under self.task, made here."""
        self.guard()
        self.notice, self.retry = None, retry
        self.task, self.stoppable, self.pace = Task(), stoppable, Pace()
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
            self.install_step = None
            if kind == "error" and isinstance(value, Stopped):
                LOG.info("event=background_stopped")
                self.check_game()
                self.page_state.set(str(value))
                if self.closing:
                    self.root.destroy()
                    return
                self.refresh()
            elif kind == "error":
                self.page_state.set("The operation failed.")
                LOG.error("event=background_failed type=%s", type(value).__name__)
                if self.closing:
                    self.root.destroy()
                    return
                self.copy_from(value)
                if title:
                    log = setup_log() if "RECOMPIL" in title else None
                    self.fail(f"{spoken(title)} failed", str(value), *((("Try again", self.retry),) if self.retry else ()),
                              ("Open log", lambda: self.open_file(log)) if log and log.is_file() else
                              ("Open logs", lambda: open_folder(self.local / "logs")))
                    self.show("Files" if self.active_page == "Files" else "Home")
                else:
                    self.refresh()   # (Home's entries are enabled again)
                    dialogs.error(self.root, "That did not work", str(value))
            else:
                self.page_state.set("")
                if self.closing:   # it ended before it could be stopped: what it made is kept
                    self.action(lambda: complete(value))
                    self.root.destroy()
                    return
                self.refresh()   # also after a job without a demo: what it disabled is enabled again
                self.action(lambda: complete(value))
            return
        if isinstance(progress, dict):   # prepare_shaders: nxs_prepare.py's events
            value = shader_progress(progress); text = shader_progress_text(progress)
            if progress.get("phase") == "translate" and progress.get("todo"):
                self.pace.feed(progress.get("translated", 0) + progress.get("failed", 0), progress["todo"])
            self.progress.configure(value=value)
            self.page_state.set(text[:150])
            self.demo_state = (value / 100, "Preparing shaders", text[:120])
        elif progress and len(progress) == 3:   # install_from_files: step, steps, last line
            step, total, text = progress
            self.install_step = max(1, step)
            if counted(text):
                self.pace.feed(*counted(text))
            value = max(self.demo_state[0] * 100 if self.demo_title else 0, 100 * install_fraction(step, total, text))   # never backwards
            self.progress.configure(value=value)
            self.page_state.set(f"Installation · step {step}/{total} · {text}"[:150])
            self.demo_state = (value / 100, f"Step {step}/{total}", str(text)[:120])
        elif progress:
            done, total = progress
            self.pace.feed(done, total)
            self.progress.configure(value=100 * done / max(1, total))
            self.page_state.set(f"Downloading · {done / 2**20:.0f} / {total / 2**20:.0f} MB")
            self.demo_state = (done / max(1, total), "Downloading", f"{done / 2**20:.0f} / {total / 2**20:.0f} MB")
        if self.demo_title:
            if self.demo is not None and progress is not None:
                self.demo.set_progress(*self.demo_state)
            if self.job_bar is not None:
                self.job_bar.configure(text="Stopping at the end of this step…" if self.task.stopped else self.pace.text())
            if isinstance(self.view, FilesPage):
                self.view.progress()
        self.root.after(90, self.poll_job)

    def play(self):
        self.guard()
        if not self.game:
            raise LauncherError("Locate an installation.")
        if (not shader_preparation(self.game, self.profiles) and not self.profiles.data.get("shader_prep_declined")):
            answer = dialogs.choose(self.root, "Prepare the shaders first?", SHADER_PREP_TEXT, ("Prepare, then play", "Play now", "Cancel"))
            if answer in (None, 2):
                return
            if answer == 0:
                self.prepare_shaders(confirm=False, then=self.play)
                return
            self.profiles.update(shader_prep_declined=True)
        self.background("Starting Orbitals…", lambda: launch(self.game, self.profiles), self.started)

    def started(self, result):
        self.process, self.run = result
        self.pads.close()   # the controllers are the game's now
        self.page_state.set("Orbitals is running.")
        self.refresh()
        self.game_timer = self.root.after(500, self.poll_game)

    def poll_game(self):
        code = self.process.poll()
        if code is None:
            self.game_timer = self.root.after(500, self.poll_game)
            return
        run = self.run
        self.process = self.run = None
        finish_session(run, code, self.profiles)
        self.page_state.set("Session finished." if code == 0 else f"Unexpected stop · code {code}")
        if code:
            self.fail("Orbitals stopped unexpectedly", f"Exit code {code}. The logs of this session are available for a report.",
                      ("Report it", self.report), ("Open logs", lambda: open_folder(run)))
        self.refresh()

    def stop_job(self):
        """Stop the long job that runs; what it made so far is kept, and starting it again continues."""
        if not (self.job and self.stoppable) or self.task.stopped:
            return
        if dialogs.confirm(self.root, f"Stop {spoken(self.demo_title, False)}?", "What is done is kept: starting it again continues from there.",
                           yes="Stop", no="Go on") and self.job:
            self.task.stop()
            self.page_state.set("Stopping…")
            self.refresh()

    def check_game(self):
        """After a stop: is the installation still whole? An update stopped while it was being written has to be started again."""
        if self.game:
            try:
                self.game = installation(self.game.root)
            except (OSError, LauncherError) as error:
                self.game = None
                self.fail("The game is not complete", f"{error} Set it up again: it continues from where it stopped.",
                          ("Game files", lambda: self.show("Files")))

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
        if self.job and self.stoppable and not self.process:
            if dialogs.confirm(self.root, f"Stop {spoken(self.demo_title, False)} and close?", "What is done is kept.", yes="Stop and close",
                               no="Go on") and self.job:
                self.closing = True
                self.task.stop()
                self.page_state.set("Stopping, then closing…")
            elif not self.job:
                self.close()
            return
        if self.job or self.process:
            dialogs.message(self.root, "Not yet", "Close the game first, or wait for the operation to finish.")
            return
        self.action(self.flush)
        self.root.destroy()
