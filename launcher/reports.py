# SwitchRecomp - Copyright 2026 MZ Labs

"""Build bounded, previewable diagnostics entirely on the local machine."""

import ctypes
import hashlib
import ipaddress
import os
import platform
import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

from . import VERSION
from .core import (LOG, SAVE_NAMES, WINDOWS, LauncherError, atomic_output, json_bytes, read_local,
                   runtime_info, save_files, timestamp, write_text)

ISSUE_TYPES = ("Crash", "Graphics / Vulkan", "Audio", "Performance", "Controller",
               "Netplay", "Installation", "Save / progress", "Other")
REPORT_LIMIT = 24_000_000
LOG_LIMIT = 1_048_576


def scrub(value, paths=()):
    roots = {str(Path.home()), os.environ.get("USERPROFILE", ""), *map(str, paths)}
    try:   # the folder the game and the profiles share (e.g. an SD card's mount point on Linux, outside the home folder)
        common = Path(os.path.commonpath([str(p) for p in paths])) if len(paths) > 1 else None
        if common and len(common.parts) > 2:
            roots.add(str(common))
    except ValueError:   # different drives
        pass
    roots |= {root.replace("\\", "/") for root in roots}
    for root in sorted(filter(None, roots), key=len, reverse=True):
        value = re.sub(re.escape(root), "<local folder>", value, flags=re.IGNORECASE if WINDOWS else 0)
    value = re.sub(r"(?i)(?:[a-z]:[\\/](?:users|documents and settings)[\\/]|/(?:home|Users)/)[^\\/\r\n]+",
                   "<user folder>", value)
    value = re.sub(r"(?im)^(?:.*(?:-----BEGIN [A-Z ]*PRIVATE KEY-----).*(?:\r?\n|$))"
                   r"[\s\S]*?-----END [A-Z ]*PRIVATE KEY-----", "<private key hidden>", value)
    value = re.sub(r"(?im)^([^\r\n]{0,110}\b(?:authorization|cookie|set-cookie|password|passwd|"
                   r"secret|token|api[_-]?key|account[_-]?id|prod\.keys)\s*[=:]).*$",
                   r"\1 <hidden>", value)
    value = re.sub(r"(?i)(?:gh[pousr]_[a-z0-9_]{10,}|github_pat_[a-z0-9_]{10,}|"
                   r"Bearer\s+[a-z0-9._~+/=-]{8,}|https?://[^/\s:@]+:[^/\s@]+@)", "<identifier hidden>", value)
    value = re.sub(r"(?i)\b(?:token|password|secret|api[_-]?key|account[_-]?id)=[^\s&;]+",
                   "<identifier hidden>", value)
    value = re.sub(r"\b[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}\b", "<e-mail hidden>", value)
    def hide_ip(match):
        try:
            address = ipaddress.ip_address(match[0])
        except ValueError:
            return match[0]
        return "<IP address hidden>" if address.is_global else match[0]

    return re.sub(r"(?<![\w:.])(?:\d{1,3}(?:\.\d{1,3}){3}|"
                  r"[0-9a-fA-F:]*:[0-9a-fA-F:]*:[0-9a-fA-F:]*)(?![\w:.])", hide_ip, value)


def system_info():
    info = {"os": platform.system(), "os_release": platform.release(),
            "os_version": platform.version(), "architecture": platform.machine()}
    if WINDOWS:
        import winreg

        class MemoryStatus(ctypes.Structure):
            _fields_ = [("length", ctypes.c_uint32), ("load", ctypes.c_uint32)] + [
                (name, ctypes.c_uint64) for name in
                ("total", "available", "page_total", "page_available", "virtual_total",
                 "virtual_available", "extended")]

        memory = MemoryStatus()
        memory.length = ctypes.sizeof(memory)
        if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(memory)):
            info["memory_bytes"] = memory.total
        try:
            key = r"HARDWARE\DESCRIPTION\System\CentralProcessor\0"
            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, key) as cpu:
                info["cpu"] = winreg.QueryValueEx(cpu, "ProcessorNameString")[0].strip()
        except OSError:
            pass
    else:
        try:
            info["memory_bytes"] = os.sysconf("SC_PHYS_PAGES") * os.sysconf("SC_PAGE_SIZE")
            with Path("/proc/cpuinfo").open(encoding="utf-8") as cpu:
                for line in cpu:
                    if line.startswith("model name") and ":" in line:
                        info["cpu"] = line.partition(":")[2].strip()
                        break
        except (OSError, ValueError):
            pass
    return info


def gpu_info():
    command = shutil.which("vulkaninfo")
    if not command:
        return {}
    try:
        probe = subprocess.run([command, "--summary"], timeout=8, check=True,
                               stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                               creationflags=subprocess.CREATE_NO_WINDOW if WINDOWS else 0)
    except (OSError, subprocess.SubprocessError):
        return {}
    summary = probe.stdout.decode("utf-8", errors="replace")
    instance = re.search(r"Vulkan Instance Version:\s*([\d.]+)", summary)
    result = {"devices": []}
    if instance:
        result["vulkan_instance"] = instance[1]
    for section in re.split(r"(?m)^\s*GPU\d+:\s*$", summary)[1:]:
        device = dict(re.findall(r"(?m)^[ \t]*(deviceName|driverName|driverInfo|driverVersion|apiVersion)"
                                 r"[ \t]*=[ \t]*([^\r\n]+)", section))
        if device.get("deviceName"):
            result["devices"].append(device)
    return result if instance or result["devices"] else {}


def read_log(root, name, paths):
    with read_local(root, Path(name)) as stream:
        size = os.fstat(stream.fileno()).st_size
        if size > LOG_LIMIT:
            early = stream.read(65_536)
            stream.seek(-LOG_LIMIT + 65_536, os.SEEK_END)
            contents = early + b"\n--- middle omitted: size limit ---\n" + stream.read(LOG_LIMIT - 65_536)
        else:
            contents = stream.read(LOG_LIMIT)
    if b"\0" in contents:
        raise LauncherError("The log is binary.")
    return scrub(contents.decode("utf-8", errors="replace"), paths).encode("utf-8")


@dataclass(frozen=True)
class Report:
    files: dict[str, bytes]
    missing: dict[str, str]

    @property
    def issue(self):
        return self.files["issue.md"].decode("utf-8")

    def write(self, parent):
        if sum(map(len, self.files.values())) > REPORT_LIMIT:
            raise LauncherError("The report is larger than 24 MB. Remove an attachment and try again.")
        directory = parent / ("Orbitals-BugReport-" + timestamp())
        directory.mkdir(parents=True)
        archive = directory / (directory.name + ".zip")
        with atomic_output(archive) as output:
            with ZipFile(output, "w", compression=ZIP_DEFLATED, compresslevel=5) as bundle:
                for path, content in self.files.items():
                    bundle.writestr(path, content)
            if output.stat().st_size > REPORT_LIMIT:
                raise LauncherError("The archive is larger than 24 MB.")
            with ZipFile(output) as bundle:
                if bundle.testzip() is not None:
                    raise LauncherError("The ZIP integrity check failed.")
        write_text(directory / "issue.md", self.issue)
        LOG.info("event=report_created files=%s bytes=%s", len(self.files), archive.stat().st_size)
        return archive


def create_report(fields, include, profiles, game=None, run=None, *, selected_saves=()):
    files, missing = {}, {}
    paths = [profiles.root]
    if game:
        paths.append(game.root)
        paths.extend((game.exefs, game.romfs))
    runtime = runtime_info((run, game.root if game else None)) if include.get("version") else {}
    system = system_info() if include.get("hardware") else {}
    gpu = gpu_info() if include.get("hardware") else {}

    if include.get("hardware"):
        files["system/system_info.json"] = json_bytes(system)
        if gpu:
            files["system/gpu_info.json"] = json_bytes(gpu)
        else:
            missing["system/gpu_info.json"] = "vulkaninfo missing or no result"
    if include.get("version"):
        build = {"launcher_version": VERSION, **runtime}
        if game:
            build["exefs_main_build_id"] = game.ids["main"]
            if game.version:
                build["game_version"] = game.version
        if not runtime:
            missing["recomp_version"] = "No runtime log header"
        if not game or not game.version:
            missing["game_version"] = "control.nacp metadata unavailable"
        files["system/build_info.json"] = json_bytes(build)
    if include.get("settings"):
        source = profiles.settings
        files["config/settings.json"] = json_bytes({
            key: source.get(key) for key in ("gfx_preset", "mode", "display", "size", "upscale", "vsync", "volume", "keyboard", "fps")
        })
    log_root = run or (game.root if game else None)
    if include.get("game_logs"):
        for name in ("Orbitals.log", "console.log", "threads.txt", "crash.log", "exit.json"):
            path = "logs/" + name
            try:
                if log_root is None:
                    raise FileNotFoundError
                files[path] = read_log(log_root, name, paths)
            except (OSError, LauncherError):
                missing[path] = "Missing or unreadable"
    if include.get("launcher_logs"):
        for name in ("launcher.log", "launcher.log.1"):
            try:
                files["logs/" + name] = read_log(profiles.root / "logs", name, paths)
            except (OSError, LauncherError):
                missing["logs/" + name] = "Missing or unreadable"
    if include.get("saves"):
        available = report_saves(profiles.saves)
        if not selected_saves:
            missing["saves/"] = "No save selected"
        for name in selected_saves:
            if name not in available:
                raise LauncherError("The selection of saves changed. Refresh the preview.")
            with read_local(profiles.saves, name) as input_file:
                data = input_file.read(REPORT_LIMIT + 1)
            if not data.startswith(b"GVAS") or len(data) != available[name]:
                raise LauncherError("A file changed while the report was prepared.")
            files["saves/" + name.as_posix()] = data

    category = fields.get("type") if fields.get("type") in ISSUE_TYPES else "Other"
    title = scrub(" ".join(fields.get("title", "").split())[:140], paths) or "Orbitals problem"
    issue = [f"# [{category}] {title}"]
    for field, label in (("description", "Description"), ("steps", "Steps to reproduce"),
                         ("expected", "Expected behaviour"), ("actual", "Observed behaviour")):
        issue.extend((f"## {label}", scrub(fields.get(field, "").strip()[:8000], paths) or "To be filled in."))
    details = {}
    if system:
        details["OS"] = " ".join(system[key] for key in ("os", "os_release", "architecture"))
    if gpu.get("devices"):
        details["GPUs"] = ", ".join(device["deviceName"] for device in gpu["devices"])
        drivers = [device.get("driverInfo") or device.get("driverVersion") for device in gpu["devices"]]
        if any(drivers):
            details["Drivers"] = ", ".join(filter(None, drivers))
    if gpu.get("vulkan_instance"):
        details["Vulkan"] = gpu["vulkan_instance"]
    if runtime:
        details["Recomp version"] = " ".join(filter(None, (runtime.get("release"), runtime.get("commit")))) or runtime["recomp_version"]
        if runtime.get("vulkan_device"):
            details["Vulkan device"] = runtime["vulkan_device"]
    if include.get("settings"):
        chosen = profiles.settings
        details["Settings"] = ", ".join(f"{key}={chosen.get(key)}" for key in ("gfx_preset", "mode", "fps", "size", "display", "vsync"))
    if include.get("version") and game and game.version:
        details["Game version"] = game.version
    if details:
        issue.extend(("## System", "\n".join(f"- **{key}** · {value}" for key, value in details.items())))
    issue.extend(("## Attachments", "Attach the diagnostic ZIP after checking its contents."))
    files["issue.md"] = ("\n\n".join(issue) + "\n").encode("utf-8")
    files["README.txt"] = (
        "Orbitals PC Recomp local report\n\n"
        "Check every file before attaching this ZIP to a public issue.\n"
        "The text to paste is in issue.md. The list of files and the information "
        "that was unavailable are in manifest.json. Selected saves are binary copies.\n"
        + ("Recomp version: " + runtime["recomp_version"] + "\n" if runtime else "")
    ).encode("utf-8")
    files["manifest.json"] = json_bytes({
        "schema": 1, "missing": missing,
        "files": [{"path": path, "bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()}
                  for path, data in sorted(files.items())],
    })
    if sum(map(len, files.values())) > REPORT_LIMIT:
        raise LauncherError("The report is larger than 24 MB. Remove an attachment and try again.")
    return Report(files, missing)


def report_saves(root):
    available = {}
    for path, size in save_files(root).items():
        if len(path.parts) != 2 or path.name not in SAVE_NAMES or size > REPORT_LIMIT:
            continue
        with read_local(root, path) as stream:
            if stream.read(4) == b"GVAS":
                available[path] = size
    return available
