# Orbitals PC Recomp, a work based on SwitchRecomp by MZ Labs. GNU AGPL v3.0 with the additional terms of NOTICE.txt (LICENSE.txt).
"""Setup and play without a window, for RecompLauncher (recomplauncher.json). Only `--prepare` and `--play` as the first argument reach
this module (launcher/__main__.py); without them the launcher opens as before. No Tk is needed here.

  python -B -m launcher --prepare [--game=<folder with exefs and romfs>] [--data <folder>] [--shaders]
      Install from my files into <data>/games/Orbitals, printing "progress <0-1> <text>" lines. Without --game the installation is
      built again from the copy it links to. Nothing to do when this release already built it from the same copy. --shaders then
      prepares the shaders (PREPARE SHADERS).
  python -B -m launcher --play [--data <folder>] [--set key=value ...]
      PLAY with the active profile of <data>/launcher; --set changes a profile setting for this session only.

<data> defaults to RECOMPLAUNCHER_DATA. Profiles, the shader cache and the logs go in <data>/launcher, the build in <data>/games.
"""

import argparse
import json
import os
import shutil
import time
from pathlib import Path

from . import VERSION
from .core import (DEFAULT_SETTINGS, LOG, WINDOWS, LauncherError, Profiles, finish_session, game_source, install_fraction,
                   install_from_files, installation, instance_lock, launch, prepare_shaders, setup_logging, shader_preparation)

BUILD = "build.json"   # {"release", "source"}: written once a build has finished, removed before one starts


def say(text):
    print(text, flush=True)


def progress(fraction, text):
    say(f"progress {max(0.0, min(1.0, fraction)):.3f} {text}")


def built(games):
    try:
        info = json.loads((games / BUILD).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return info if isinstance(info, dict) else {}


def unlink_copy(game):
    """Remove the links to an earlier copy (never what they point to), so the installation can link to another one."""
    for name in ("exefs", "romfs"):
        path = game / "Orbitals_data" / name
        if WINDOWS and path.is_junction():
            path.rmdir()
        elif path.is_symlink():
            path.unlink()
        elif path.exists():
            raise LauncherError(f"{path} is a folder, not a link to your copy: choose another data folder.")


def setup_tail(games, lines=6):
    try:
        text = (games / "setup.log").read_text(encoding="utf-8", errors="replace")
    except OSError:
        return
    for line in [line for line in text.splitlines() if line.strip()][-lines:]:
        say(line[:200])


def shaders(game, data, start):
    profiles = Profiles(data / "launcher")
    if shader_preparation(game, profiles):
        return
    last = [0.0]

    def step(event):
        if event.get("phase") == "translate" and event.get("discovered"):
            done = event.get("cached", 0) + event.get("translated", 0) + event.get("failed", 0)
            if time.monotonic() - last[0] > 2:
                last[0] = time.monotonic()
                progress(start + (1 - start) * done / event["discovered"], f"Preparing the shaders: {done} of {event['discovered']}")
        elif event.get("phase") in ("deps", "decoder", "extract", "decode"):
            progress(start, "Preparing the shaders: " + str(event.get("phase")))

    prepare_shaders(game, profiles, step)


def prepare(args, data):
    games = data / "games"
    game_dir = games / "Orbitals"
    try:
        current = installation(game_dir)
    except (OSError, LauncherError):
        current = None
    info = built(games)
    source = Path(args.game).resolve() if args.game else (game_source(current) if current else None)
    end = 0.8 if args.shaders else 1.0
    same = source is not None and os.path.normcase(info.get("source", "")) == os.path.normcase(str(source))
    if current and same and info.get("release") == VERSION:
        if args.shaders:
            shaders(current, data, end)
        progress(1, "Already built")
        return 0
    if source is None:
        old = info.get("source")
        say(f"Your copy of Orbitals is no longer at {old}." if old else "No copy of Orbitals was given.")
        say("Pick your copy again: the folder extracted from it, with exefs and romfs.")
        return 2
    if game_dir.is_dir():
        unlink_copy(game_dir)
    (games / BUILD).unlink(missing_ok=True)
    progress(0, "Recompiling your copy of Orbitals (20 to 60 minutes)")
    last = [0.0, None]

    def step(n, total, text):
        if not text:
            return
        if n != last[1] or time.monotonic() - last[0] > 2:
            last[0], last[1] = time.monotonic(), n
            progress(end * install_fraction(n, total, text), text)

    try:
        game = install_from_files(source, games, on_progress=step, rebuild=True)
    except LauncherError:
        setup_tail(games)
        raise
    (games / BUILD).write_text(json.dumps({"release": VERSION, "source": str(source)}), encoding="utf-8")
    if args.shaders:
        shaders(game, data, end)
    progress(1, "Ready to play")
    return 0


def setting(text):
    key, _, value = text.partition("=")
    if key not in DEFAULT_SETTINGS or not value:
        raise LauncherError(f"Unknown setting: {text}")
    kind = type(DEFAULT_SETTINGS[key])
    if kind is bool or key == "mouse_camera":
        if value not in ("true", "false"):
            raise LauncherError(f"{key} is true or false.")
        return key, value == "true"
    if kind is int or key == "mouse_sensitivity":
        if not value.isdecimal():
            raise LauncherError(f"{key} is a number.")
        return key, int(value)
    return key, value


def play(args, data):
    try:
        game = installation(data / "games" / "Orbitals")
    except (OSError, LauncherError) as error:
        say(f"Orbitals is not set up in {data / 'games'} yet ({error}). Set it up again, with your copy.")
        return 2
    local = data / "launcher"
    changes = dict(setting(text) for text in args.set)
    with instance_lock(local), setup_logging(local):
        profiles = Profiles(local)
        profile = profiles.profile
        profiles.data = profiles.data | {"profiles": profiles.entries | {
            profiles.active: profile | {"settings": profile["settings"] | changes}}}   # this session only: nothing is written
        process, run = launch(game, profiles)
        code = process.wait()
        finish_session(run, code, Profiles(local))
        try:   # the game's log where RecompLauncher looks for it (folders.logs)
            shutil.copy2(run / "Orbitals.log", local / "logs" / "Orbitals.log")
        except OSError:
            LOG.warning("event=log_copy_failed")
    return code


def main(argv):
    parser = argparse.ArgumentParser(prog="launcher", description="Orbitals PC Recomp without a window (RecompLauncher)")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--prepare", action="store_true", help="install from your files, or check that it is done")
    mode.add_argument("--play", action="store_true", help="start the game")
    parser.add_argument("--game", help="the folder extracted from your copy, with exefs and romfs")
    parser.add_argument("--data", default=os.environ.get("RECOMPLAUNCHER_DATA"), help="where the build, profiles and logs go")
    parser.add_argument("--shaders", action="store_true", help="also prepare the shaders")
    parser.add_argument("--set", action="append", default=[], metavar="KEY=VALUE", help="a profile setting for this session")
    args = parser.parse_args(argv)
    if not args.data:
        parser.error("--data (or RECOMPLAUNCHER_DATA) is needed")
    data = Path(args.data).resolve()
    try:
        return prepare(args, data) if args.prepare else play(args, data)
    except (LauncherError, OSError) as error:
        say(str(error))
        return 1
