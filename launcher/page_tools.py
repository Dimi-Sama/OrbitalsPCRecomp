# SwitchRecomp - Copyright 2026 MZ Labs
"""The Saves page and the Tools page (shortcuts, updates, problem reports, folders), as rows."""

import webbrowser
from pathlib import Path
from tkinter import filedialog

from . import desktop, dialogs, steam
from .core import RELEASES_URL, WINDOWS, latest_run, runtime_info, setup_log
from .rows import Rows


class RowsPage:
    def __init__(self, app):
        self.app = app
        self.rows = Rows(app, app.side)
        self.build()
        self.rows.ready()

    def idle(self):
        return not (self.app.process or self.app.job)


class SavesPage(RowsPage):
    """The saves, as one player has them. Profiles of an earlier version stay reachable: their saves are never out of sight."""

    def build(self):
        rows, app, idle = self.rows, self.app, self.idle
        rows.group("Saves")
        if len(app.profiles.entries) > 1:
            rows.choice("Saves in use", lambda: tuple(app.profiles.entries), lambda: app.profiles.active, self.select,
                        "An earlier version of the launcher kept several sets of saves, each with its settings. This one plays.",
                        show=lambda key: app.profiles.entries[key]["name"], enabled=idle)
        rows.action("Back up", "Create a copy", lambda: self.copy(app.profiles.backup), "A copy of the saves with the time in its name, in the "
                    "launcher's folder.", enabled=idle)
        rows.action("Import or restore", "Choose a folder", self.restore, "Puts a save folder, or a copy made by the launcher, in place of the "
                    "saves in use. A copy of those is kept first.", enabled=idle)
        rows.action("Export", "Choose a folder", self.export, "A copy of the saves in a folder of yours.", enabled=idle)
        rows.group("Folder")
        rows.action("Save folder", "Open", lambda: app.open_folder(app.profiles.saves), "Where the game writes its saves.")

    def select(self, profile):
        self.app.guard()
        self.app.profiles.select(profile)

    def copy(self, operation):
        self.app.background("Copying the saves…", operation, lambda path: self.app.page_state.set(f"Copy finished · {path.name}"))

    def restore(self):
        self.app.guard()
        path = filedialog.askdirectory(parent=self.app.root, title="Save folder to import")
        if path and dialogs.confirm(self.app.root, "Restore the saves", "Replace the saves in use? A copy of them is kept.", yes="Replace"):
            self.copy(lambda: self.app.profiles.restore(Path(path)))

    def export(self):
        self.app.guard()
        path = filedialog.askdirectory(parent=self.app.root, title="Destination folder")
        if path:
            self.copy(lambda: self.app.profiles.export(Path(path)))


class ToolsPage(RowsPage):
    def build(self):
        rows, app = self.rows, self.app
        self.steam_said = self.shortcut_said = ""
        rows.group("Shortcuts")
        rows.action("Desktop shortcut" if WINDOWS else "Application menu", "Add", self.add_shortcut,
                    lambda: ("The launcher with its icon on your desktop." if WINDOWS else "The launcher with its icon in your application menu.")
                    + " Adding it again replaces it." + (f"\n\n{self.shortcut_said}" if self.shortcut_said else ""))
        rows.action("Add to Steam", "Add", self.add_to_steam,
                    lambda: "The launcher as a non-Steam game, for Big Picture and the Steam Deck, with its library images. Your other shortcuts "
                    "are kept, and a copy of the list before. Adding it again replaces it."
                    + (f"\n\n{self.steam_said}" if self.steam_said else ""), enabled=lambda: not app.job)
        rows.group("Updates")
        rows.action("Latest release", lambda: "Update" if app.update_info else "Check now",
                    lambda: app.download_update() if app.update_info else app.check_now(),
                    lambda: app.update_answer or f"You have {app.version}. This asks GitHub for the latest public release.",
                    enabled=lambda: not (app.process or app.job))
        rows.action("What's new", "Read", app.update_notes, "The notes of the new release.", enabled=lambda: bool(app.update_info))
        rows.action("All releases", "Open", lambda: webbrowser.open(RELEASES_URL), "The releases' page in your browser.")
        rows.group("Problems")
        rows.action("Report a problem", "Create", app.report, "Makes a ZIP on this PC, to check before attaching it to a GitHub issue. Nothing is "
                    "sent.", enabled=self.idle)
        rows.action("GitHub issues", "Open", app.issues, "The issues' page in your browser (set in Settings, General).")
        rows.action("System information", "Show", app.inspect_system, "What a report says about this PC and its graphics.", enabled=self.idle)
        rows.group("Folders")
        rows.action("Last session", "Open", self.last_session, "The logs of the last time the game ran.")
        rows.action("Launcher logs", "Open", lambda: app.open_folder(app.local / "logs"), "What the launcher did.")
        rows.action("Setup log", "Open", lambda: app.open_file(setup_log()), "The output of the last installation.",
                    enabled=lambda: setup_log().is_file())
        rows.action("Reports", "Open", app.open_reports, "The ZIP files made by Report a problem.")
        rows.action("Launcher folder", "Open", lambda: app.open_folder(app.local), f"Profiles, saves, shader cache, logs and reports:\n{app.local}")
        rows.group("About")
        rows.action("Versions", "Copy", self.copy_versions, lambda: "\n".join(self.versions()))

    def add_shortcut(self):
        try:
            self.shortcut_said = desktop.add_shortcut()
        except (OSError, ValueError) as error:   # (LauncherError is a ValueError)
            self.shortcut_said = f"The shortcut could not be made: {error}"
        self.app.page_state.set(self.shortcut_said)

    def add_to_steam(self):
        app = self.app

        def done(result):
            self.steam_said = str(result)   # what was done, or the error
            app.page_state.set(str(result))
            if self.rows.pane.winfo_exists():
                self.rows.sync()

        self.steam_said = "Adding…"
        app.probe(lambda: steam.add(steam.images()), done)

    def last_session(self):
        app = self.app
        app.open_folder(latest_run(app.profiles) or (app.game.root if app.game else app.local / "logs"))

    def versions(self):
        app = self.app
        lines = [f"Launcher {app.version}"]
        if app.game:
            lines.append(f"Game build {app.game.ids['main'][:16]}" + (f" ({app.game.version})" if app.game.version else ""))
            detected = runtime_info((latest_run(app.profiles), app.game.root))
            if detected.get("release"):
                lines.append("Runtime " + " ".join(filter(None, (detected["release"], detected.get("commit")))))
            elif detected:
                lines.append("Recomp " + detected.get("recomp_version", "?"))
            if detected.get("vulkan_device"):
                lines.append(detected["vulkan_device"])
        return [*lines, "", "Built on SwitchRecomp by MZ Labs."]

    def copy_versions(self):
        self.app.root.clipboard_clear()
        self.app.root.clipboard_append("\n".join(line for line in self.versions() if line))
        self.app.page_state.set("Versions copied.")
