# Orbitals PC Recomp, based on SwitchRecomp by MZ Labs. AGPL-3.0 with NOTICE.txt terms.
"""RecompLauncher setup and play without importing Tk. See recomplauncher.json."""

import argparse
import json
import os
import shutil
import stat
import tempfile
import time
from pathlib import Path

from . import VERSION, code_update, nup
from .core import (DATA, DEFAULT_SETTINGS, LOG, InstallationLinksMissing, LauncherError, Profiles, atomic_output, build_ids,
                   carry_saves, detect_installation, finish_session, install_fraction, installation, instance_lock,
                   json_bytes, launch, prepare_shaders, read_local, repair_installation, safe_entry,
                   setup_log, setup_logging, shader_preparation, stage_install)

BUILD = code_update.BUILD_INFO
PREVIOUS = ".orbitals-previous"


def say(text):
    print(text, flush=True)


def progress(fraction, text):
    say(f"progress {max(0.0, min(1.0, fraction)):.3f} {text}")


def build_info(folder):
    try:
        with read_local(folder, Path(BUILD)) as file:
            data = json.loads(file.read(8192))
    except (OSError, ValueError):
        return {}
    if isinstance(data, dict) and isinstance(data.get("source"), str) and data["source"]:
        return data
    return {}


def require_managed(folder):
    if not stat.S_ISDIR(safe_entry(folder).st_mode) or not build_info(folder):
        raise LauncherError(f"This folder is not a RecompLauncher installation. Choose a different data folder. {folder}")


def recover_installation(game_dir):
    previous = game_dir.with_name(PREVIOUS)
    if not os.path.lexists(previous):
        return
    require_managed(previous)
    if not os.path.lexists(game_dir):
        previous.rename(game_dir)
        return
    require_managed(game_dir)
    # Both directories exist only after the prepared build was published. Python's rmtree
    # unlinks NTFS junctions instead of walking into the player's game files.
    try:
        with tempfile.TemporaryDirectory(prefix=".orbitals-retired-", dir=game_dir.parent) as work:
            previous.rename(Path(work) / "Orbitals")
    except OSError:
        LOG.warning("event=managed_previous_build_cleanup_failed", exc_info=True)


def publish(staged, game_dir):
    previous = game_dir.with_name(PREVIOUS)
    replaced = os.path.lexists(game_dir)
    if replaced:
        require_managed(game_dir)
        game_dir.rename(previous)
    try:
        staged.rename(game_dir)
    except OSError:
        if replaced:
            previous.rename(game_dir)
        raise
    recover_installation(game_dir)


def setup_tail(games):
    try:
        lines = setup_log(games).read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return
    for line in [line for line in lines if line.strip()][-6:]:
        say(line[:200])


def shaders(game, profiles):
    if shader_preparation(game, profiles):
        return
    progress(0.8, "Preparing the shaders")

    def step(event):
        if event.get("phase") == "translate" and event.get("discovered"):
            done = event.get("cached", 0) + event.get("translated", 0) + event.get("failed", 0)
            fraction = done / event["discovered"]
            progress(0.8 + 0.2 * fraction, f"Preparing shaders ({done} of {event['discovered']})")

    prepare_shaders(game, profiles, step)


def prepare(args, game_dir, profiles):
    games = game_dir.parent
    info = build_info(game_dir)
    given = args.game or info.get("source")
    if not given:
        say("Choose a NUP containing the base game or the folder with exefs and romfs.")
        return 2
    source = Path(given).resolve()
    if source.is_relative_to(game_dir) or game_dir.is_relative_to(source):
        raise LauncherError("Choose a copy outside the RecompLauncher installation folder.")
    from_nup = (source.suffix.lower() == ".nup" and not source.is_dir()) if args.game else bool(info.get("nup_base"))

    current = None
    if os.path.lexists(game_dir):
        require_managed(game_dir)
        try:
            current = installation(game_dir)
        except InstallationLinksMissing:
            if not from_nup and not source.is_dir():
                raise LauncherError("The original extracted game folder has moved. Select it again in RecompLauncher.")
            if not from_nup and info.get("ids") == build_ids(source / "exefs"):
                current = repair_installation(game_dir, source)
                with atomic_output(game_dir / BUILD) as output:
                    output.write_bytes(json_bytes(info | {"source": str(source)}))
                if code_update.plan(current, source) == code_update.READY:
                    if args.shaders:
                        shaders(current, profiles)
                    progress(1, "Game data reconnected")
                    return 0
        except (OSError, LauncherError):
            pass
    games.mkdir(parents=True, exist_ok=True)
    source_info = {"source": str(source)}
    plan_source = source
    if from_nup:
        # A managed NUP installation owns its extracted data. An update with no new
        # input can use that copy even after the player removes their original archive.
        plan_source = None
        if current and not args.game:
            revision = info["nup_base"]
        else:
            if not source.is_file():
                raise LauncherError("Choose a readable .nup file containing the base game.")
            revision = nup.base_fingerprint(source)
        source_info["nup_base"] = revision
        matching = (current and info.get("nup_base") == revision
                    and current.exefs == game_dir / DATA / "exefs" and current.romfs == game_dir / DATA / "romfs")
    else:
        matching = current and current.exefs == (source / "exefs").resolve() and current.romfs == (source / "romfs").resolve()
    end = 0.8 if args.shaders else 1.0
    extracted = end * 0.15 if from_nup and not matching else 0.0
    last_stage, last_at = -1, 0.0

    def step(number, total, message):
        nonlocal last_stage, last_at
        now = time.monotonic()
        if message and (number != last_stage or now - last_at > 2):
            last_stage, last_at = number, now
            progress(extracted + (end - extracted) * install_fraction(number, total, message), message)

    def extracting(event):
        progress(extracted * event.done / event.total if event.total else 0, event.text)

    if matching:
        choice = code_update.plan(current, plan_source)
        if choice == code_update.READY:
            if args.shaders:
                shaders(current, profiles)
            if from_nup and info["source"] != str(source):
                with atomic_output(game_dir / BUILD) as output:
                    output.write_bytes(json_bytes(info | source_info))
            progress(1, choice)
            return 0
        progress(0, choice)
        try:
            updated = code_update.apply(current, choice, install_dir=games, on_progress=step,
                                        managed={"release": VERSION, "ids": current.ids, **source_info})
        except LauncherError:
            setup_tail(games)
            raise
        if args.shaders:
            try:
                shaders(updated, profiles)
            except (LauncherError, OSError):
                code_update.rollback(game_dir)
                raise
        progress(1, "Ready to play")
        return 0

    progress(0, code_update.RECOMPILE)
    with tempfile.TemporaryDirectory(prefix=".orbitals-prepare-", dir=games) as work:
        destination = Path(work) / "Orbitals"
        try:
            staged = stage_install(source, destination, install_dir=games, local=profiles.root, on_progress=step,
                                   from_nup=from_nup, on_extract=extracting)
            if from_nup and nup.base_fingerprint(source) != source_info["nup_base"]:
                raise LauncherError("The NUP changed during installation. Choose it again and retry.")
        except LauncherError:
            setup_tail(games)
            raise
        carry_saves(current, staged)
        if current and (current.root / "Orbitals.ini").is_file():
            shutil.copy2(current.root / "Orbitals.ini", staged.root / "Orbitals.ini")
        if args.shaders:
            shaders(staged, profiles)
        (staged.root / BUILD).write_bytes(json_bytes({"release": VERSION, "ids": staged.ids, **source_info}))
        publish(staged.root, game_dir)
    progress(1, "Ready to play")
    return 0


def setting(text):
    key, _, value = text.partition("=")
    if key not in DEFAULT_SETTINGS or not value:
        raise LauncherError(f"Unknown setting {text!r}.")
    if type(DEFAULT_SETTINGS[key]) is bool or key in ("mouse_camera", "wb_gpu"):
        if value not in ("true", "false"):
            raise LauncherError(f"{key} must be true or false.")
        return key, value == "true"
    if type(DEFAULT_SETTINGS[key]) is int or key == "mouse_sensitivity":
        if not value.isascii() or not value.isdecimal() or len(value) > 10:
            raise LauncherError(f"{key} must be a number.")
        return key, int(value)
    if type(DEFAULT_SETTINGS[key]) is float:
        try:
            return key, float(value)
        except ValueError as error:
            raise LauncherError(f"{key} needs a number.") from error
    return key, value


def play(args, game, profiles):
    changes = dict(setting(text) for text in args.set)
    process, run = launch(game, profiles, overrides=changes)
    code = process.wait()
    finish_session(run, code, Profiles(profiles.root))
    try:
        shutil.copy2(run / "Orbitals.log", profiles.root / "logs" / "Orbitals.log")
    except OSError:
        LOG.warning("event=log_copy_failed")
    if code and code_update.can_restore(game.root):
        say("To return to the previous version, open this installation in Liftoff and choose Restore previous version in Game Files.")
    return code


def find_quiver_game(game_dir, profiles):
    configured = profiles.data.get("install")
    if configured or os.path.lexists(game_dir):
        try:
            return installation(Path(configured) if configured else game_dir)
        except (OSError, LauncherError):
            return None
    return detect_installation()


def main(argv, *, open_liftoff=None):
    parser = argparse.ArgumentParser(prog="launcher", description="Set up or play Orbitals without opening Liftoff.")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--prepare", action="store_true", help="install from your own copy")
    mode.add_argument("--play", action="store_true", help="start the game")
    parser.add_argument("--game", help="NUP containing the base game or folder holding exefs and romfs")
    parser.add_argument("--data", type=Path, default=os.environ.get("RECOMPLAUNCHER_DATA") or None,
                        help="RecompLauncher data folder")
    parser.add_argument("--shaders", action="store_true", help="prepare the shaders after building")
    parser.add_argument("--set", action="append", default=[], metavar="KEY=VALUE", help="change a setting for this session")
    args = parser.parse_args(argv)
    if args.data is None:
        parser.error("--data or RECOMPLAUNCHER_DATA is required")
    if (args.play and (args.game or args.shaders)) or (args.prepare and args.set):
        parser.error("--game and --shaders are for --prepare, and --set is for --play")
    data = args.data.resolve()
    local = data / "launcher"
    game_dir = data / "games" / "Orbitals"
    # Quiver reads the same play manifest and passes these variables without the
    # version variable that identifies RecompLauncher's own prepare/play protocol.
    quiver = args.play and os.environ.get("RECOMPLAUNCHER") == "1" and not os.environ.get("RECOMPLAUNCHER_VERSION")
    try:
        with instance_lock(local), setup_logging(local):
            if os.path.lexists(game_dir.parent) and not stat.S_ISDIR(safe_entry(game_dir.parent).st_mode):
                raise LauncherError("The RecompLauncher games path must be a directory.")
            recover_installation(game_dir)
            profiles = Profiles(local)
            if args.prepare:
                return prepare(args, game_dir, profiles)
            if quiver:
                game = find_quiver_game(game_dir, profiles)
                if game:
                    declined = profiles.data.get("recompile_declined")
                    if not code_update.kit_differs(game) or declined == code_update.kit_revision():
                        return play(args, game, profiles)
            else:
                try:
                    game = installation(game_dir)
                except InstallationLinksMissing:
                    say("The extracted game folder has moved. Select it again in RecompLauncher to reconnect the game.")
                    return 2
                except (OSError, LauncherError) as error:
                    say(f"Set up Orbitals again with your copy. {error}")
                    return 2
                return play(args, game, profiles)
        if open_liftoff:
            options = ["--data-dir", str(local)]
            if game:
                options += ["--game-dir", str(game.root)]
            return open_liftoff(options)
        say("Open Liftoff to set up Orbitals from your copy.")
        return 2
    except (LauncherError, OSError, ValueError) as error:
        say(str(error))
        return 1
