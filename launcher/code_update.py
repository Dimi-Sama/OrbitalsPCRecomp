# Orbitals PC Recomp, based on SwitchRecomp by MZ Labs. AGPL-3.0 with NOTICE.txt terms.
"""Plan, publish and roll back updates to the installed runtime and code module."""

import json
import os
import shutil
import stat
import subprocess
import tempfile
import time
from pathlib import Path

import module_build as build

from . import core

FAST = "Quick update"
RECOMPILE = "Recompilation required (estimated 20–60 minutes; up to 90 on Steam Deck)"
READY = "Already built"
JOURNAL = ".orbitals-update.json"
LOCK = ".orbitals-update-lock"
BUILD_INFO = ".recomplauncher-build.json"
MANIFEST = build.manifest_path(core.MODULE).name
PAYLOAD = (core.MODULE, MANIFEST, "SDL3.dll", "Play-Orbitals.ps1", "orbitals-deck.sh",
           "nxshader", "toolchain", "python", BUILD_INFO, core.EXE)


def available_runtime():
    name = "runtime_win64_win32.exe" if core.WINDOWS else "runtime_linux_x11"
    return core.REPO / "bin" / name


def tools_differ(game):
    desired = core.REPO / "tools/nxshader"
    if not desired.is_dir():
        return False
    installed = core.shader_tools(game)
    return installed is None or installed.resolve() != desired.resolve()


def kit_differs(game):
    release = core.game_release(game)
    if release and core.version_tuple(release) > core.version_tuple(core.VERSION):
        return False
    runtime = available_runtime()
    return (core.outdated_release(game) or (runtime.is_file() and
            build.marker_value(runtime, build.RUNTIME_MARKER) is not None
            and (release is not None or build.marker_value(game.exe, build.RUNTIME_MARKER) is not None)
            and (build.file_hash(runtime) != build.file_hash(game.exe) or tools_differ(game))))


def kit_revision():
    runtime = available_runtime()
    identity = build.file_hash(runtime) if runtime.is_file() else build.runtime_contract()
    return build.digest([identity, core.VERSION, str(core.REPO)])


def plan(game, source=None):
    """Use the installed compiler provenance on kits without a compiler (notably the Deck)."""
    import switchrecomp as sw

    release = core.game_release(game)
    if release and core.version_tuple(release) > core.version_tuple(core.VERSION):
        assert_launchable(game, require_identity=True)
        return READY
    module = game.root / core.MODULE
    saved = build.read_manifest(module)
    if not saved:
        return RECOMPILE
    contract = build.runtime_contract()
    runtime = available_runtime()
    if build.marker_value(runtime, build.RUNTIME_MARKER) != contract:
        return RECOMPILE
    cc = (core.REPO / "gcc/Library/bin/x86_64-w64-mingw32-gcc.exe" if core.WINDOWS
          else shutil.which("gcc"))
    try:
        flags = sw.extra_cflags("gcc")
        if flags:
            return RECOMPILE
        installed_compiler = saved["inputs"]["compiler"]
        cross = not core.WINDOWS and installed_compiler.get("driver") == "zig-cc"
        if cc and Path(cc).is_file() and not cross:
            compiler = sw.compiler_identity(str(cc))
            environment = sw.module_compiler_environment(str(cc), sw.DEFAULT_OPT, core.WINDOWS, flags, compiler)
        else:
            compiler = installed_compiler
            environment = saved["inputs"].get("compiler_environment")
        exefs, romfs = (source / "exefs", source / "romfs") if source else (game.exefs, game.romfs)
        if source and (exefs.resolve() != game.exefs or romfs.resolve() != game.romfs):
            return RECOMPILE
        expected = sw.orbitals_inputs(exefs, romfs, sw.read_hints(game.root / "Orbitals.hints"),
                                      core.WINDOWS, compiler, flags, compiler_environment=environment)
        if cross:
            expected["options"]["cross_recipe"] = build.source_hash(("tools/steamdeck/cross/build.py",))
        if saved["inputs"] != expected or not build.verified_module(module, saved, contract):
            return RECOMPILE
    except (AttributeError, OSError, ValueError, KeyError, subprocess.SubprocessError):
        return RECOMPILE
    return READY if build.file_hash(game.exe) == build.file_hash(runtime) and not tools_differ(game) else FAST


def assert_launchable(game, *, require_identity=False):
    module = game.root / core.MODULE
    contract = build.marker_value(game.exe, build.RUNTIME_MARKER)
    manifest = build.read_manifest(module)
    if not require_identity and contract is None and not build.manifest_path(module).exists():
        if build.marker_value(module, build.MODULE_MARKER) is None:
            return  # the previous, pre-fingerprint installation
    if (contract is None or not build.verified_module(module, manifest, contract)
            or build.manifest_ids(manifest) != game.ids
            or manifest["inputs"]["game"] != build.game_inputs(game.exefs, game.romfs)):
        raise core.LauncherError("The runtime and recompiled code are incompatible. Update Orbitals or restore the previous version.")


def _journal(root):
    try:
        with core.read_local(root, Path(JOURNAL)) as stream:
            state = json.load(stream)
    except FileNotFoundError:
        return None
    if (not isinstance(state, dict) or state.get("phase") not in {"pending", "applied", "restoring"}
            or not isinstance(state.get("files"), dict)
            or not all(name in PAYLOAD and type(had_file) is bool for name, had_file in state["files"].items())
            or Path(str(state.get("work"))).name != state.get("work")
            or not state["work"].startswith(".orbitals-payload-")):
        raise core.LauncherError("The update journal is invalid.")
    return state


def _restore(root, state):
    work = root / state["work"]
    if not stat.S_ISDIR(core.safe_entry(work).st_mode):
        raise core.LauncherError("The previous installation is unavailable.")
    build.write_json(root / JOURNAL, state | {"phase": "restoring"})
    for name in reversed(PAYLOAD):
        if name not in state["files"]:
            continue
        live, previous = root / name, work / "previous" / name
        if os.path.lexists(previous):
            if os.path.lexists(live):
                live.rename(work / "discard" / name)
            previous.rename(live)
        elif not state["files"][name] and os.path.lexists(live):
            live.rename(work / "discard" / name)
    (root / JOURNAL).unlink()
    shutil.rmtree(work, ignore_errors=True)


def recover(root):
    state = _journal(root)
    if state and state["phase"] != "applied":
        _restore(root, state)


def can_restore(root):
    try:
        state = _journal(root)
        return bool(state and state["phase"] == "applied")
    except (OSError, ValueError):
        return False


def rollback(root):
    with core.instance_lock(root / LOCK):
        state = _journal(root)
        if not state:
            raise core.LauncherError("There is no previous version to restore.")
        _restore(root, state)
    return core.installation(root)


def _publish(root, stage, work):
    previous_update = _journal(root)
    state = {"phase": "pending", "work": work.name,
             "files": {name: os.path.lexists(root / name) for name in PAYLOAD if os.path.lexists(stage / name)}}
    build.write_json(root / JOURNAL, state)
    try:
        for name, exists in state["files"].items():
            if exists:
                (root / name).rename(work / "previous" / name)
            (stage / name).rename(root / name)
        build.write_json(root / JOURNAL, state | {"phase": "applied"})
    except (OSError, ValueError):
        _restore(root, state)
        if previous_update:
            build.write_json(root / JOURNAL, previous_update)
        raise
    if previous_update:
        shutil.rmtree(root / previous_update["work"], ignore_errors=True)


def _stage_tools(stage, game, install_dir, rebuilt):
    shaders = core.REPO / "tools/nxshader"
    if shaders.is_dir():
        core.link_directory(stage / "nxshader", shaders)
    if core.WINDOWS:
        sdl = core.REPO / "bin/SDL3.dll"
        if sdl.is_file():
            shutil.copy2(sdl, stage / sdl.name)
        play = core.REPO / "tools/release/Play-Orbitals.ps1"
        if play.is_file():
            shutil.copy2(play, stage / play.name)
        if rebuilt:
            for name, target in (("toolchain", install_dir / "toolchain"), ("python", core.REPO / "python")):
                if target.is_dir():
                    core.link_directory(stage / name, target)
    elif (game.root / "orbitals-deck.sh").is_file():
        shutil.copy2(core.REPO / "tools/steamdeck/orbitals-deck.sh", stage / "orbitals-deck.sh")


def _check_native_pair(stage):
    try:
        result = subprocess.run([str(stage / core.EXE), "--check-code"], cwd=stage, timeout=30,
                                capture_output=True, stdin=subprocess.DEVNULL,
                                creationflags=subprocess.CREATE_NO_WINDOW if core.WINDOWS else 0)
    except (OSError, subprocess.SubprocessError) as error:
        raise core.LauncherError("The staged runtime could not check the recompiled code. The current version can still be used.") from error
    if result.returncode:
        raise core.LauncherError("The staged runtime refused the recompiled code. The current version can still be used.")


def apply(game, choice, *, install_dir=None, on_progress=lambda *args: None, managed=None):
    """Stage everything on the selected volume before replacing individual program files."""
    root = game.root
    install_dir = Path(install_dir or core.REPO / "games").resolve()
    started = time.monotonic()
    with core.instance_lock(root / LOCK):
        recover(root)
        game = core.installation(root)
        current = plan(game)
        if choice in {FAST, READY} and current == RECOMPILE:
            raise core.LauncherError("Quick update refused. The existing code does not match this kit. Recompile to update.")
        if current == READY and choice != RECOMPILE:
            return game
        rebuilt = choice == RECOMPILE
        work = Path(tempfile.mkdtemp(dir=root, prefix=".orbitals-payload-"))
        try:
            stage = work / "new"
            for folder in (stage, work / "previous", work / "discard"):
                folder.mkdir()
            if rebuilt:
                data = stage / core.DATA
                data.mkdir()
                core.link_directory(data / "exefs", game.exefs)
                core.link_directory(data / "romfs", game.romfs)
                hints = root / "Orbitals.hints"
                if hints.is_file():
                    shutil.copy2(hints, stage / hints.name)
                with core.instance_lock(install_dir):
                    core.install_from_files(data, install_dir, on_progress, game_dir=stage,
                                            object_cache=root / "Orbitals_build/objects-v1")
                assert_launchable(core.installation(stage), require_identity=True)
                _check_native_pair(stage)
            else:
                shutil.copy2(available_runtime(), stage / core.EXE)
                saved = build.read_manifest(root / core.MODULE)
                if saved is None or build.marker_value(stage / core.EXE, build.RUNTIME_MARKER) != saved["inputs"]["contract"]:
                    raise core.LauncherError("Quick update refused. The kit runtime changed while the update was being prepared.")
                probe = stage / core.MODULE
                try:
                    os.link(root / core.MODULE, probe)
                except OSError:
                    shutil.copy2(root / core.MODULE, probe)
                try:
                    _check_native_pair(stage)
                finally:
                    probe.unlink()
            _stage_tools(stage, game, install_dir, rebuilt)
            if managed is not None:
                build.write_json(stage / BUILD_INFO, managed)
            _publish(root, stage, work)
            try:
                shutil.rmtree(stage)
            except OSError:
                core.LOG.warning("event=update_stage_cleanup_failed", exc_info=True)
        finally:
            state = _journal(root)
            if not state or state["work"] != work.name:
                shutil.rmtree(work, ignore_errors=True)
    core.LOG.info("event=code_update kind=%s elapsed_seconds=%.3f", "recompile" if rebuilt else "quick",
                  time.monotonic() - started)
    return core.installation(root)
