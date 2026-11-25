# Orbitals PC Recomp, a work based on SwitchRecomp by MZ Labs. GNU AGPL v3.0 with the additional terms of NOTICE.txt (LICENSE.txt).
# The shortcuts.vdf reading and writing and the rule for the library images are from mkw-recomp's tools/prepare/steam.py
# (https://github.com/adriadam10/mkw-recomp), MIT License, Copyright (c) 2026 Adrià: launcher/LICENSE_mkw-recomp.txt.
"""Add the launcher to Steam as a non-Steam game, for Big Picture and the Steam Deck: an entry in every Steam user's
config/shortcuts.vdf (Steam's binary key-value format), the one Steam's own "Add a Non-Steam Game" writes. An entry added before is
replaced, not doubled; the others are kept as they are. Steam reads the file when it starts.

The format, from Steam's files themselves: a map is 0x00 <name> NUL <entries> 0x08, a string 0x01 <name> NUL <value> NUL, a 32-bit
integer 0x02 <name> NUL <4 bytes LE>, a 64-bit one 0x07 <name> NUL <8 bytes LE>. The appid Steam derives for a shortcut is
crc32(exe + name) with the top bit set.

Steam's library shows a non-Steam game by its images in config/grid/: <appid>p.png, <appid>.png and <appid>_hero.png, here cut from
the launcher's own illustration (no art of the game). An image the player set stays: only one this launcher wrote, by its SHA-256 in
<appid>_orbitals-recomp.txt, is replaced."""

import hashlib
import os
import shutil
import struct
import sys
import tkinter as tk
import zlib
from pathlib import Path

from .core import LOG, REPO, WINDOWS, LauncherError

NAME = "Orbitals PC Recomp"
RECORD = "_orbitals-recomp.txt"


def steam_dir():
    if WINDOWS:
        import winreg
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Valve\Steam") as key:
                return Path(winreg.QueryValueEx(key, "SteamPath")[0])
        except OSError:
            return None
    home = Path.home()
    for folder in (home / ".steam/steam", home / ".local/share/Steam", home / ".var/app/com.valvesoftware.Steam/.local/share/Steam"):
        if (folder / "userdata").is_dir():
            return folder
    return None


def steam_running(steam):
    if WINDOWS:
        import winreg
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Valve\Steam\ActiveProcess") as key:
                return bool(winreg.QueryValueEx(key, "pid")[0])
        except OSError:
            return False
    pid = steam.parent / "steam.pid" if steam.name == "steam" else Path.home() / ".steam/steam.pid"
    try:
        os.kill(int(pid.read_text().strip()), 0)
        return True
    except (OSError, ValueError):
        return False


def read_map(data, i):
    out = {}
    while data[i] != 0x08:
        kind, i = data[i], i + 1
        end = data.index(0, i)
        key, i = data[i:end].decode("utf-8", "surrogateescape"), end + 1
        if kind == 0x00:
            out[key], i = read_map(data, i)
        elif kind == 0x01:
            end = data.index(0, i)
            out[key], i = data[i:end].decode("utf-8", "surrogateescape"), end + 1
        elif kind == 0x02:
            out[key], i = struct.unpack_from("<i", data, i)[0], i + 4
        elif kind == 0x07:
            out[key], i = ("u64", struct.unpack_from("<Q", data, i)[0]), i + 8
        else:
            raise ValueError(f"unknown type {kind} at {i}")
    return out, i + 1


def write_map(values):
    out = bytearray()
    for key, value in values.items():
        name = key.encode("utf-8", "surrogateescape") + b"\0"
        if isinstance(value, dict):
            out += b"\x00" + name + write_map(value)
        elif isinstance(value, tuple):
            out += b"\x07" + name + struct.pack("<Q", value[1])
        elif isinstance(value, int):
            out += b"\x02" + name + struct.pack("<i", value)
        else:
            out += b"\x01" + name + str(value).encode("utf-8", "surrogateescape") + b"\0"
    return bytes(out + b"\x08")


def target():
    """(program, its arguments, its folder) that starts this launcher, for Steam to follow until the window closes."""
    if os.environ.get("APPIMAGE"):
        return os.environ["APPIMAGE"], "", str(Path(os.environ["APPIMAGE"]).parent)
    if not WINDOWS:
        return str(REPO / "Orbitals-Launcher.sh"), "", str(REPO)
    windowed = Path(sys.executable).with_name("pythonw.exe")   # (the .bat file ends at once: Steam would take the game for closed)
    return str(windowed if windowed.is_file() else sys.executable), "-B -m launcher", str(REPO)


def app_id(exe, name=NAME):
    return zlib.crc32((f'"{exe}"' + name).encode("utf-8", "surrogateescape")) | 0x80000000


def draw_images(master, folder):
    """Steam's library images, cut from the launcher's illustration (Tk thread). Returns {suffix after the appid: file}."""
    art = tk.PhotoImage(master=master, file=str(Path(__file__).with_name("assets") / "orbital-halo.png"))
    folder.mkdir(parents=True, exist_ok=True)
    images = {}
    for suffix, (w, h), zoom, less, (x, y) in (("p.png", (600, 900), 2, 1, (1500, 10)), (".png", (920, 430), 1, 1, (360, 20)),
                                               ("_hero.png", (1920, 620), 3, 2, (0, 35))):
        scaled = art.zoom(zoom) if zoom > 1 else art
        if less > 1:
            scaled = scaled.subsample(less)
        image = tk.PhotoImage(master=master, width=w, height=h)
        image.tk.call(image, "copy", scaled, "-from", x, y, x + w, y + h, "-to", 0, 0)
        images[suffix] = folder / ("steam" + suffix)
        image.write(str(images[suffix]), format="png")
    return images


def write_new(path, data):
    part = path.with_name(path.name + ".part")
    part.write_bytes(data)
    part.replace(path)


def put_images(grid, appid, images):
    grid.mkdir(parents=True, exist_ok=True)
    record = grid / f"{appid}{RECORD}"
    ours = dict(line.split(" ", 1)[::-1] for line in record.read_text().splitlines() if " " in line) if record.is_file() else {}
    for suffix, source in images.items():
        image = grid / f"{appid}{suffix}"
        if image.exists() and hashlib.sha256(image.read_bytes()).hexdigest() != ours.get(image.name):
            continue   # the player's own
        data = source.read_bytes()
        write_new(image, data)
        ours[image.name] = hashlib.sha256(data).hexdigest()
    record.write_text("".join(f"{digest} {name}\n" for name, digest in sorted(ours.items())))


def add_entry(vdf, exe, arguments, folder, icon):
    """Our entry in a shortcuts.vdf. The file is replaced whole, and a copy of the one before is kept beside it."""
    try:
        root = read_map(vdf.read_bytes(), 0)[0] if vdf.is_file() and vdf.stat().st_size else {}
    except (IndexError, ValueError, struct.error) as error:
        raise ValueError(f"{vdf.name} cannot be read: it was left as it is") from error
    key = next((name for name in root if name.lower() == "shortcuts"), "shortcuts")
    rows = list(root.get(key, {}).values())
    grid = vdf.parent / "grid"

    def ours(row):
        """Added by this launcher: the same program and arguments, or our name with the record of our images beside it."""
        same = (row.get("Exe", row.get("exe")), row.get("LaunchOptions", "")) == (f'"{exe}"', arguments)
        named = row.get("AppName", row.get("appname")) == NAME
        uid = row["appid"] & 0xffffffff if isinstance(row.get("appid"), int) else 0
        return named and (same or (grid / f"{uid}{RECORD}").is_file())

    rows = [row for row in rows if not ours(row)]
    appid = app_id(exe)
    rows.append({"appid": struct.unpack("<i", struct.pack("<I", appid))[0], "AppName": NAME, "Exe": f'"{exe}"', "StartDir": f'"{folder}"',
                 "icon": str(icon), "ShortcutPath": "", "LaunchOptions": arguments, "IsHidden": 0, "AllowDesktopConfig": 1, "AllowOverlay": 1,
                 "OpenVR": 0, "Devkit": 0, "DevkitGameID": "", "DevkitOverrideAppID": 0, "LastPlayTime": 0, "FlatpakAppID": "", "tags": {}})
    if vdf.is_file():
        shutil.copy2(vdf, vdf.with_name("shortcuts.vdf.before-orbitals"))
    root[key] = {str(i): row for i, row in enumerate(rows)}
    write_new(vdf, write_map(root))   # never a half-written file Steam would drop every shortcut from


def add(images, steam=None):
    """Add the launcher for every Steam user of this PC. Returns what to tell the player."""
    steam = steam or steam_dir()
    users = []
    if steam is not None and (steam / "userdata").is_dir():
        users = [user for user in (steam / "userdata").iterdir() if user.name.isdigit() and user.name != "0" and user.is_dir()]
    if not users:
        raise LauncherError("Steam was not found on this PC, or no one has signed in to it yet.")
    exe, arguments, folder = target()
    icon = Path(__file__).with_name("assets") / "orbitals-icon.png"
    done, problem = 0, None
    for user in users:
        try:
            (user / "config").mkdir(exist_ok=True)
            add_entry(user / "config" / "shortcuts.vdf", exe, arguments, folder, icon)
            put_images(user / "config" / "grid", app_id(exe), images)
            done += 1
        except (OSError, ValueError) as error:
            problem = problem or error
            LOG.error("event=steam_add_failed type=%s", type(error).__name__)
    if not done:
        raise LauncherError(f"Steam's shortcuts could not be changed: {problem}")
    LOG.info("event=steam_added users=%s of=%s", done, len(users))
    said = "Added to Steam." if done == len(users) else f"Added to Steam for {done} of its {len(users)} users."
    return said + (" Restart Steam to see it." if steam_running(steam) else "")
