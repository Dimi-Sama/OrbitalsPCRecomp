# Orbitals PC Recomp, based on SwitchRecomp by MZ Labs. GNU AGPL v3.0, see LICENSE.txt and NOTICE.txt.
"""Compare the issue #11 replay modes with an existing compiled game."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import tempfile

from . import code_update, core, graphics


def existing_profile(game):
    roots = [core.data_home()]
    if game.root.parent.name.casefold() == "games":
        roots.insert(0, game.root.parent.parent / "launcher")
    for root in roots:
        try:
            data = json.loads((root / "launcher.json").read_text(encoding="utf-8"))
            configured = data.get("install")
            if configured and Path(configured).resolve() != game.root:
                continue
            active = data["active"]
            if re.fullmatch(r"[0-9a-f]{32}", active):
                settings = data["profiles"][active]["settings"]
                settings = {key: core.LEGACY_VALUES.get(value, value) if isinstance(value, str) else value
                            for key, value in settings.items()}
                core.validate_settings(core.DEFAULT_SETTINGS | settings)
                return settings, root / "profiles" / active / "save", root / "shader-cache" / game.ids["main"]
        except (OSError, ValueError, TypeError, KeyError, AttributeError):
            continue
    settings = {}
    ini = game.root / "Orbitals.ini"
    if ini.is_file():
        text = ini.read_text(encoding="utf-8-sig", errors="replace")
        for key, label in (("ue_fps", "fps"), ("docked", "mode")):
            values = re.findall(rf"(?m)^\s*{key}\s*=\s*(\d+)", text)
            if values:
                if label == "fps":
                    fps = next((name for name, value in graphics.FPS_MODES.items() if str(value) == values[-1]), None)
                    if fps:
                        settings[label] = fps
                elif values[-1] in ("0", "1"):
                    settings.update(mode="TV" if values[-1] == "1" else "Portable", gfx_preset="Custom")
    return settings, game.saves, game.root / "Orbitals_nvn"


def snapshot(game, data):
    key = hashlib.sha256(os.fsencode(str(game.root))).hexdigest()[:16]
    saved = data / "inputs" / key
    saved.parent.mkdir(parents=True, exist_ok=True)
    if saved.is_dir():
        return saved
    settings, save, cache = existing_profile(game)
    if not save.is_dir():
        save = game.saves
    with tempfile.TemporaryDirectory(dir=saved.parent, prefix=".copy-") as work:
        stage = Path(work) / "snapshot"
        stage.mkdir()
        if save.is_dir():
            core.copy_files(save, stage / "save", core.save_files(save))
        if (game.root / "Orbitals.ini").is_file():
            shutil.copy2(game.root / "Orbitals.ini", stage)
        core.write_text(stage / "inputs.json", json.dumps({"settings": settings, "seed": str(cache)}))
        stage.rename(saved)
    return saved


def play(game, mode, data, result):
    code_update.assert_launchable(game, require_identity=True)
    if code_update.plan(game) == code_update.RECOMPILE:
        raise core.LauncherError("Update or recompile the selected installation before running this test.")
    initial = snapshot(game, data)
    inputs = json.loads((initial / "inputs.json").read_text(encoding="utf-8"))
    settings = inputs["settings"]
    result.mkdir(parents=True)
    core.write_text(result / "test.json", json.dumps({
        "mode": mode, "async_replay": mode != "A", "target_fence": mode == "C",
        "settings": core.DEFAULT_SETTINGS | settings,
    }, indent=2))
    # Keep RomFS paths short. Windows can briefly retain the shader worker's directory after exit.
    with tempfile.TemporaryDirectory(prefix="o11-", ignore_cleanup_errors=True) as work:
        stage = Path(work)
        native = stage / "game"
        (native / core.DATA).mkdir(parents=True)
        shutil.copy2(core.REPO / "bin/runtime_win64_win32.exe", native / core.EXE)
        for path in core.local_binary_files(game.root):
            if path.name.casefold() in {core.EXE.casefold(), "sdl3.dll"}:
                continue
            shutil.copy2(path, native / path.name)
        shutil.copy2(game.root / code_update.MANIFEST, native / code_update.MANIFEST)
        shutil.copy2(core.REPO / "bin/SDL3.dll", native / "SDL3.dll")
        if (initial / "Orbitals.ini").is_file():
            shutil.copy2(initial / "Orbitals.ini", native)
        for leaf, path in (("exefs", game.exefs), ("romfs", game.romfs), ("fonts", game.root / core.DATA / "fonts")):
            if path.is_dir():
                core.link_directory(native / core.DATA / leaf, path.resolve())
        for parent in (game.root, game.root.parent):
            toolchain = parent / "toolchain"
            if toolchain.is_dir():
                core.link_directory(native / "toolchain", toolchain.resolve())
                break
        seed = Path(inputs["seed"])
        if seed.is_dir():
            core.link_directory(native / "Orbitals_nvn", seed.resolve())
        profiles = core.Profiles(stage / "local")
        profiles.update_active(settings=settings)
        if (initial / "save").is_dir():
            core.copy_files(initial / "save", profiles.saves, core.save_files(initial / "save"))
        shared = data / "shader-cache"
        shared.mkdir(exist_ok=True)
        core.link_directory(profiles.root / "shader-cache", shared)
        os.environ.update(ORBITALS_DIAGNOSTICS="1", NXRT_VK_COMPLETION_WAKE="0", NXRT_VK_FLIGHT="0",
                          SWR_ASYNC_SUBMIT="0" if mode == "A" else "1",
                          SWR_SYNC_TARGET_FENCE="1" if mode == "C" else "0",
                          SWR_TRACE_SYNC="2400:trace", SWR_TRACE="hotkey:36")
        process, run = core.launch(core.installation(native), profiles, run=stage / "run")
        code = process.wait()
        core.finish_session(run, code)
        for name in ("Orbitals.log", "console.log", "frames.csv", "exit.json"):
            if (run / name).is_file():
                shutil.copy2(run / name, result)
        for trace in run.glob("swr_trace_*.json"):
            shutil.copy2(trace, result)
    return code


def main(argv):
    from tkinter import Tk, filedialog, messagebox

    parser = argparse.ArgumentParser(description="Orbitals issue #11 Windows diagnostics")
    if not core.WINDOWS:
        parser.error("The comparison script uses the Windows kit.")
    parser.add_argument("mode", choices=("A", "B", "C"))
    mode = parser.parse_args(argv).mode
    root = Tk()
    root.withdraw()
    data = core.REPO / "issue11-local"
    recent = data / "game-folder.txt"
    try:
        initial = recent.read_text(encoding="utf-8").strip() if recent.is_file() else ""
        path = filedialog.askdirectory(parent=root, initialdir=initial or None, mustexist=True,
                                       title="Choisis le dossier contenant Orbitals.exe et Orbitals_code.dll")
        if not path:
            return 0
        with core.instance_lock(data):
            game = core.installation(Path(path))
            core.write_text(recent, str(game.root))
            result = core.REPO / "issue11-results" / f"{mode}-{core.timestamp()}"
            code = play(game, mode, data, result)
        if code:
            messagebox.showwarning("Orbitals · Issue #11", f"Le jeu a quitté avec le code {code}. Les journaux sont disponibles.", parent=root)
        os.startfile(result)
        return code
    except (OSError, ValueError) as error:
        messagebox.showerror("Orbitals · Issue #11", f"Impossible de lancer le test.\n\n{error}", parent=root)
        return 1
    finally:
        root.destroy()
