# SwitchRecomp - Copyright 2026 MZ Labs

import os
import queue
import re
import subprocess
import threading
import tkinter as tk
import webbrowser
from pathlib import Path
from tkinter import filedialog, font, messagebox, simpledialog, ttk

from . import VERSION, graphics
from .core import (LOG, RELEASES_URL, REPO, WINDOWS, LauncherError, Profiles, carry_saves, check_update, detect_installation,
                   download_update, finish_session, game_source, gamepad_inventory, graphics_settings, install_fraction,
                   install_from_files, installation, json_bytes, latest_run, launch, launch_kit, outdated_release, prepare,
                   prepare_shaders, runtime_info, shader_preparation, validate_settings)
from .demo import DemoScreen
from .look import BG, CYAN, INK, MUTED, PANEL, PEACH, RAIL, RED, ScrollPage, label, surface, theme
from .neo import TitleScreen, header_strip
from .report_form import ReportForm, show_text
from .reports import gpu_info, system_info
from .shader_text import SHADER_PREP_TEXT, shader_progress, shader_progress_text


def native_size(root):
    """The primary monitor's resolution in physical pixels (Windows: not the DPI-scaled size Tk reports), or None."""
    if WINDOWS:
        try:
            import ctypes
            user32 = ctypes.windll.user32
            dc = user32.GetDC(0)
            try:
                w, h = ctypes.windll.gdi32.GetDeviceCaps(dc, 118), ctypes.windll.gdi32.GetDeviceCaps(dc, 117)   # DESKTOPHORZRES, DESKTOPVERTRES
            finally:
                user32.ReleaseDC(0, dc)
            if w > 0 and h > 0:
                return w, h
        except (OSError, AttributeError):
            pass
    try:
        return root.winfo_screenwidth(), root.winfo_screenheight()
    except tk.TclError:
        return None


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
        self.error_text = ""
        self.job = None
        self.process = None
        self.run = None
        self.active_page = "Home"
        self.demo = None; self.demo_title = None; self.demo_state = (0.0, "", "")   # the demo screen of a long task (demo.py)
        self.page_state = tk.StringVar()
        self.events = queue.Queue()
        self.calls = queue.Queue()   # functions other threads want run on this one (post)
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
                self.error_text = str(error)
        else:
            self.game = detect_installation()
        self.template = self.game
        LOG.info("event=detect ready=%s", self.game is not None)
        self.build_shell()
        self.show("Home")
        self.pump()
        if self.profiles.data.get("update_check", True):   # on unless turned off in Settings; one request to GitHub's releases API
            threading.Thread(target=lambda: self.update_result(quiet=True), daemon=True).start()
        self.offer_timer = self.root.after(600, self.offer_recompile)

    def closed(self, event):
        if event.widget is self.root:
            for timer in (self.pump_timer, self.offer_timer):
                self.root.after_cancel(timer)

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

    def offer_recompile(self, asked_now=False):
        """A game compiled by an older release: say it once per (game release, launcher version), and from Play."""
        old = outdated_release(self.game) if self.game else None
        if not old or self.job:
            return False
        key = f"{old}->{VERSION}"
        if not asked_now and self.profiles.data.get("recompile_declined") == key:
            return False
        if messagebox.askyesno("Update the game",
                               f"Your game was compiled by version {old}; this launcher is {VERSION}.\n\n"
                               "Recompile it now to get the fixes and improvements of this version? It takes 20 to 60 minutes, "
                               "once. Your saves are kept, and the old installation is left as it is.", parent=self.root):
            self.action(self.recompile_game)
            return True
        self.profiles.update(recompile_declined=key)
        return False

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
                        done, demo="RECOMPILING ORBITALS")

    def update_result(self, quiet=False):
        """Runs on a worker thread: asks GitHub for the latest release and hands the answer to the Tk thread."""
        try:
            info, error = check_update(), None
        except LauncherError as err:
            info, error = None, str(err)
        self.post(lambda: self.show_update(info, error, quiet))

    def show_update(self, info, error, quiet):
        if error:
            if not quiet:
                messagebox.showwarning("Updates", error, parent=self.root)
            return
        if info is None:
            if not quiet:
                messagebox.showinfo("Updates", "No update repository is set in this version of the launcher.", parent=self.root)
            return
        if not info["newer"]:
            self.page_state.set(f"Launcher up to date (version {VERSION}).")
            if not quiet:
                messagebox.showinfo("Updates", f"You have the latest version ({VERSION}).", parent=self.root)
            return
        self.page_state.set(f"New version available: {info['latest']}")
        self.update_info = info
        if self.job:
            return
        answer = messagebox.askyesnocancel("Update available",
                                           f"Version {info['latest']} is available (you have {VERSION}).\n\n"
                                           "Download it now? It is checked (SHA-256) and unpacked beside this one; then the new "
                                           "launcher opens and offers to recompile your game. Your saves and this version stay "
                                           "as they are.\n\nNo: open the release page instead.", parent=self.root)
        if answer:
            self.action(self.download_update)
        elif answer is False:
            webbrowser.open(info["url"])

    def download_update(self):
        self.guard()
        info = self.update_info
        self.background(f"Downloading {info['latest']}…",
                        lambda: download_update(info, on_progress=lambda d, t: self.events.put(("progress", (d, t)))),
                        self.update_ready, demo="DOWNLOADING UPDATE")

    def update_ready(self, kit):
        self.page_state.set(f"Version {self.update_info['latest']} is ready in {kit}.")
        if messagebox.askyesno("Update ready", f"Version {self.update_info['latest']} is ready in:\n{kit}\n\n"
                               "Open it now? This window closes.", parent=self.root):
            launch_kit(kit)
            self.root.destroy()

    def callback_error(self, error_type, error, stack):
        LOG.error("event=ui_error type=%s", error_type.__name__)
        messagebox.showerror("Liftoff", str(error), parent=self.root)

    def action(self, callback):
        try:
            callback()
        except (OSError, LauncherError, subprocess.SubprocessError, tk.TclError) as error:
            self.error_text = str(error)
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
        for event in ("<MouseWheel>", "<Button-4>", "<Button-5>"):
            self.root.bind_all(event, lambda e: self.scroll and self.scroll.wheel(e))
        self.root.bind_all("<FocusIn>", lambda e: self.scroll and self.scroll.reveal(e), add="+")
        self.root.bind("<Escape>", lambda _e: self.show("Home") if self.active_page != "Home" else None)

    SUBSCREENS = {"Graphics": ("SETTINGS", "Graphics"), "Controls": ("SETTINGS", "Controls"), "Settings": ("SETTINGS", "Launcher"),
                  "Profiles": ("PROFILES", None), "Support": ("HELP", None)}

    def show(self, name):
        self.active_page = name
        self.scroll = None
        for child in self.stage.winfo_children():
            child.destroy()
        self.demo = None
        if name != "Home":   # a sub-screen: the title screen's header strip, its tabs, then the page itself
            title, tab = self.SUBSCREENS.get(name, (name.upper(), None))
            tabs = [("Graphics", "GRAPHICS"), ("Controls", "CONTROLS"), ("Settings", "LAUNCHER")] if tab else []
            header_strip(self.stage, title, tabs, name, on_tab=self.show, on_back=lambda: self.show("Home")).pack(fill="x")
            self.scroll = ScrollPage(self.stage)
            self.scroll.pack(fill="both", expand=True, padx=(34, 20), pady=(14, 0))
            self.page = self.scroll.body
        else:
            self.page = tk.Frame(self.stage, bg=BG)
            self.page.pack(fill="both", expand=True)
        if name == "Home" and self.job and self.demo_title:   # a long task: its demo screen, fed by poll_job
            self.demo = DemoScreen(self.page, title=self.demo_title)
            self.demo.pack(fill="both", expand=True)
            self.demo.set_progress(*self.demo_state)
            label(self.page, "You can keep using the other pages; this screen comes back on Home.", color=MUTED, size=9).pack(anchor="w", pady=(8, 0))
            return
        getattr(self, {"Home": "home", "Profiles": "profile_page", "Graphics": "graphics_page", "Controls": "controls_page", "Settings": "settings_page",
                       "Support": "support_page"}[name])()

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
        """The title screen: its menu is the next steps for this installation's state, its chips the state itself."""
        shaders = shader_preparation(self.game, self.profiles) if self.game else None
        busy = bool(self.process or self.job)
        act = lambda f: (lambda: self.action(f))
        settings = ("SETTINGS", "Graphics, controls, launcher", lambda: self.show("Graphics"), True)
        helpme = ("HELP", "Game files, report a problem, logs, about", lambda: self.show("Support"), True)
        if not self.game:
            menu = [("INSTALL ORBITALS", "From your own game files: about 20 to 60 minutes, once", act(self.install_game), not busy),
                    ("USE AN INSTALLATION", "A folder this launcher or the setup script already made", act(self.locate), not busy),
                    settings, helpme]
        else:
            old = outdated_release(self.game)
            menu = [("UPDATE THE GAME", f"From {old} to {VERSION}: 20 to 60 min, saves kept",
                     act(self.recompile_game), not busy)] if old else []
            menu.append(("PLAY", "The game is running" if self.process else "Start the game · two players: plug in a second controller",
                         act(self.play), not busy))
            if not shaders:
                menu.append(("PREPARE SHADERS", "Recommended once, about 15 minutes: no pauses in the first session",
                             act(self.prepare_shaders), not busy))
            menu += [settings, ("PROFILES", "Saves and settings per player", lambda: self.show("Profiles"), True), helpme]
        if self.game:
            game_tag = ("GAME", "RUNNING" if self.process else ("OUTDATED" if outdated_release(self.game) else "READY"),
                        PEACH if outdated_release(self.game) and not self.process else CYAN)
        else:
            game_tag = ("GAME", "PROBLEM" if self.error_text else "NOT INSTALLED", PEACH)
        shader_tag = ("SHADERS", f"{shaders.get('validated', 0):,} READY".replace(",", " ") if shaders else "NOT PREPARED",
                      CYAN if shaders else PEACH)
        tags = [game_tag, shader_tag, ("PROFILE", self.profiles.profile["name"], RED)]
        subtitle = self.error_text[:400] if self.error_text else "A cooperative adventure in space"
        TitleScreen(self.page, menu, tags, subtitle=subtitle, still=lambda: self.process is not None).pack(fill="both", expand=True)

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
            self.error_text = "Build found. Prepare the ExeFS / RomFS data to enable Play."
            self.refresh()
            return
        self.set_game(detected)

    def set_game(self, game):
        self.profiles.update(install=str(game.root))
        self.game = self.template = game
        self.error_text = ""
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
                        self.installed, demo="RECOMPILING ORBITALS")

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
                        lambda summary: self.shaders_prepared(summary, then), demo="PREPARING SHADERS")

    def shaders_prepared(self, summary, then=None):
        failed = summary.get("failed", 0)
        self.page_state.set(f"Shaders prepared: {summary.get('validated', 0):,} validated, {failed} not supported."
                            .replace(",", " "))
        self.refresh()
        if then:
            then()

    def background(self, status, worker, complete, demo=None):
        self.guard()
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
            self.demo_title = None
            if self.active_page == "Home":   # also after a job without a demo: its entries are enabled again
                self.show("Home")
            if kind == "error":
                self.error_text = str(value)
                self.page_state.set("The operation failed.")
                LOG.error("event=background_failed type=%s", type(value).__name__)
                self.copy_from(value)
                messagebox.showerror("Liftoff", self.error_text, parent=self.root)
                self.refresh()
            else:
                self.page_state.set("")
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
        if outdated_release(self.game) and self.offer_recompile(asked_now=True):
            return
        if (not shader_preparation(self.game, self.profiles) and not self.profiles.data.get("shader_prep_declined")):
            answer = messagebox.askyesnocancel("Prepare shaders", SHADER_PREP_TEXT + "\n\nPrepare them before playing? "
                                               "(No: play now and translate them during the session.)", parent=self.root)
            if answer is None:
                return
            if answer:
                self.prepare_shaders(confirm=False, then=self.play)
                return
            self.profiles.update(shader_prep_declined=True)
        self.error_text = ""
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
        self.error_text = "" if code == 0 else "Orbitals has stopped. The logs of this session are available."
        self.refresh()
        if code and messagebox.askyesno("Unexpected stop", "Prepare a report about this stop?", parent=self.root):
            self.report()

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
            self.error_text = ""
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
            self.error_text = ""
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

    def settings_page(self):
        self.heading("Settings", f"Settings applied at launch for {self.profiles.profile['name']}.")
        card = surface(self.page)
        card.pack(fill="x", pady=(0, 10))
        panel = tk.Frame(card, bg=PANEL)
        panel.pack(fill="x", padx=13, pady=(9, 11))
        label(panel, "Volume (%)", bg=PANEL, color=MUTED, size=9).pack(anchor="w", pady=(0, 2))
        volume = tk.StringVar(value=self.profiles.settings["volume"])
        ttk.Spinbox(panel, from_=0, to=100, textvariable=volume, width=9).pack(anchor="w")
        label(self.page, "GitHub issues URL", color=MUTED, size=9).pack(anchor="w", pady=(1, 2))
        address = ttk.Entry(self.page)
        address.insert(0, self.profiles.data.get("issues", ""))
        address.pack(fill="x", pady=(0, 9))
        updates = tk.BooleanVar(value=bool(self.profiles.data.get("update_check", True)))
        row = tk.Frame(self.page, bg=BG)
        row.pack(fill="x", pady=(0, 10))
        ttk.Checkbutton(row, variable=updates, text="Check for updates at start (one request to GitHub; a download only when you accept it)").pack(side="left")
        self.button(row, "Check now", lambda: threading.Thread(target=self.update_result, daemon=True).start()).pack(side="left", padx=10)
        self.button(row, "Open releases", lambda: webbrowser.open(RELEASES_URL)).pack(side="left")

        def save():
            self.guard()
            try:
                value = int(volume.get())
            except ValueError as err:
                raise LauncherError("Use a number for the volume.") from err
            settings = self.profiles.profile["settings"] | {"volume": value}
            validate_settings(self.profiles.settings | settings)
            url = address.get().strip().rstrip("/")
            if url and not re.fullmatch(r"https://github\.com/[\w.-]+/[\w.-]+/issues", url):
                raise LauncherError("Enter a GitHub URL ending in /issues.")
            entries = self.profiles.entries | {
                self.profiles.active: self.profiles.profile | {"settings": settings}}
            self.profiles.update(issues=url, profiles=entries, update_check=bool(updates.get()))
            self.page_state.set("Settings saved.")

        self.button(self.page, "Save", save, style="Play.TButton").pack(side="left", anchor="n")
        self.button(self.page, "Launcher folder", lambda: open_folder(self.local)).pack(
            side="left", anchor="n", padx=8, pady=4)

    def controls_page(self):
        self.heading("Controls", f"Input settings for {self.profiles.profile['name']}.")
        card = surface(self.page)
        card.pack(fill="x", pady=(0, 12))
        panel = tk.Frame(card, bg=PANEL)
        panel.pack(fill="x", padx=13, pady=11)
        detected = tk.StringVar(value="Close the game to scan for controllers." if self.process else "Ready to scan.")
        scan_button = self.button(panel, "Scan", lambda: scan())
        scan_button.pack(side="right", anchor="n")
        label(panel, "Connected controllers", bg=PANEL, color=CYAN, bold=True).pack(anchor="w")
        label(panel, textvariable=detected, bg=PANEL, color=MUTED, wraplength=480).pack(
            anchor="w", pady=(5, 0))

        def scan():
            game = self.game

            def probe():
                try:
                    return gamepad_inventory(game)
                except LauncherError as err:
                    return None, str(err)

            def show_devices(result):
                if not card.winfo_exists():   # another page is shown
                    return
                scan_button.state(["!disabled"])
                backend, devices = (None, "Could not check the connected controllers.") if isinstance(result, Exception) else result
                if backend is None:
                    detected.set(devices)
                elif backend == "unavailable":
                    detected.set("Controller support is unavailable on this system.")
                elif devices:
                    entries = [name if mapped else f"{name} · no gamepad mapping" for name, mapped in devices[:6]]
                    if len(devices) > 6:
                        entries.append(f"and {len(devices) - 6} more")
                    detected.set(f"{backend}\n" + "\n".join(entries))
                else:
                    detected.set(f"No controllers detected · {backend}")

            scan_button.state(["disabled"])
            detected.set("Scanning…")
            self.probe(probe, show_devices)

        if self.process:
            scan_button.state(["disabled"])
        else:
            scan()

        settings = self.profiles.settings
        card2 = surface(self.page)
        card2.pack(fill="x", pady=(0, 12))
        panel = tk.Frame(card2, bg=PANEL)
        panel.pack(fill="x", padx=13, pady=11)
        panel.columnconfigure((0, 1, 2), weight=1)
        players = {"Player 1": 1, "Player 2": 2}
        cameras = {"Game default": None, "Mouse + IJKL": True, "IJKL only": False}
        player = tk.StringVar(value=f"Player {settings['keyboard']}")
        camera = tk.StringVar(value=next((name for name, value in cameras.items() if value is settings["mouse_camera"]),
                                         "Game default"))
        speed = tk.StringVar(value=settings["mouse_sensitivity"] or "")
        vibration = tk.BooleanVar(value=settings["vibration"])
        label(panel, "Keyboard and mouse", bg=PANEL, color=CYAN, bold=True).grid(row=0, column=0, columnspan=3, sticky="w")
        for index, (caption, widget) in enumerate((
            ("Assigned player", ttk.Combobox(panel, values=tuple(players), textvariable=player, state="readonly", width=13)),
            ("Right stick", ttk.Combobox(panel, values=tuple(cameras), textvariable=camera, state="readonly", width=14)),
            ("Mouse speed (%)", ttk.Spinbox(panel, from_=10, to=500, textvariable=speed, width=10)),
        )):
            label(panel, caption, bg=PANEL, color=MUTED, size=9).grid(row=1, column=index, sticky="w", pady=(7, 2))
            widget.grid(row=2, column=index, sticky="ew", padx=(0, 9))
        label(panel, "Choose Player 2 for co-op with one controller. Keyboard and mouse take over Player 1 when "
                     "its controller is absent. Leave mouse speed blank to use the game's setting.",
              bg=PANEL, color=MUTED, wraplength=520).grid(row=3, column=0, columnspan=3, sticky="w", pady=(10, 3))
        label(panel, "F2 toggles mouse capture in game. Left click is ZR and right click is ZL.",
              bg=PANEL, color=MUTED, wraplength=520).grid(row=4, column=0, columnspan=3, sticky="w")
        if WINDOWS:
            ttk.Checkbutton(panel, text="Controller vibration", variable=vibration, style="Panel.TCheckbutton").grid(
                row=5, column=0, columnspan=3, sticky="w", pady=(8, 0))

        def save():
            self.guard()
            try:
                sensitivity = int(speed.get()) if speed.get().strip() else None
            except ValueError as err:
                raise LauncherError("Enter a mouse speed from 10 to 500, or leave it blank.") from err
            values = {"keyboard": players[player.get()], "mouse_camera": cameras[camera.get()],
                      "mouse_sensitivity": sensitivity, "vibration": vibration.get()}
            validate_settings(self.profiles.settings | values)
            self.profiles.update_active(settings=self.profiles.profile["settings"] | values)
            self.page_state.set("Controls saved for the next launch.")

        self.button(self.page, "Save", save, style="Play.TButton").pack(anchor="w")

    def graphics_page(self):
        """Presets and options of launcher/graphics.py (only measured ones), frame pacing, display; applied at the next launch."""
        self.heading("Graphics", "Applied at the next launch (restart needed). High = the game's own console rendering.")
        settings = self.profiles.settings
        gfx = graphics_settings(settings)
        preset = tk.StringVar(value=gfx["preset"])
        option_vars = {name: tk.StringVar(value=gfx.get(name, graphics.ORIGINAL)) for name in graphics.OPTIONS}
        fps = tk.StringVar(value=settings["fps"])
        mode = tk.StringVar(value=settings["mode"])
        display = tk.StringVar(value=settings["display"])
        size = tk.StringVar(value=settings["size"])
        upscale = tk.StringVar(value=settings["upscale"])
        vsync = tk.BooleanVar(value=settings["vsync"])

        card = surface(self.page)
        card.pack(fill="x", pady=(0, 10))
        panel = tk.Frame(card, bg=PANEL)
        panel.pack(fill="x", padx=13, pady=(9, 11))
        panel.columnconfigure((0, 1, 2), weight=1, uniform="gfx")
        label(panel, "Quality", bg=PANEL, color=CYAN, bold=True).grid(row=0, column=0, columnspan=3, sticky="w")
        label(panel, "Preset", bg=PANEL, size=9, color=MUTED).grid(row=1, column=0, sticky="w", pady=(7, 1))
        combo = ttk.Combobox(panel, textvariable=preset, values=graphics.PRESET_ORDER, state="readonly", width=14)
        combo.grid(row=2, column=0, sticky="ew", padx=(0, 10))
        controls = {}
        for n, (name, (caption, values)) in enumerate(graphics.OPTIONS.items()):
            col, row = (n + 1) % 3, ((n + 1) // 3) * 2 + 1
            label(panel, caption, bg=PANEL, size=9, color=MUTED).grid(row=row, column=col, sticky="w", pady=(7, 1))
            controls[name] = ttk.Combobox(panel, textvariable=option_vars[name], values=tuple(values), state="readonly", width=24)
            controls[name].grid(row=row + 1, column=col, sticky="ew", padx=(0, 10))
        summary = tk.StringVar()

        def on_preset(*_):
            chosen = graphics.resolve({"preset": preset.get(), **{k: v.get() for k, v in option_vars.items()}})
            for name, control in controls.items():
                if preset.get() != "Custom":
                    option_vars[name].set(chosen[name])
                control.configure(state="readonly" if preset.get() == "Custom" else "disabled")
            summary.set(graphics.PRESET_NOTES.get(preset.get(), ""))
            if preset.get() in graphics.PRESET_MODE:
                mode.set(graphics.PRESET_MODE[preset.get()])
            if mode_control is not None:
                mode_control.configure(state="readonly" if preset.get() == "Custom" else "disabled")
        mode_control = None
        preset.trace_add("write", on_preset)
        label(panel, textvariable=summary, bg=PANEL, size=9, color=MUTED, wraplength=760).grid(
            row=99, column=0, columnspan=3, sticky="w", pady=(9, 0))

        card2 = surface(self.page)
        card2.pack(fill="x", pady=(0, 10))
        panel2 = tk.Frame(card2, bg=PANEL)
        panel2.pack(fill="x", padx=13, pady=(9, 11))
        panel2.columnconfigure((0, 1, 2), weight=1, uniform="gfx2")
        label(panel2, "Display and frame rate", bg=PANEL, color=CYAN, bold=True).grid(row=0, column=0, columnspan=3, sticky="w")
        size_control = ttk.Combobox(panel2, textvariable=size, values=graphics.output_sizes(native_size(self.root)), width=18)
        rows = (("Frame rate", ttk.Combobox(panel2, textvariable=fps, values=graphics.FPS_CHOICES, state="readonly", width=24)),
                ("Internal 3D resolution", ttk.Combobox(panel2, textvariable=mode, values=graphics.RENDER_MODES, state="readonly", width=14)),
                ("Display", ttk.Combobox(panel2, textvariable=display, values=("Windowed", "Borderless"), state="readonly", width=14)),
                ("Window output size", size_control),
                ("Upscaling filter", ttk.Combobox(panel2, textvariable=upscale, values=("Standard", "Sharp", "FSR1"), state="readonly", width=14)),
                ("VSync", ttk.Checkbutton(panel2, variable=vsync, text="On", style="Panel.TCheckbutton")))
        for n, (caption, control) in enumerate(rows):
            col, row = n % 3, (n // 3) * 2 + 1
            label(panel2, caption, bg=PANEL, size=9, color=MUTED).grid(row=row, column=col, sticky="w", pady=(7, 1))
            control.grid(row=row + 1, column=col, sticky="ew", padx=(0, 10))
        mode_control = rows[1][1]
        on_preset()
        warning = tk.StringVar()

        def display_status(*_):
            desktop = display.get() == "Borderless"
            size_control.configure(state="disabled" if desktop else "normal")
            messages = [graphics.FPS_WARNINGS.get(fps.get(), ""), graphics.MODE_NOTES.get(mode.get(), "")]
            if desktop:
                messages.append("Borderless uses the monitor's desktop resolution.")
            warning.set("\n".join(filter(None, messages)))
        for value in (fps, mode, display):
            value.trace_add("write", display_status)
        display_status()
        label(panel2, textvariable=warning, bg=PANEL, size=9, color=PEACH, wraplength=760).grid(
            row=99, column=0, columnspan=3, sticky="w", pady=(9, 0))

        def save():
            self.guard()
            values = {"gfx_preset": preset.get(), "fps": fps.get(), "mode": mode.get(), "display": display.get(),
                      "size": size.get().strip(), "upscale": upscale.get(), "vsync": bool(vsync.get())}
            if preset.get() == "Custom":
                values |= {f"gfx_{k}": v.get() for k, v in option_vars.items()}
            current = dict(self.profiles.profile.get("settings", {}))
            new = {k: v for k, v in current.items() if not k.startswith("gfx_")} | values
            validate_settings(self.profiles.settings | new)
            if fps.get() != graphics.FPS_CHOICES[0] and not messagebox.askokcancel(
                    "Experimental mode", graphics.FPS_WARNINGS[fps.get()] + "\n\nSave anyway?", parent=self.root):
                return
            self.profiles.update_active(settings=new)
            self.page_state.set("Graphics saved: they apply at the next launch (restart needed).")

        def reset():
            self.guard()
            current = dict(self.profiles.profile.get("settings", {}))
            keep = {k: v for k, v in current.items() if not k.startswith("gfx_") and k not in ("fps", "mode", "display", "size", "upscale", "vsync")}
            self.profiles.update_active(settings=keep)
            self.page_state.set("Graphics reset (High, 30 FPS).")
            self.refresh()

        self.button(self.page, "Save", save, style="Play.TButton").pack(side="left", anchor="n")
        self.button(self.page, "Reset", reset).pack(side="left", anchor="n", padx=8, pady=4)

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
        self.root.destroy()
