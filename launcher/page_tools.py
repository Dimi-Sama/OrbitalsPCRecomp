# SwitchRecomp - Copyright 2026 MZ Labs
"""The Profiles page (players, their saves) and the Tools page (Steam, updates, problem reports, folders), as rows."""

import tempfile
import webbrowser
from pathlib import Path
from tkinter import filedialog

from . import dialogs, steam
from .core import RELEASES_URL, latest_run, runtime_info, setup_log
from .rows import Rows


class RowsPage:
    def __init__(self, app):
        self.app = app
        self.rows = Rows(app, app.side)
        self.build()
        self.rows.ready()

    def idle(self):
        return not (self.app.process or self.app.job)


class ProfilesPage(RowsPage):
    def build(self):
        rows, app, idle = self.rows, self.app, self.idle
        rows.group("Players")
        rows.choice("Active profile", lambda: tuple(app.profiles.entries), lambda: app.profiles.active, self.select,
                    "Who plays next. Each profile has its own settings and save folder.",
                    show=lambda key: app.profiles.entries[key]["name"], enabled=idle)
        rows.action("New profile", "Create", lambda: self.name("New profile", "", app.profiles.create), "Another player, with their own saves "
                    "and the default settings.", enabled=idle)
        rows.action("Rename this profile", "Rename", lambda: self.name("Rename the profile", app.profiles.profile["name"], app.profiles.rename),
                    "The saves and the settings stay.", enabled=idle)
        rows.action("Delete this profile", "Delete…", self.delete, "It leaves the list. Its files are moved to archived-profiles in the launcher's "
                    "folder, not erased.", enabled=lambda: idle() and len(app.profiles.entries) > 1)
        rows.group("Saves")
        rows.action("Back up", "Create a copy", lambda: self.copy(app.profiles.backup), "A copy of the saves with the time in its name, in the "
                    "profile's backups.", enabled=idle)
        rows.action("Import or restore", "Choose a folder", self.restore, "Puts a save folder, or a copy made by the launcher, in place of the "
                    "active saves. A copy of those is kept first.", enabled=idle)
        rows.action("Export", "Choose a folder", self.export, "A copy of the saves in a folder of yours.", enabled=idle)
        rows.action("Save folder", "Open", lambda: app.open_folder(app.profiles.saves), "Where the game writes this profile's saves.")

    def select(self, profile):
        self.app.guard()
        self.app.profiles.select(profile)

    def name(self, title, value, keep):
        self.app.guard()
        profiles = self.app.profiles
        exclude = profiles.active if value else None   # (its own name may stay)
        name = dialogs.ask_text(self.app.root, title, "Name (1 to 32 characters)", value,
                                check=lambda text: profiles.validate_name(text, exclude=exclude))
        if name is not None:
            keep(name)

    def delete(self):
        self.app.guard()
        name = self.app.profiles.profile["name"]
        if dialogs.confirm(self.app.root, "Delete the profile", f"Remove {name} from the list? Its files are kept in archived-profiles.",
                           yes="Remove", alarm=True):
            self.app.profiles.archive()

    def copy(self, operation):
        self.app.background("Copying the saves…", operation, lambda path: self.app.page_state.set(f"Copy finished · {path.name}"))

    def restore(self):
        self.app.guard()
        path = filedialog.askdirectory(parent=self.app.root, title="Folder to import into the active profile")
        if path and dialogs.confirm(self.app.root, "Restore the saves", "Replace the active saves? A copy of them is kept.", yes="Replace"):
            self.copy(lambda: self.app.profiles.restore(Path(path)))

    def export(self):
        self.app.guard()
        path = filedialog.askdirectory(parent=self.app.root, title="Destination folder")
        if path:
            self.copy(lambda: self.app.profiles.export(Path(path)))


class ToolsPage(RowsPage):
    def build(self):
        rows, app = self.rows, self.app
        self.steam_said = ""
        rows.group("Steam")
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

    def add_to_steam(self):
        app = self.app
        folder = Path(tempfile.mkdtemp(prefix="orbitals-steam-"))
        images = steam.draw_images(app.root, folder)

        def done(result):
            for image in images.values():
                image.unlink(missing_ok=True)
            folder.rmdir()
            self.steam_said = str(result)   # what was done, or the error
            app.page_state.set(str(result))
            if self.rows.pane.winfo_exists():
                self.rows.sync()

        self.steam_said = "Adding…"
        app.probe(lambda: steam.add(images), done)

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
