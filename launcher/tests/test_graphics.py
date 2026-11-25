# Orbitals PC Recomp, a work based on SwitchRecomp by MZ Labs. GNU AGPL v3.0 with the additional terms of NOTICE.txt (LICENSE.txt).
"""Graphics settings: presets, validation, persistence per profile, and what a launch writes (overlay file, Orbitals.ini keys)."""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from launcher import core, graphics
from test_launcher import build_fixture


class GraphicsTest(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name).resolve()
        self.profiles = core.Profiles(self.root / "launcher")

    def test_high_is_the_original_and_writes_nothing(self):
        sg, ini, files = graphics.launch_changes({"preset": "High"})
        self.assertEqual((sg, ini, files), ({}, {}, {}))
        self.assertTrue(all(v == graphics.ORIGINAL for v in graphics.resolve({"preset": "High"}).values()))

    def test_every_option_starts_with_original_and_presets_use_known_values(self):
        for name, (caption, values) in graphics.OPTIONS.items():
            self.assertEqual(next(iter(values)), graphics.ORIGINAL, name)
            self.assertEqual(values[graphics.ORIGINAL], {}, name)
        for preset, chosen in graphics.PRESETS.items():
            for name, value in chosen.items():
                self.assertIn(value, graphics.OPTIONS[name][1], (preset, name))

    def test_presets_choose_the_games_3d_resolution(self):
        native = self.root / "game"
        build_fixture(native)
        game = core.installation(native)
        for preset, mode, docked in (("High", "Portable", "--docked=1"), ("Low", "TV", "--docked=0"), ("Performance", "Portable", "--docked=1"),
                                     ("Custom", "TV", "--docked=1"), ("Custom", "Portable", "--docked=0")):
            argv, env = core.launch_options(game, self.root, self.root / "cache", self.profiles.settings | {"gfx_preset": preset, "mode": mode})
            self.assertIn(docked, argv, (preset, mode))
        with self.assertRaises(core.LauncherError):
            core.launch_options(game, self.root, self.root / "cache", self.profiles.settings | {"gfx_preset": "Medium"})

    def test_performance_preset_is_720p_3d(self):
        sg, ini, files = graphics.launch_changes({"preset": "Performance", "mode": "Portable"})
        self.assertEqual((sg, ini), ({}, {}))
        self.assertEqual(files, {graphics.ENGINE: "[SystemSettings]\nr.SecondaryScreenPercentage.GameViewport=66.6667\n"})
        self.assertEqual(graphics.PRESET_ORDER[-1], "Custom")

    def test_custom_values_are_validated(self):
        for name in graphics.OPTIONS:
            with self.assertRaises(ValueError):
                graphics.validate({"preset": "Custom", name: "not a value"})
        with self.assertRaises(ValueError):
            graphics.validate({"preset": "Ultra"})

    def test_overlay_text_lists_the_scalability_groups(self):
        for preset in graphics.PRESET_ORDER[:-1]:
            sg, ini, files = graphics.launch_changes({"preset": preset})
            if sg:
                text = files[graphics.GUS]
                self.assertIn("[ScalabilityGroups]", text)
                for k, v in sg.items():
                    self.assertIn(f"{k}={v}\n", text)

    def test_profile_persistence_and_reset(self):
        self.assertEqual(self.profiles.settings["gfx_preset"], "High")
        self.profiles.update_active(settings={"gfx_preset": "Low", "fps": "60 (experimental)"})
        reloaded = core.Profiles(self.profiles.root)
        self.assertEqual(reloaded.settings["gfx_preset"], "Low")
        self.assertEqual(reloaded.settings["fps"], "60 (experimental)")
        core.validate_settings(reloaded.settings)
        reloaded.update_active(settings={})
        self.assertEqual(core.Profiles(self.profiles.root).settings["gfx_preset"], "High")
        with self.assertRaises(core.LauncherError):
            core.validate_settings(reloaded.settings | {"gfx_preset": "Ultra"})

    def test_launch_writes_overlay_and_ini_in_the_session_only(self):
        native = self.root / "game"
        build_fixture(native)
        game = core.installation(native)
        for preset in graphics.PRESET_ORDER[:-1]:
            run = core.session_directory(game, self.profiles)
            text = core.apply_graphics(run, "ue_fps=0\n", self.profiles.settings | {"gfx_preset": preset})
            sg, ini, files = graphics.launch_changes({"preset": preset})
            for rel, body in files.items():
                self.assertEqual((run / core.DATA / "romfs_overlay" / rel).read_text(encoding="utf-8"), body)
            for k, v in ini.items():
                self.assertIn(f"\n{k}={v}\n", "\n" + text)
            self.assertFalse((native / core.DATA / "romfs_overlay").exists(), "the game folder is never written")
            core.prune_run_payload(run)

    def test_scaled_scene_resolution_is_independent_of_output(self):
        native = self.root / "game"
        build_fixture(native)
        game = core.installation(native)
        for size, percent in (("960x540", "50"), ("1280x720", "66.6667"), ("1600x900", "83.3333")):
            with self.subTest(scene=size):
                settings = {"gfx_preset": "Custom", "mode": size, "size": "2560x1440", "upscale": "FSR1"}
                self.profiles.update_active(settings=settings)
                session_settings = core.Profiles(self.profiles.root).settings
                run = core.session_directory(game, self.profiles)
                self.addCleanup(core.prune_run_payload, run)
                core.apply_graphics(run, "ue_fps=0\n", session_settings)
                argv, env = core.launch_options(game, run, self.root / "cache", session_settings)
                self.assertIn("--docked=1", argv)
                self.assertEqual(env["SWR_WINDOW_SIZE"], "2560x1440")
                self.assertEqual(env["NXRT_VK_UPSCALE"], "fsr1")
                overlay = run / core.DATA / "romfs_overlay" / graphics.ENGINE
                self.assertEqual(overlay.read_text(encoding="utf-8"),
                                 f"[SystemSettings]\nr.SecondaryScreenPercentage.GameViewport={percent}\n")
        for preset in ("High", "Low"):
            self.assertEqual(graphics.launch_changes({"preset": preset, "mode": "960x540"})[2], {})

    def test_async_30_fps_writes_the_existing_runtime_mode(self):
        native = self.root / "game"
        build_fixture(native)
        game = core.installation(native)
        self.profiles.update_active(settings={"fps": "30 (async replay)"})
        run = core.session_directory(game, self.profiles)
        self.addCleanup(core.prune_run_payload, run)
        with patch.object(core, "session_directory", return_value=run), patch.object(core.subprocess, "Popen"):
            core.launch(game, self.profiles)
        self.assertIn("\nue_fps=30\n", (run / "Orbitals.ini").read_text(encoding="utf-8"))


class UpdateCheckTest(unittest.TestCase):
    """core.check_update against canned GitHub answers (no network)."""
    def opener(self, payload, fail=False):
        import io, json as j
        class Answer(io.BytesIO):
            def __enter__(self): return self
            def __exit__(self, *a): return False
        def open_(request, timeout):
            self.seen = request.full_url
            if fail: raise OSError("offline")
            return Answer(j.dumps(payload).encode())
        return open_

    def test_unconfigured_repository_makes_no_request(self):
        self.assertIsNone(core.check_update("0.1.0", repository="", opener=self.opener({}, fail=True)))

    def test_inaccessible_release_can_be_opened_in_signed_in_browser(self):
        from urllib.error import HTTPError

        def private(request, timeout):
            raise HTTPError(request.full_url, 404, "Not Found", None, None)

        with self.assertRaisesRegex(core.LauncherError, "Open releases"):
            core.check_update(repository="o/r", opener=private)

    def test_newer_same_and_errors(self):
        rel = {"tag_name": "v0.2.0", "html_url": "https://github.com/o/r/releases/tag/v0.2.0", "body": "notes"}
        info = core.check_update("0.1.0", repository="o/r", opener=self.opener(rel))
        self.assertEqual(self.seen, "https://api.github.com/repos/o/r/releases/latest")
        self.assertTrue(info["newer"]); self.assertEqual(info["latest"], "v0.2.0")
        self.assertFalse(core.check_update("0.2.0", repository="o/r", opener=self.opener(rel))["newer"])
        self.assertFalse(core.check_update("0.10.0", repository="o/r", opener=self.opener(rel))["newer"])
        with self.assertRaises(core.LauncherError):
            core.check_update("0.1.0", repository="o/r", opener=self.opener(rel, fail=True))
        with self.assertRaises(core.LauncherError):
            core.check_update("0.1.0", repository="o/r", opener=self.opener({"tag_name": "v9", "html_url": "https://evil.example/x"}))
        with self.assertRaises(core.LauncherError):
            core.check_update("0.1.0", repository="not a repo")


class CacheSeedTest(unittest.TestCase):
    def test_first_launch_starts_from_the_game_folders_cache(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            native = root / "game"; build_fixture(native)
            (native / "Orbitals_nvn/cache/vk").mkdir(parents=True); (native / "Orbitals_nvn/cache/vk/a.spv").write_bytes(b"x")
            (native / "Orbitals_nvn/cache/dumps").mkdir(); (native / "Orbitals_nvn/cache/dumps/k.ctl").write_bytes(b"d")
            cache = root / "launcher-cache"
            core.seed_cache(core.installation(native), cache)
            self.assertEqual((cache / "cache/vk/a.spv").read_bytes(), b"x")
            self.assertFalse((cache / "cache/dumps").exists())
            (native / "Orbitals_nvn/cache/vk/b.spv").write_bytes(b"y")
            core.seed_cache(core.installation(native), cache)   # only the first time
            self.assertFalse((cache / "cache/vk/b.spv").exists())


class InstallTest(unittest.TestCase):
    """core.install_from_files with a stand-in for setup-windows.ps1: input checks, progress, log, the installation it returns."""
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name).resolve()

    def fake(self, code=0):
        script = self.root / "fake_setup.py"
        script.write_text(
            "import sys\nsys.path.insert(0, sys.argv[2]); sys.path.insert(0, sys.argv[3])\nfrom pathlib import Path\nfrom test_launcher import build_fixture\n"
            "for i, s in enumerate(('Python and GCC', 'tools', 'runtime', 'game code', 'folder'), 1): print(f'[{i}/5] {s}', flush=True)\n"
            f"o = Path(sys.argv[1]) / 'Orbitals'\nif not o.exists(): build_fixture(o)\nsys.exit({code})\n", encoding="utf-8")
        return script

    def test_checks_the_players_folder(self):
        (self.root / "dump/exefs").mkdir(parents=True)
        with self.assertRaisesRegex(core.LauncherError, "exefs/main"):
            core.install_from_files(self.root / "dump", self.root / "games", command=["unused"])

    def test_linux_setup_uses_the_archive_and_checks_dotnet_10(self):
        tools = self.root / "tools"
        tools.mkdir()
        script = tools / "build-orbitals-linux.sh"
        script.touch()
        with patch.object(core, "REPO", self.root), patch.object(core, "install_jobs", return_value=2), \
             patch.object(core.shutil, "which", side_effect=lambda name: f"/usr/bin/{name}"), \
             patch.object(core.subprocess, "run") as probe:
            probe.return_value.returncode = 0
            probe.return_value.stdout = "Microsoft.NETCore.App 9.0.5 [/usr/share/dotnet]\n"
            with self.assertRaisesRegex(core.LauncherError, r"\.NET 10 runtime"):
                core.linux_install_command(self.root / "game files", self.root / "games")
            probe.return_value.stdout += "Microsoft.NETCore.App 10.0.15 [/usr/share/dotnet]\n"
            self.assertEqual(core.linux_install_command(self.root / "game files", self.root / "games"),
                             ["/usr/bin/bash", str(script), str(self.root / "game files"),
                              str(self.root / "games/Orbitals"), "2"])

    def test_progress_log_and_installation(self):
        dump = self.root / "dump"
        (dump / "exefs").mkdir(parents=True); (dump / "romfs").mkdir()
        (dump / "exefs/main").write_bytes(b"NSO0"); (dump / "exefs/main.npdm").write_bytes(b"META")
        games = self.root / "games"
        steps = []
        import sys
        here = str(Path(__file__).resolve().parent)
        game = core.install_from_files(dump, games, on_progress=lambda s, n, t: steps.append((s, n)),
                                       command=[sys.executable, str(self.fake()), str(games), here, str(core.REPO)])
        self.assertEqual(game.root, games / "Orbitals")
        self.assertEqual(steps[-1], (5, 5))
        self.assertIn("[3/5] runtime", (games / "setup.log").read_text(encoding="utf-8"))
        with self.assertRaisesRegex(core.LauncherError, "code 3"):
            core.install_from_files(dump, games, command=[sys.executable, str(self.fake(3)), str(games), here, str(core.REPO)])


if __name__ == "__main__":
    unittest.main()

class RuntimeInfoTest(unittest.TestCase):
    def test_release_commit_and_device_from_the_log_header(self):
        with tempfile.TemporaryDirectory() as temp:
            Path(temp, "Orbitals.log").write_text(
                "[   0.00] SwitchRecomp - Orbitals (runtime 0.4.1, built Nov 22 2026)\n"
                "[   0.00] release 0.1.0-rc1 1c3321b0aa11\n"
                "[   3.42] [vk] device: AMD Radeon RX 9070 XT, AMD driver 2.0.350, Vulkan 1.4.315, queue family 0\n", encoding="utf-8")
            info = core.runtime_info((Path(temp),))
        self.assertEqual(info["recomp_version"], "0.4.1")
        self.assertEqual(info["release"], "0.1.0-rc1")
        self.assertEqual(info["commit"], "1c3321b0aa11")
        self.assertTrue(info["vulkan_device"].startswith("AMD Radeon RX 9070 XT"))

class LegacySettingsTest(unittest.TestCase):
    def test_values_saved_by_the_french_interface_still_load(self):
        with tempfile.TemporaryDirectory() as temp:
            profiles = core.Profiles(Path(temp))
            profiles.profile["settings"] = {"display": "Fenêtré", "fps": "60 (expérimental)"}
            settings = profiles.settings
        self.assertEqual(settings["display"], "Windowed")
        self.assertEqual(settings["fps"], "60 (experimental)")
        core.validate_settings(settings)

class OutputSizeTest(unittest.TestCase):
    def test_native_first_and_nothing_larger_than_the_monitor(self):
        self.assertEqual(graphics.output_sizes((2560, 1440))[0], "2560x1440")
        self.assertNotIn("3840x2160", graphics.output_sizes((2560, 1440)))
        self.assertEqual(graphics.output_sizes(None), graphics.OUTPUT_SIZES)
        for size in graphics.output_sizes((3440, 1440)):
            settings = dict(core.DEFAULT_SETTINGS, size=size)
            core.validate_settings(settings)
