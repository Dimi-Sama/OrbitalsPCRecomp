# Orbitals PC Recomp, a work based on SwitchRecomp by MZ Labs. GNU AGPL v3.0 with the additional terms of NOTICE.txt (LICENSE.txt).
"""RecompLauncher's setup and play without a window (launcher/recomplauncher.py), and no updates under it. No build, no network."""
import contextlib
import io
import json
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from launcher import VERSION, core, recomplauncher
from test_launcher import build_fixture   # (unittest discover -s launcher/tests)


class WindowlessTest(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp(prefix="orbitals-recomplauncher-")).resolve()
        self.addCleanup(shutil.rmtree, self.root, ignore_errors=True)
        self.data = self.root / "recompdata"
        self.games = self.data / "games"

    def run_main(self, *argv):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = recomplauncher.main(list(argv))
        return code, out.getvalue().splitlines()

    def test_already_built_by_this_release_needs_no_copy(self):
        build_fixture(self.games / "Orbitals")
        source = core.game_source(core.installation(self.games / "Orbitals"))
        (self.games / recomplauncher.BUILD).write_text(json.dumps({"release": VERSION, "source": str(source)}), encoding="utf-8")
        with patch.object(recomplauncher, "install_from_files") as install:
            code, lines = self.run_main("--prepare", "--data", str(self.data))
        self.assertEqual((code, lines[-1]), (0, "progress 1.000 Already built"))
        install.assert_not_called()

    def test_a_new_release_builds_again_and_writes_its_version_last(self):
        copy = self.root / "my copy"
        build_fixture(copy)
        source = copy / core.DATA

        def install(game_data, install_dir, on_progress, rebuild):
            self.assertFalse((install_dir / recomplauncher.BUILD).exists())   # removed before the build starts
            self.assertTrue(rebuild)
            on_progress(4, 5, "compiled 5/10")
            build_fixture(install_dir / "Orbitals")
            return core.installation(install_dir / "Orbitals")

        self.games.mkdir(parents=True)
        (self.games / recomplauncher.BUILD).write_text(json.dumps({"release": "0.1.0", "source": str(source)}), encoding="utf-8")
        with patch.object(recomplauncher, "install_from_files", side_effect=install):
            code, lines = self.run_main("--prepare", f"--game={source}", "--data", str(self.data))
        self.assertEqual(code, 0)
        self.assertTrue(lines[1].startswith("progress 0.") and "compiled 5/10" in lines[1])
        self.assertEqual(lines[-1], "progress 1.000 Ready to play")
        self.assertEqual(json.loads((self.games / recomplauncher.BUILD).read_text(encoding="utf-8")),
                         {"release": VERSION, "source": str(source)})

    def test_without_a_copy_or_a_build_it_asks_for_the_copy(self):
        code, lines = self.run_main("--prepare", "--data", str(self.data))
        self.assertEqual(code, 2)
        self.assertIn("Pick your copy again", lines[-1])

    def test_a_failed_build_ends_on_its_reason(self):
        with patch.object(recomplauncher, "install_from_files", side_effect=core.LauncherError("Orbitals setup needs: gcc.")):
            build_fixture(self.root / "copy")
            code, lines = self.run_main("--prepare", f"--game={self.root / 'copy' / core.DATA}", "--data", str(self.data))
        self.assertEqual((code, lines[-1]), (1, "Orbitals setup needs: gcc."))
        self.assertFalse((self.games / recomplauncher.BUILD).exists())

    def test_play_before_setup_says_so(self):
        code, lines = self.run_main("--play", "--data", str(self.data))
        self.assertEqual(code, 2)
        self.assertIn("Set it up again", lines[-1])

    def test_play_uses_the_session_settings_without_keeping_them(self):
        build_fixture(self.games / "Orbitals")
        seen = {}

        def launch(game, profiles):
            seen.update(profiles.settings)
            run = profiles.directory / "runs" / "session"
            run.mkdir(parents=True)
            (run / "Orbitals.log").write_text("log", encoding="utf-8")
            return type("Process", (), {"wait": lambda self: 0})(), run

        with patch.object(recomplauncher, "launch", side_effect=launch):
            code, _ = self.run_main("--play", "--data", str(self.data), "--set=fps=60 (experimental)", "--set=vsync=false")
        self.assertEqual(code, 0)
        self.assertEqual((seen["fps"], seen["vsync"], seen["display"]), ("60 (experimental)", False, "Windowed"))
        self.assertEqual(core.Profiles(self.data / "launcher").settings["fps"], "30 (reference)")
        self.assertTrue((self.data / "launcher" / "logs" / "Orbitals.log").is_file())

    def test_session_settings(self):
        self.assertEqual(recomplauncher.setting("fps=60 (experimental)"), ("fps", "60 (experimental)"))
        self.assertEqual(recomplauncher.setting("vsync=false"), ("vsync", False))
        self.assertEqual(recomplauncher.setting("keyboard=2"), ("keyboard", 2))
        self.assertEqual(recomplauncher.setting("mouse_camera=true"), ("mouse_camera", True))
        for bad in ("nope=1", "vsync=1", "volume=loud", "display="):
            with self.assertRaises(core.LauncherError):
                recomplauncher.setting(bad)

    def test_no_update_check_download_or_kit_switch_under_recomplauncher(self):
        opener = lambda *a, **k: self.fail("no request under RecompLauncher")
        with patch.object(core, "MANAGED", True), patch.object(core.subprocess, "Popen") as popen:
            for call in (lambda: core.check_update(opener=opener),
                         lambda: core.download_update({"latest": "v9.0.0", "assets": {}}, self.root, opener=opener),
                         lambda: core.launch_kit(self.root)):
                with self.assertRaisesRegex(core.LauncherError, "RecompLauncher"):
                    call()
            popen.assert_not_called()


if __name__ == "__main__":
    unittest.main()
