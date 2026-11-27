# Orbitals PC Recomp, a work based on SwitchRecomp by MZ Labs. GNU AGPL v3.0 with the additional terms of NOTICE.txt (LICENSE.txt).
"""Auto-update and outdated games, with no network: a fake GitHub serves the archives, and fake executables carry the release."""
import hashlib
import io
import shutil
import tempfile
import unittest
import zipfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from launcher import core


def kit_zip(version, extra=None):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr(f"OrbitalsPCRecomp-{version}/launcher/__main__.py", "print('kit')\n")
        z.writestr(f"OrbitalsPCRecomp-{version}/VERSION", version + "\n")
        for name, data in (extra or {}).items():
            z.writestr(name, data)
    return buf.getvalue()


class FakeResponse(io.BytesIO):
    def __init__(self, data):
        super().__init__(data)
        self.headers = {"Content-Length": str(len(data))}


class UpdateTest(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp(prefix="orbitals-update-"))
        self.addCleanup(shutil.rmtree, self.root, ignore_errors=True)

    def release(self, archive, sums=None, version="0.2.0"):
        name = core.kit_archive(version, "windows")
        files = {name: archive, "SHA256SUMS.txt": (sums if sums is not None else
                                                    f"{hashlib.sha256(archive).hexdigest()}  {name}\n").encode()}
        base = "https://github.com/o/r/releases/download/v" + version + "/"
        info = {"latest": "v" + version, "assets": {n: base + n for n in files}}
        opener = lambda request, timeout=0: FakeResponse(files[request.full_url.rsplit("/", 1)[1]])
        return info, opener

    def test_download_checks_and_unpacks_beside_the_kit(self):
        info, opener = self.release(kit_zip("0.2.0"))
        seen = []
        kit = core.download_update(info, self.root, on_progress=lambda d, t: seen.append((d, t)), opener=opener, platform="windows")
        self.assertEqual(kit, (self.root / "OrbitalsPCRecomp-0.2.0").resolve())
        self.assertTrue((kit / "launcher/__main__.py").is_file())
        self.assertTrue(seen and seen[-1][0] == seen[-1][1])
        self.assertEqual(sorted(p.name for p in self.root.iterdir()), ["OrbitalsPCRecomp-0.2.0"])   # no .part, no staging left
        # a second call reuses it without downloading
        self.assertEqual(core.download_update(info, self.root, opener=None, platform="windows"), kit)

    def test_a_wrong_checksum_changes_nothing(self):
        info, opener = self.release(kit_zip("0.2.0"), sums="0" * 64 + "  " + core.kit_archive("0.2.0", "windows") + "\n")
        with self.assertRaises(core.LauncherError):
            core.download_update(info, self.root, opener=opener, platform="windows")
        self.assertEqual(list(self.root.iterdir()), [])

    def test_existing_unfinished_update_folder_is_preserved(self):
        info, opener = self.release(kit_zip("0.2.0"))
        target = self.root / "OrbitalsPCRecomp-0.2.0"
        target.mkdir()
        (target / "keep.txt").write_bytes(b"my files")
        with self.assertRaisesRegex(core.LauncherError, "already exists"):
            core.download_update(info, self.root, opener=opener, platform="windows")
        self.assertEqual(list(target.iterdir()), [target / "keep.txt"])
        self.assertEqual((target / "keep.txt").read_bytes(), b"my files")

    def test_a_member_outside_the_folder_is_refused(self):
        info, opener = self.release(kit_zip("0.2.0", {"../evil.txt": "x"}))
        with self.assertRaises(core.LauncherError):
            core.download_update(info, self.root, opener=opener, platform="windows")
        self.assertFalse((self.root.parent / "evil.txt").exists())
        self.assertEqual(list(self.root.iterdir()), [])

    def test_missing_assets_point_to_the_release_page(self):
        with self.assertRaises(core.LauncherError):
            core.download_update({"latest": "v0.2.0", "assets": {}}, self.root, platform="windows")


class OutdatedGameTest(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp(prefix="orbitals-outdated-"))
        self.addCleanup(shutil.rmtree, self.root, ignore_errors=True)

    def game(self, release, name="g"):
        root = self.root / name
        (root / "Orbitals_data/save").mkdir(parents=True, exist_ok=True)
        exe = root / "Orbitals.exe"
        exe.write_bytes(b"MZ\0\0junk\0" +(release.encode() + b"\0" if release else b"") + b"more")
        return SimpleNamespace(root=root, exe=exe, saves=root / "Orbitals_data/save")

    def test_release_read_from_the_executable(self):
        self.assertEqual(core.game_release(self.game("0.1.0 b8755a8c1234")), "0.1.0")
        self.assertIsNone(core.game_release(self.game(None)))

    def test_older_release_is_outdated(self):
        self.assertEqual(core.outdated_release(self.game("0.1.0 b8755a8c1234"), current="0.1.5"), "0.1.0")
        self.assertEqual(core.outdated_release(self.game("0.1.5-preview.1 6986926f8308"), current="0.1.5"), "0.1.5-preview.1")
        self.assertIsNone(core.outdated_release(self.game("0.1.5 6986926f8308"), current="0.1.5"))
        self.assertIsNone(core.outdated_release(self.game("dev unknown"), current="0.1.5"))
        self.assertEqual(core.outdated_release(self.game(None), current="0.1.5"), core.UNSTAMPED)   # v0.1.0 and older: no release string

    def test_saves_are_copied_not_moved(self):
        old, new = self.game("0.1.0 b8755a8c1234", "old"), self.game("0.1.5 6986926f8308", "new")
        (old.saves / "slot0.sav").write_bytes(b"progress")
        self.assertTrue(core.carry_saves(old, new))
        self.assertEqual((new.saves / "slot0.sav").read_bytes(), b"progress")
        self.assertTrue((old.saves / "slot0.sav").is_file())
        (new.saves / "slot0.sav").write_bytes(b"newer")
        self.assertFalse(core.carry_saves(old, new))   # never over saves the new installation already has
        self.assertEqual((new.saves / "slot0.sav").read_bytes(), b"newer")


if __name__ == "__main__":
    unittest.main()


class LinuxDepsTest(unittest.TestCase):
    """A missing Linux tool names the package and the command for the distribution (copied by the launcher)."""

    def family(self, text):
        path = Path(tempfile.mkdtemp(prefix="orbitals-osr-")) / "os-release"
        self.addCleanup(shutil.rmtree, path.parent, ignore_errors=True)
        path.write_text(text, encoding="utf-8")
        return core.linux_family(path)

    def test_families(self):
        self.assertEqual(self.family('ID=ubuntu\nID_LIKE=debian\n'), "apt")
        self.assertEqual(self.family('ID="fedora"\n'), "dnf")
        self.assertEqual(self.family('ID=cachyos\nID_LIKE=arch\n'), "pacman")
        self.assertEqual(self.family('ID=opensuse-tumbleweed\nID_LIKE="opensuse suse"\n'), "zypper")
        self.assertIsNone(self.family('ID=gentoo\n'))

    def test_command_is_copied(self):
        error = core.linux_deps_error(["gcc", "spirv-val", "spirv-opt"], "apt")
        self.assertEqual(error.copy, "sudo apt install build-essential spirv-tools")
        self.assertIn(error.copy, str(error))
        with patch.object(core, "linux_family", return_value=None):
            self.assertIsNone(core.linux_deps_error(["gcc"]).copy)


class InstallProgressTest(unittest.TestCase):
    """The installation bar follows the recompile's own count instead of sitting at one value for most of the install."""

    def test_recompile_moves_the_bar(self):
        start = core.install_fraction(4, 5, "Recompiling the game code")
        early = core.install_fraction(4, 5, "  compiled 30/886 (88s)")
        half = core.install_fraction(4, 5, "  compiled 443/886 (900s)")
        self.assertLess(start, early)
        self.assertLess(early, half)
        self.assertAlmostEqual(core.install_fraction(4, 5, "  compiled 886/886 (1800s)"), core.install_fraction(5, 5, "Completing"))
        self.assertLess(core.install_fraction(1, 5, "Python"), core.install_fraction(2, 5, "tools"))
        self.assertEqual(core.install_fraction(9, 5, "junk compiled 5/0"), 1.0)   # clamped


class PrepareOldInstallTest(unittest.TestCase):
    """An installation made by a kit older than v0.1.5 has no shader preparation tools: say so and point to UPDATE THE GAME
    (v0.1.5 on a v0.1.0 installation: "can't open file ... nxs_kraken.py")."""

    def test_old_kit_tools_give_a_clear_message(self):
        root = Path(tempfile.mkdtemp(prefix="orbitals-oldkit-"))
        self.addCleanup(shutil.rmtree, root, ignore_errors=True)
        tools = root / "nxshader"; tools.mkdir()
        (tools / "nxs_live.py").write_text("# v0.1.0 kit: the live translator only\n")
        exe = root / "Orbitals.exe"; exe.write_bytes(b"MZ\0\0\0" + b"0.1.0 b8755a8c1234\0")
        game = SimpleNamespace(root=root, exe=exe)
        from unittest.mock import patch
        with patch.object(core, "shader_tools", return_value=tools):
            with self.assertRaises(core.LauncherError) as caught:
                core.prepare_shaders(game, profiles=None)
        self.assertIn("UPDATE THE GAME", str(caught.exception))
        self.assertIn("0.1.0", str(caught.exception))
