# Orbitals PC Recomp, a work based on SwitchRecomp by MZ Labs. GNU AGPL v3.0 with the additional terms of NOTICE.txt (LICENSE.txt).
"""Add to Steam (launcher/steam.py), on a stand-in Steam folder."""
import struct
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from launcher import core, steam


class SteamTest(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name).resolve()
        self.user = self.root / "Steam/userdata/123/config"
        self.user.mkdir(parents=True)
        (self.root / "Steam/userdata/0").mkdir()
        self.vdf = self.user / "shortcuts.vdf"
        self.images = {}
        for suffix in ("p.png", ".png", "_hero.png"):
            self.images[suffix] = self.root / ("image" + suffix)
            self.images[suffix].write_bytes(b"ours" + suffix.encode())
        for name, value in (("target", ("C:/Python/pythonw.exe", "-B -m launcher", "C:/kit")), ("steam_running", False)):
            p = patch.object(steam, name, return_value=value); p.start(); self.addCleanup(p.stop)

    def rows(self):
        return list(steam.read_map(self.vdf.read_bytes(), 0)[0]["shortcuts"].values())

    def test_other_shortcuts_are_kept_and_ours_is_not_doubled(self):
        other = {"appid": -5, "AppName": "Another game é", "Exe": '"C:/Python/pythonw.exe"', "LaunchOptions": "other.py",
                 "LastPlayTime": ("u64", 1 << 40), "tags": {"0": "Favourite"}, "Unknown": "kept"}
        self.vdf.write_bytes(steam.write_map({"shortcuts": {"0": other}}))
        before = self.vdf.read_bytes()
        for _ in range(2):
            self.assertEqual(steam.add(self.images, self.root / "Steam"), "Added to Steam.")
        rows = self.rows()
        self.assertEqual(rows[0], other)
        self.assertEqual([row["AppName"] for row in rows], ["Another game é", steam.NAME])
        self.assertEqual((rows[1]["Exe"], rows[1]["LaunchOptions"], rows[1]["StartDir"]),
                         ('"C:/Python/pythonw.exe"', "-B -m launcher", '"C:/kit"'))
        self.assertTrue(before.startswith(b"\x00shortcuts\x00\x000\x00"))
        self.assertTrue((self.user / "shortcuts.vdf.before-orbitals").is_file())
        self.assertFalse(list(self.user.glob("*.part")))

    def test_a_moved_kit_replaces_its_entry(self):
        steam.add(self.images, self.root / "Steam")
        with patch.object(steam, "target", return_value=("D:/other/pythonw.exe", "-B -m launcher", "D:/kit")):
            steam.add(self.images, self.root / "Steam")
        self.assertEqual([row["StartDir"] for row in self.rows()], ['"D:/kit"'])

    def test_images_the_player_set_stay(self):
        steam.add(self.images, self.root / "Steam")
        appid = steam.app_id("C:/Python/pythonw.exe")
        grid = self.user / "grid"
        self.assertEqual((grid / f"{appid}p.png").read_bytes(), b"oursp.png")
        (grid / f"{appid}p.png").write_bytes(b"the player's")
        self.images[".png"].write_bytes(b"a newer one")
        steam.add(self.images, self.root / "Steam")
        self.assertEqual((grid / f"{appid}p.png").read_bytes(), b"the player's")
        self.assertEqual((grid / f"{appid}.png").read_bytes(), b"a newer one")

    def test_an_unreadable_list_is_left_as_it_is(self):
        self.vdf.write_bytes(b"\x00shortcuts\x00\x09broken")
        with self.assertRaisesRegex(core.LauncherError, "left as it is"):
            steam.add(self.images, self.root / "Steam")
        self.assertEqual(self.vdf.read_bytes(), b"\x00shortcuts\x00\x09broken")

    def test_no_steam_is_said(self):
        with self.assertRaisesRegex(core.LauncherError, "not found"):
            steam.add(self.images, self.root / "nowhere")

    def test_images_have_steams_sizes(self):
        sizes = {suffix: struct.unpack(">II", path.read_bytes()[16:24]) for suffix, path in steam.images().items()}
        self.assertEqual({suffix: size for suffix, size in sizes.items() if suffix != "_logo.png"},
                         {"p.png": (600, 900), ".png": (920, 430), "_hero.png": (1920, 620)})


if __name__ == "__main__":
    unittest.main()
