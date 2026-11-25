# SwitchRecomp - Copyright 2026 MZ Labs
"""The bug report's windows: the form, its preview, and a read-only text window."""

import tkinter as tk
from tkinter import messagebox, ttk

from .core import LauncherError, latest_run
from .look import BG, CYAN, ENTRY, INK, LINE, MUTED, PEACH, label, text_box
from .reports import ISSUE_TYPES, create_report, report_saves


def show_text(parent, title, content):
    view = tk.Toplevel(parent, bg=BG)
    view.title(title)
    view.geometry("660x490")
    view.transient(parent)
    box = text_box(view)
    bar = ttk.Scrollbar(view, command=box.yview)
    bar.pack(side="right", fill="y")
    box.configure(yscrollcommand=bar.set)
    box.pack(fill="both", expand=True, padx=12, pady=12)
    box.insert("1.0", content)
    box.configure(state="disabled")
    return view


class ReportForm:
    def __init__(self, app):
        self.app = app
        self.window = tk.Toplevel(app.root, bg=BG)
        self.window.title("Report a problem · Orbitals")
        self.window.transient(app.root)
        self.window.minsize(680, 560)
        self.window.geometry("780x640")
        self.window.grab_set()
        self.busy = False
        self.window.protocol("WM_DELETE_WINDOW", self.close)
        body = tk.Frame(self.window, bg=BG)
        body.pack(fill="both", expand=True, padx=16, pady=13)
        label(body, "Report a problem", size=20, bold=True).pack(anchor="w")
        label(body, "Check the contents before posting a report on GitHub.", color=MUTED).pack(
            anchor="w", pady=(0, 8))
        title_row = tk.Frame(body, bg=BG)
        title_row.pack(fill="x")
        self.category = tk.StringVar(value=ISSUE_TYPES[0])
        ttk.Combobox(title_row, textvariable=self.category, values=ISSUE_TYPES, state="readonly", width=22).pack(
            side="left", padx=(0, 8))
        self.title = tk.StringVar()
        ttk.Entry(title_row, textvariable=self.title).pack(side="left", fill="x", expand=True)
        label(body, "Problem type and title", color=MUTED, size=9).pack(anchor="w", pady=(2, 5))
        form = tk.Frame(body, bg=BG)
        form.pack(fill="both", expand=True)
        form.columnconfigure((0, 1), weight=1, uniform="fields")
        form.rowconfigure((0, 1), weight=1, uniform="fields")
        self.inputs = {}
        for index, (name, caption) in enumerate((
            ("description", "Description"), ("steps", "Steps to reproduce"),
            ("expected", "Expected behaviour"), ("actual", "Observed behaviour"),
        )):
            field = tk.Frame(form, bg=BG)
            field.grid(row=index // 2, column=index % 2, sticky="nsew", padx=(0, 8), pady=(0, 5))
            label(field, caption, color=MUTED, size=9).pack(anchor="w")
            self.inputs[name] = text_box(field, height=2)
            self.inputs[name].pack(fill="both", expand=True)
        self.options = {}
        checkboxes = tk.Frame(body, bg=BG)
        checkboxes.pack(fill="x", pady=(4, 4))
        run = latest_run(app.profiles)
        log_root = run or (app.game.root if app.game else None)
        game_logs = bool(log_root and any((log_root / name).is_file() for name in
                                          ("Orbitals.log", "console.log", "threads.txt", "crash.log", "exit.json")))
        for index, (key, title, enabled) in enumerate(
            (("game_logs", "Game logs" if game_logs else "Game logs · unavailable", game_logs),
             ("launcher_logs", "Launcher logs", True), ("hardware", "Hardware", True),
             ("version", "Versions", True), ("settings", "Profile settings", True))):
            self.options[key] = tk.BooleanVar(value=enabled)
            check = ttk.Checkbutton(checkboxes, text=title, variable=self.options[key])
            check.grid(row=index // 3, column=index % 3, sticky="w", padx=(0, 9))
            if not enabled:
                check.state(["disabled"])
        try:
            self.saves = report_saves(app.profiles.saves)
        except (OSError, LauncherError):
            self.saves = {}
        self.options["saves"] = tk.BooleanVar(value=False)
        save_title = "Choose saves…" if self.saves else "Saves · unavailable"
        save = ttk.Checkbutton(checkboxes, text=save_title, variable=self.options["saves"], command=self.choose_saves)
        save.grid(row=1, column=2, sticky="w")
        if not self.saves:
            save.state(["disabled"])
        self.selected_saves = ()
        self.status = tk.StringVar(value="Maximum package size · 24 MB")
        label(body, textvariable=self.status, color=CYAN, size=9, wraplength=660).pack(anchor="w", pady=(1, 6))
        actions = tk.Frame(body, bg=BG)
        actions.pack(fill="x")
        app.button(actions, "Preview", self.review).pack(side="left", padx=(0, 5))
        app.button(actions, "Reports folder", app.open_reports).pack(side="right", padx=(5, 0))
        app.button(actions, "Issues GitHub", app.issues).pack(side="right")

    def close(self):
        if not self.busy:
            self.window.destroy()

    def choose_saves(self):
        if not self.options["saves"].get():
            self.selected_saves = ()
            return
        view = tk.Toplevel(self.window, bg=BG, padx=15, pady=13)
        view.title("Save copies")
        view.transient(self.window)
        view.grab_set()
        label(view, "Choose the files you want to attach.", bold=True).pack(anchor="w")
        label(view, "Public attachments can be read by other people.",
              color=PEACH).pack(anchor="w", pady=(4, 7))
        variables = {}
        for name, size in sorted(self.saves.items()):
            variables[name] = tk.BooleanVar()
            ttk.Checkbutton(view, text=f"{name.as_posix()}  ·  {size:,} bytes",
                            variable=variables[name]).pack(anchor="w")

        def done(keep):
            self.selected_saves = tuple(name for name, var in variables.items() if keep and var.get())
            self.options["saves"].set(bool(self.selected_saves))
            view.destroy()
            self.window.grab_set()

        self.app.button(view, "Confirm the selection", lambda: done(True)).pack(anchor="e", pady=(10, 0))
        view.protocol("WM_DELETE_WINDOW", lambda: done(False))

    def collect(self):
        self.app.guard()
        if self.busy:
            return
        fields = {name: control.get("1.0", "end-1c") for name, control in self.inputs.items()}
        fields.update(title=self.title.get(), type=self.category.get())
        options = {name: var.get() for name, var in self.options.items()}
        return fields, options

    def review(self):
        collected = self.collect()
        if collected is None:
            return
        fields, options = collected
        self.busy = True
        self.status.set("Reading the files and information…")
        saves = self.selected_saves
        self.app.background("Preparing the preview…",
                            lambda: self.collect_report(fields, options, saves),
                            self.show_preview)

    def collect_report(self, fields, options, saves):
        try:
            report = create_report(fields, options, self.app.profiles, self.app.game,
                                   latest_run(self.app.profiles), selected_saves=saves)
        except (OSError, LauncherError, ValueError) as error:
            return error
        return report

    def show_preview(self, result):
        self.busy = False
        if isinstance(result, Exception):
            self.status.set(str(result))
            return
        report = result
        view = tk.Toplevel(self.window, bg=BG, padx=13, pady=12)
        view.title("Report preview")
        view.transient(self.window)
        view.geometry("700x560")
        view.grab_set()
        view.columnconfigure(1, weight=1)
        view.rowconfigure(1, weight=1)
        label(view, "Report contents", bold=True, size=13).grid(row=0, column=0, columnspan=2, sticky="w")
        names = list(report.files)
        listing = tk.Listbox(view, width=31, bg=ENTRY, fg=INK, selectbackground=LINE,
                             relief="flat", exportselection=False)
        listing.grid(row=1, column=0, sticky="ns", padx=(0, 8), pady=(8, 6))
        for name in names:
            listing.insert("end", name)
        box = text_box(view)
        box.grid(row=1, column=1, sticky="nsew", pady=(8, 6))

        def pick(_=None):
            selected = listing.curselection()
            if not selected:
                return
            name = names[selected[0]]
            data = report.files[name]
            content = (f"Binary copy · {len(data):,} bytes" if name.startswith("saves/") else
                       data.decode("utf-8", errors="replace"))
            box.configure(state="normal")
            box.delete("1.0", "end")
            box.insert("1.0", content)
            box.configure(state="disabled")

        listing.bind("<<ListboxSelect>>", pick)
        listing.select_set(names.index("issue.md"))
        pick()
        actions = tk.Frame(view, bg=BG)
        actions.grid(row=2, column=0, columnspan=2, sticky="ew")

        def close():
            view.destroy()
            self.window.grab_set()

        def copy():
            view.clipboard_clear()
            view.clipboard_append(report.issue)
            self.status.set("Issue text copied.")

        def write():
            if any(name.startswith("saves/") for name in names) and not messagebox.askyesno(
                    "Confirm the saves", "Include these binary copies in the local ZIP?", parent=view):
                return
            destination = report.write(self.app.local / "reports")
            self.status.set(f"ZIP created · {destination.name}")
            close()

        self.app.button(actions, "Copy the text", copy).pack(side="left")
        self.app.button(actions, "Close", close).pack(side="right", padx=(6, 0))
        self.app.button(actions, "Create the ZIP", write, style="Play.TButton").pack(side="right")
        view.protocol("WM_DELETE_WINDOW", close)
