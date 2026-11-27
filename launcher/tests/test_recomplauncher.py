"""Exercise managed installs and frontend handoffs with game-free fixtures."""

import contextlib
import io
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from launcher import VERSION, core, recomplauncher as managed
from launcher.tests.test_nup import package_archive
from test_launcher import build_fixture


class RecompLauncherTest(unittest.TestCase):
    def setUp(self):
        scratch = tempfile.TemporaryDirectory()
        self.addCleanup(scratch.cleanup)
        self.root = Path(scratch.name).resolve()
        self.data = self.root / "frontend data"
        self.local = self.data / "launcher"
        self.game = self.data / "games" / "Orbitals"
        self.source = build_fixture(self.root / "my copy")
        self.enterContext(patch.dict(os.environ, {"RECOMPLAUNCHER": "1", "RECOMPLAUNCHER_VERSION": "test"}))

    def run_managed(self, *args, **kwargs):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = managed.main([*args, "--data", str(self.data)], **kwargs)
        return code, out.getvalue()

    def install_fixture(self, source, destination, **kwargs):
        fixture = self.root / "fixture binaries"
        if not fixture.exists():
            build_fixture(fixture)
        (destination / core.DATA).mkdir(parents=True)
        for ext in (core.EXE, core.MODULE):
            (destination / ext).write_bytes((fixture / ext).read_bytes())
        (destination / core.EXE).chmod(0o755)
        with (destination / core.MODULE).open("ab") as module:
            for build_id in core.build_ids(source / "exefs").values():
                module.write(bytes.fromhex(build_id))
        for leaf in ("exefs", "romfs"):
            core.link_directory(destination / core.DATA / leaf, source / leaf)
        return core.installation(destination)

    def prepare_fixture(self):
        with patch.object(managed, "stage_install", side_effect=self.install_fixture):
            code, out = self.run_managed("--prepare", f"--game={self.source}")
        self.assertEqual(code, 0, out)

    def test_mixed_nup_setup_reuses_the_extracted_base_for_both_frontends(self):
        base = {path.relative_to(self.source).parts: path.read_bytes()
                for path in self.source.rglob("*") if path.is_file()}
        archive = self.root / "my copy.NUP"

        def pack_update(payload):
            patch_files = {("exefs", "main"): payload, ("romfs", "update.txt"): payload}
            archive.write_bytes(package_archive([(1, patch_files, {}), (0, base, {})]))

        def compile_fixture(data, install_dir, on_progress, *, game_dir):
            self.assertEqual(data, game_dir / core.DATA)
            self.assertEqual((data / "exefs/main").read_bytes(), base["exefs", "main"])
            self.assertFalse((data / "romfs/update.txt").exists())
            for name in (core.EXE, core.MODULE):
                (game_dir / name).write_bytes((self.source.parent / name).read_bytes())
            (game_dir / core.EXE).chmod(0o755)
            return core.installation(game_dir)

        pack_update(b"first update")
        with patch.object(core, "install_from_files", side_effect=compile_fixture) as compile:
            code, out = self.run_managed("--prepare", f"--game={archive}")
        self.assertEqual(code, 0, out)
        compile.assert_called_once()
        self.assertEqual(core.game_source(core.installation(self.game)), self.game / core.DATA)
        self.assertTrue(managed.build_info(self.game)["nup_base"])

        pack_update(b"different update")
        with (patch.object(managed, "stage_install") as install,
              patch.object(managed.code_update, "plan", return_value=managed.code_update.READY) as plan):
            result = self.run_managed("--prepare", f"--game={archive}")
            self.assertEqual(result[0], 0, result[1])
            self.assertIn("Already built", result[1])
            archive.unlink()
            result = self.run_managed("--prepare")
            self.assertEqual(result[0], 0, result[1])
            self.assertIn("Already built", result[1])
            install.assert_not_called()
            self.assertIsNone(plan.call_args.args[1])
        with (patch.object(managed, "play", return_value=0) as play,
              patch.object(managed.code_update, "kit_differs", return_value=False)):
            self.assertEqual(self.run_managed("--play")[0], 0)
            os.environ.pop("RECOMPLAUNCHER_VERSION")
            self.assertEqual(self.run_managed("--play")[0], 0)
        self.assertEqual([call.args[1].root for call in play.call_args_list], [self.game, self.game])

    def test_update_only_nup_reports_that_the_base_game_is_missing(self):
        archive = self.root / "update.nup"
        archive.write_bytes(package_archive([(1, {("exefs", "main"): b"update"}, {})]))
        with patch.object(managed, "stage_install") as install:
            code, out = self.run_managed("--prepare", f"--game={archive}")
        self.assertEqual(code, 1, out)
        self.assertIn("no base game package", out)
        install.assert_not_called()

    def test_prepare_repairs_moved_game_copy_with_portable_marker_present(self):
        self.prepare_fixture()
        kit = self.root / "kit"
        kit.mkdir()
        (kit / "portable.txt").touch()
        moved = self.root / "moved copy"
        self.source.rename(moved)
        with (patch.object(core, "REPO", kit), patch.object(managed, "stage_install") as compile_game,
              patch.object(managed.code_update, "plan", return_value=managed.code_update.READY)):
            code, out = self.run_managed("--play")
            self.assertEqual(code, 2)
            self.assertIn("Select it again", out)
            code, out = self.run_managed("--prepare", f"--game={moved}")
            self.assertEqual(code, 0, out)
            self.assertIn("Game data reconnected", out)
            compile_game.assert_not_called()
        self.assertEqual(managed.build_info(self.game)["source"], str(moved))
        self.assertEqual(core.game_source(core.installation(self.game)), moved)
        self.assertTrue((self.local / "launcher.json").is_file())
        self.assertFalse((kit / "portable-data").exists())

    def test_prepare_updates_repaired_installation_when_new_codegen_requires_it(self):
        self.prepare_fixture()
        moved = self.root / "moved copy"
        self.source.rename(moved)
        with (patch.object(managed.code_update, "plan", return_value=managed.code_update.RECOMPILE),
              patch.object(managed.code_update, "apply", side_effect=lambda game, *a, **k: game) as apply):
            code, out = self.run_managed("--prepare", f"--game={moved}")
        self.assertEqual(code, 0, out)
        self.assertIn("Recompilation required", out)
        self.assertEqual(apply.call_args.args[0].exefs, moved / "exefs")
        self.assertEqual(apply.call_args.args[1], managed.code_update.RECOMPILE)

    def test_bad_copy_and_failed_build_keep_the_previous_install(self):
        self.prepare_fixture()
        before = (self.game / managed.BUILD).read_bytes()
        bad = build_fixture(self.root / "incomplete copy")
        (bad / "exefs/main.npdm").unlink()
        with patch.object(core, "install_from_files", side_effect=core.LauncherError("Missing ExeFS")):
            code, out = self.run_managed("--prepare", f"--game={bad}")
        self.assertEqual(code, 1, out)
        self.assertIn("Missing ExeFS", out)
        self.assertEqual((self.game / managed.BUILD).read_bytes(), before)
        self.assertEqual(core.game_source(core.installation(self.game)), self.source)

    def test_shader_failure_keeps_the_previous_install(self):
        self.prepare_fixture()
        other = build_fixture(self.root / "another copy", b"p")
        with patch.object(managed, "stage_install", side_effect=self.install_fixture), \
                patch.object(managed, "prepare_shaders", side_effect=core.LauncherError("Shader preparation stopped")):
            code, out = self.run_managed("--prepare", f"--game={other}", "--shaders")
        self.assertEqual(code, 1, out)
        self.assertIn("Shader preparation stopped", out)
        self.assertEqual(core.game_source(core.installation(self.game)), self.source)
        self.assertFalse(self.game.with_name(managed.PREVIOUS).exists())

    def test_rebuild_publishes_new_metadata_and_preserves_existing_saves(self):
        self.prepare_fixture()
        self.assertEqual(managed.build_info(self.game)["release"], VERSION)
        saves = core.installation(self.game).saves
        saves.mkdir()
        (saves / "ProfileSave").write_bytes(b"GVASfixture")
        other = build_fixture(self.root / "another copy", b"p")
        with patch.object(managed, "stage_install", side_effect=self.install_fixture):
            code, out = self.run_managed("--prepare", f"--game={other}")
        self.assertEqual(code, 0, out)
        self.assertEqual(managed.build_info(self.game)["source"], str(other))
        self.assertEqual((saves / "ProfileSave").read_bytes(), b"GVASfixture")
        self.assertTrue((self.source / "exefs/main").is_file())
        self.assertFalse(self.game.with_name(managed.PREVIOUS).exists())
        with patch.object(managed, "stage_install") as install, \
                patch.object(managed.code_update, "plan", return_value=managed.code_update.READY):
            result = self.run_managed("--prepare")
        self.assertIn("Already built", result[1])
        install.assert_not_called()

    def test_missing_active_folder_recovers_interrupted_publication(self):
        self.prepare_fixture()
        self.game.rename(self.game.with_name(managed.PREVIOUS))
        with patch.object(managed, "stage_install") as install, \
                patch.object(managed.code_update, "plan", return_value=managed.code_update.READY):
            code, out = self.run_managed("--prepare")
        self.assertEqual(code, 0, out)
        self.assertTrue(self.game.is_dir())
        self.assertIn("Already built", out)
        install.assert_not_called()

    def test_quiver_opens_liftoff_without_holding_its_profile_lock(self):
        os.environ.pop("RECOMPLAUNCHER_VERSION")
        opened = []

        def liftoff(args):
            with core.instance_lock(self.local):
                opened.extend(args)
            return 0

        with patch.object(managed, "detect_installation", return_value=None):
            code, out = self.run_managed("--play", open_liftoff=liftoff)
        self.assertEqual(code, 0, out)
        self.assertEqual(opened, ["--data-dir", str(self.local)])

    def test_quiver_uses_selected_liftoff_install_and_session_only_settings(self):
        os.environ.pop("RECOMPLAUNCHER_VERSION")
        game_dir = self.root / "Liftoff installation"
        build_fixture(game_dir)
        with (game_dir / core.EXE).open("ab") as exe:
            exe.write(f"\0{VERSION} abcdef1\0".encode("ascii"))
        core.Profiles(self.local).update(install=str(game_dir))

        def launch(game, profiles, *, overrides):
            self.assertEqual(game.root, game_dir)
            self.assertEqual(profiles.settings["tv_resolution"], "1080p (console)")
            self.assertEqual(overrides, {"tv_resolution": "3440×1440 (ultrawide)", "stretch_wide": True})
            run = profiles.directory / "runs" / "test"
            run.mkdir(parents=True)
            (run / "Orbitals.log").write_text("Fixture", encoding="utf-8")
            return type("Process", (), {"wait": lambda self: 0})(), run

        with patch.object(managed, "launch", side_effect=launch) as play, \
                patch.object(managed.code_update, "available_runtime", return_value=self.root / "no bundled runtime"):
            code, out = self.run_managed("--play", "--set=tv_resolution=3440×1440 (ultrawide)", "--set=stretch_wide=true")
        self.assertEqual(code, 0, out)
        play.assert_called_once()
        self.assertEqual(core.Profiles(self.local).settings["tv_resolution"], "1080p (console)")
        self.assertFalse(core.Profiles(self.local).settings["stretch_wide"])

    def test_prepare_and_play_use_the_same_lock(self):
        with core.instance_lock(self.local):
            code, out = self.run_managed("--prepare", f"--game={self.source}")
        self.assertEqual(code, 1, out)
        self.assertIn("already open", out)

    def test_prepare_reuses_compatible_code_in_the_managed_folder(self):
        self.prepare_fixture()
        game = core.installation(self.game)
        with patch.object(managed.code_update, "plan", return_value=managed.code_update.FAST), \
                patch.object(managed.code_update, "apply", return_value=game) as update, \
                patch.object(managed, "stage_install") as install:
            code, out = self.run_managed("--prepare")
        self.assertEqual(code, 0, out)
        self.assertIn("Quick update", out)
        self.assertEqual(update.call_args.args[0].root, self.game)
        install.assert_not_called()

    def test_quiver_opens_liftoff_with_selected_install_when_update_is_available(self):
        self.prepare_fixture()
        os.environ.pop("RECOMPLAUNCHER_VERSION")
        with patch.object(managed.code_update, "kit_differs", return_value=True), \
                patch.object(managed, "launch") as launch:
            code, out = self.run_managed("--play", open_liftoff=lambda args: self.assertEqual(
                args, ["--data-dir", str(self.local), "--game-dir", str(self.game)]) or 0)
        self.assertEqual(code, 0, out)
        launch.assert_not_called()

    def test_managed_launcher_never_checks_or_switches_kits(self):
        opener = lambda *a, **k: self.fail("update network request")
        with patch.object(core, "MANAGED", True), patch.object(core.subprocess, "Popen") as process:
            for attempt in (lambda: core.check_update(opener=opener),
                            lambda: core.download_update({}, opener=opener), lambda: core.launch_kit(self.root)):
                with self.assertRaisesRegex(core.LauncherError, "Check for updates"):
                    attempt()
            process.assert_not_called()
