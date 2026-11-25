# Orbitals PC Recomp, a work based on SwitchRecomp by MZ Labs. GNU AGPL v3.0 with the additional terms of NOTICE.txt (LICENSE.txt).
"""The shortcut and the drawn files (launcher/desktop.py, launcher/assets, launcher/paint.py)."""
import struct
import subprocess
import sys
import tempfile
import unittest
import zlib
from pathlib import Path
from unittest.mock import patch

from launcher import core, desktop, fonts, paint


class ShortcutTest(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name).resolve()

    @unittest.skipUnless(core.WINDOWS, "Windows shortcuts")
    def test_the_windows_shortcut_has_its_target_icon_and_identity(self):
        with patch.object(desktop, "desktop_folder", return_value=self.root):
            self.assertIn("desktop", desktop.add_shortcut())
            desktop.add_shortcut()   # again: replaced
        link = self.root / f"{desktop.NAME}.lnk"
        data = link.read_bytes()
        for text in (str(desktop.ICON), "Orbitals-Launcher.pyw", desktop.APP_ID):
            self.assertIn(text.encode("utf-16-le"), data)
        self.assertEqual([path.name for path in self.root.iterdir()], [link.name])

    def test_the_linux_entry(self):
        path = self.root / "applications" / "orbitals.desktop"
        desktop.write_entry(path)
        text = path.read_text(encoding="utf-8")
        self.assertIn("Name=Orbitals PC Recomp", text)
        self.assertIn("orbitals-icon.png", text)

    def test_the_start_file_finds_the_launcher_from_any_folder(self):
        result = subprocess.run([sys.executable, "-B", str(desktop.START), "--help"], cwd=self.root, capture_output=True, text=True, timeout=60)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("--game-dir", result.stdout)


class DrawnTest(unittest.TestCase):
    def test_the_icon_has_every_size(self):
        data = desktop.ICON.read_bytes()
        count = struct.unpack("<HHH", data[:6])[2]
        self.assertEqual([data[6 + 16 * i] or 256 for i in range(count)], [16, 20, 24, 32, 40, 48, 64, 128, 256])

    def test_the_typefaces_and_their_licence_are_there(self):
        self.assertTrue(list(fonts.FOLDER.glob("*.ttf")))
        self.assertIn("SIL Open Font License", (fonts.FOLDER / "OFL.txt").read_text(encoding="utf-8"))

    def pixels(self, data, w):
        body = b"".join(data[8:].split(b"IDAT")[1:2])
        raw = zlib.decompressobj().decompress(body)
        return [raw[y * (w * 4 + 1) + 1:(y + 1) * (w * 4 + 1)] for y in range(len(raw) // (w * 4 + 1))]

    def test_a_leaning_bar_leans_and_is_one_colour(self):
        rows = self.pixels(paint._leaning(60, 20, 10, "#112233", 0, None), 60)
        first = [next(x for x in range(60) if row[x * 4 + 3] > 127) for row in rows]
        self.assertGreater(first[0], first[-1])
        self.assertEqual(rows[10][30 * 4:30 * 4 + 4], bytes((0x11, 0x22, 0x33, 255)))

    def test_a_slab_is_at_the_left_only(self):
        row = self.pixels(paint._leaning(60, 20, 0, "#000000", 8, "#ffffff"), 60)[10]
        self.assertEqual((row[4 * 4], row[40 * 4]), (255, 0))


if __name__ == "__main__":
    unittest.main()
