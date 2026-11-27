# Orbitals PC Recomp, a work based on SwitchRecomp by MZ Labs. GNU AGPL v3.0 with the additional terms of NOTICE.txt (LICENSE.txt).
"""The launcher's typefaces, Barlow and Barlow Condensed (SIL Open Font License, launcher/assets/fonts/OFL.txt), for this process only:
nothing is installed on the system. Before the first window is made."""
import ctypes
import ctypes.util
import os
from pathlib import Path

FOLDER = Path(__file__).with_name("assets") / "fonts"


def load():
    for path in sorted(FOLDER.glob("*.ttf")):
        try:
            if os.name == "nt":
                ctypes.windll.gdi32.AddFontResourceExW(str(path), 0x10, None)   # FR_PRIVATE
            else:
                library = ctypes.CDLL(ctypes.util.find_library("fontconfig") or "libfontconfig.so.1")
                library.FcConfigAppFontAddFile.argtypes = (ctypes.c_void_p, ctypes.c_char_p)
                library.FcConfigAppFontAddFile(None, os.fsencode(path))
        except (OSError, AttributeError):   # the system's own type then
            return
