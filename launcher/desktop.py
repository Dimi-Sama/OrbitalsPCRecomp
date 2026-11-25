# Orbitals PC Recomp, a work based on SwitchRecomp by MZ Labs. GNU AGPL v3.0 with the additional terms of NOTICE.txt (LICENSE.txt).
"""The launcher as an application of the desktop: its own identity in the Windows taskbar (which shows Python's icon for a program that
has none), a title bar in its colours, and a shortcut with its icon (the desktop on Windows, the application menu on Linux)."""
import ctypes
import os
import sys
from pathlib import Path

from .core import LOG, REPO, WINDOWS, LauncherError

APP_ID = "Liftoff.OrbitalsPCRecomp"
NAME = "Orbitals PC Recomp"
ICON = Path(__file__).with_name("assets") / "orbitals.ico"
START = REPO / "Orbitals-Launcher.pyw"


class Guid(ctypes.Structure):
    _fields_ = [("a", ctypes.c_uint32), ("b", ctypes.c_uint16), ("c", ctypes.c_uint16), ("d", ctypes.c_ubyte * 8)]

    @classmethod
    def of(cls, text):
        raw = bytes.fromhex(text.replace("-", ""))
        return cls(int.from_bytes(raw[:4], "big"), int.from_bytes(raw[4:6], "big"), int.from_bytes(raw[6:8], "big"),
                   (ctypes.c_ubyte * 8)(*raw[8:]))


class PropertyKey(ctypes.Structure):
    _fields_ = [("group", Guid), ("number", ctypes.c_uint32)]


class PropertyText(ctypes.Structure):   # a PROPVARIANT that holds a text
    _fields_ = [("kind", ctypes.c_uint16), ("_a", ctypes.c_uint16), ("_b", ctypes.c_uint16), ("_c", ctypes.c_uint16),
                ("text", ctypes.c_wchar_p), ("_d", ctypes.c_void_p)]


APP_MODEL = "9F4C2855-9F79-4B39-A8D0-E1D42DE1D5F3"   # the properties' group: 2 command, 3 icon, 4 name, 5 the application's id
PROPERTY_STORE = "886D8EEB-8CF2-4446-8D02-CDBA1DBDCF99"
SHELL_LINK, SHELL_LINK_W = "00021401-0000-0000-C000-000000000046", "000214F9-0000-0000-C000-000000000046"
PERSIST_FILE = "0000010B-0000-0000-C000-000000000046"
DESKTOP_FOLDER = "B4BFCC3A-DB2C-424C-B029-7FE99A87C641"


class Com:
    """A COM object: its functions by their place in its table."""

    def __init__(self, pointer):
        self.pointer = pointer

    def call(self, place, *arguments):
        table = ctypes.cast(self.pointer, ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p)))[0]
        kinds = [type(a) if isinstance(a, (ctypes._SimpleCData, ctypes._Pointer)) else ctypes.c_wchar_p if isinstance(a, str) else
                 ctypes.c_int if isinstance(a, int) else ctypes.c_void_p for a in arguments]
        result = ctypes.WINFUNCTYPE(ctypes.c_long, ctypes.c_void_p, *kinds)(table[place])(self.pointer, *arguments)
        if result < 0:
            raise OSError(f"Windows answered {result & 0xffffffff:#x}")

    def ask(self, interface):
        other = ctypes.c_void_p()
        self.call(0, ctypes.byref(Guid.of(interface)), ctypes.byref(other))
        return Com(other)

    def put(self, number, text):
        """A property of the application model, on a property store."""
        self.call(6, ctypes.byref(PropertyKey(Guid.of(APP_MODEL), number)), ctypes.byref(PropertyText(31, 0, 0, 0, text, None)))   # VT_LPWSTR

    def release(self):
        table = ctypes.cast(self.pointer, ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p)))[0]
        ctypes.WINFUNCTYPE(ctypes.c_ulong, ctypes.c_void_p)(table[2])(self.pointer)


def python():
    """The Python without a console that runs this launcher."""
    windowed = Path(sys.executable).with_name("pythonw.exe")
    return windowed if windowed.is_file() else Path(sys.executable)


def identity():
    """Windows: an application of its own in the taskbar, not a window of Python's (before any window is made)."""
    if WINDOWS:
        try:
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(APP_ID)
        except (OSError, AttributeError):
            pass


def dress(root, ground, ink):
    """The window itself: its icon, a title bar in the launcher's colours, and what a pin on the taskbar starts."""
    if not WINDOWS:
        return
    root.iconbitmap(default=str(ICON))
    window = int(root.wm_frame(), 16)
    colour = lambda c: int(c[5:7] + c[3:5] + c[1:3], 16)   # 0x00BBGGRR
    for attribute, value in ((20, 1), (35, colour(ground)), (36, colour(ink))):   # dark mode; Windows 11: the caption, its text
        try:
            ctypes.windll.dwmapi.DwmSetWindowAttribute(ctypes.c_void_p(window), attribute, ctypes.byref(ctypes.c_int(value)), 4)
        except (OSError, AttributeError):
            pass
    try:
        pointer = ctypes.c_void_p()
        if ctypes.windll.shell32.SHGetPropertyStoreForWindow(ctypes.c_void_p(window), ctypes.byref(Guid.of(PROPERTY_STORE)),
                                                             ctypes.byref(pointer)) >= 0:
            store = Com(pointer)
            for number, text in ((5, APP_ID), (2, f'"{python()}" -B "{START}"'), (4, NAME), (3, f"{ICON},0")):
                store.put(number, text)
            store.call(7)   # Commit
            store.release()
    except (OSError, AttributeError) as error:
        LOG.warning("event=taskbar_identity_failed type=%s", type(error).__name__)


def desktop_folder():
    path = ctypes.c_wchar_p()
    shell = ctypes.windll.shell32
    if shell.SHGetKnownFolderPath(ctypes.byref(Guid.of(DESKTOP_FOLDER)), 0, None, ctypes.byref(path)) != 0 or not path.value:
        raise LauncherError("The desktop's folder was not found.")
    folder = Path(path.value)
    ctypes.windll.ole32.CoTaskMemFree(path)
    return folder


def write_link(path):
    """A Windows shortcut to the launcher, with its icon and its identity (pinning it and the window are then the same)."""
    ole = ctypes.windll.ole32
    ole.CoInitializeEx(None, 2)
    try:
        pointer = ctypes.c_void_p()
        if ole.CoCreateInstance(ctypes.byref(Guid.of(SHELL_LINK)), None, 1, ctypes.byref(Guid.of(SHELL_LINK_W)), ctypes.byref(pointer)) < 0:
            raise OSError("Windows could not make a shortcut")
        link = Com(pointer)
        link.call(20, str(python()))                # SetPath
        link.call(11, f'-B "{START}"')              # SetArguments
        link.call(9, str(REPO))                     # SetWorkingDirectory
        link.call(7, "Orbitals on PC, from your own copy")   # SetDescription
        link.call(17, str(ICON), 0)                 # SetIconLocation
        store = link.ask(PROPERTY_STORE)
        store.put(5, APP_ID)
        store.call(7)
        store.release()
        file = link.ask(PERSIST_FILE)
        file.call(6, str(path), 1)                  # Save
        file.release()
        link.release()
    finally:
        ole.CoUninitialize()


def write_entry(path):
    """A Linux application menu entry (the one Orbitals-Launcher.sh --menu writes)."""
    start = os.environ.get("APPIMAGE") or str(REPO / "Orbitals-Launcher.sh")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"""[Desktop Entry]
Type=Application
Name={NAME}
Comment=Launcher: install from your own game files, graphics settings, bug reports
Exec="{start}"
Path={REPO}
Icon={ICON.with_name("orbitals-icon.png")}
Terminal=false
StartupWMClass=OrbitalsPCRecomp
Categories=Game;
""", encoding="utf-8")
    path.chmod(0o755)


def add_shortcut():
    """Returns what to tell the player."""
    if WINDOWS:
        path = desktop_folder() / f"{NAME}.lnk"
        write_link(path)
        said = "The shortcut is on your desktop."
    else:
        path = Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local/share") / "applications" / "orbitals-pc-recomp.desktop"
        write_entry(path)
        said = "Orbitals PC Recomp is in your application menu."
    LOG.info("event=shortcut_added")
    return said
