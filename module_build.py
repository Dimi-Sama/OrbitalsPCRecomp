# Orbitals PC Recomp, based on SwitchRecomp by MZ Labs. AGPL-3.0 with NOTICE.txt terms.
"""Identity shared by the compiler, the runtime packager and the launcher."""

import ast
import hashlib
import json
import mmap
import os
import re
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent
RUNTIME_MARKER = "Orbitals runtime contract v1:"
MODULE_MARKER = "Orbitals module contract v1:"
FINGERPRINT_MARKER = "Orbitals code fingerprint v1:"
CONTRACT_FILES = ("a64.py", "codegen.py", "nxloader.py", "runtime/cpu.h",
                  "runtime/cpu_helpers.c", "runtime/module_abi.h",
                  "runtime/orbitals_buttons.c", "runtime/orbitals_buttons_internal.h", "runtime/orbitals_input.c")
RUNTIME_INTERFACE = {"runtime/main.c": 2, "runtime/orbitals_settings.c": 2}


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def file_hash(path):
    with open(path, "rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def source_bytes(name):
    return (ROOT / name).read_bytes()


def source_hash(names, read=source_bytes):
    # Archives and a CRLF checkout describe the same source.
    return digest({name: hashlib.sha256(read(name).replace(b"\r\n", b"\n")).hexdigest() for name in names})


def functions_hash(names, read=source_bytes):
    source = read("switchrecomp.py").decode("utf-8").splitlines()
    tree = ast.parse("\n".join(source))
    return digest({node.name: source[node.lineno - 1:node.end_lineno] for node in tree.body
                   if isinstance(node, ast.FunctionDef) and node.name in names})


def runtime_contract(read=source_bytes):
    interfaces = {}
    for name, count in RUNTIME_INTERFACE.items():
        blocks = re.findall(r"/\* SWR_MODULE_INTERFACE_BEGIN \*/(.*?)/\* SWR_MODULE_INTERFACE_END \*/",
                            read(name).decode("utf-8").replace("\r\n", "\n"), re.S)
        if len(blocks) != count:
            raise ValueError(f"Missing module interface block in {name}")
        interfaces[name] = blocks
    return digest([source_hash(CONTRACT_FILES, read), functions_hash({"gen_module"}, read), interfaces])


def marker_value(binary, marker):
    try:
        with Path(binary).open("rb") as stream, mmap.mmap(stream.fileno(), 0, access=mmap.ACCESS_READ) as data:
            match = re.search(re.escape(marker.encode()) + rb"([0-9a-f]{64})\x00", data)
            return match[1].decode() if match else None
    except (OSError, ValueError):
        return None


def game_inputs(exefs, romfs):
    from nxloader import MODULE_ORDER

    modules = {}
    for name in MODULE_ORDER:
        path = exefs / name
        if path.is_file():
            with path.open("rb") as stream:
                header = stream.read(0x60)
                stream.seek(0)
                modules[name] = [header[0x40:0x60].hex(), hashlib.file_digest(stream, "sha256").hexdigest()]
    npdm = exefs / "main.npdm"
    deferred = {}
    if romfs and romfs.is_dir():
        for folder, _, names in os.walk(romfs):
            for name in names:
                if name.lower().endswith(".nro"):
                    path = Path(folder) / name
                    with path.open("rb") as stream:
                        if stream.read(0x14)[0x10:] == b"NRO0":
                            stream.seek(0)
                            deferred[path.relative_to(romfs).as_posix()] = hashlib.file_digest(stream, "sha256").hexdigest()
    return {"modules": modules, "npdm": file_hash(npdm) if npdm.is_file() else None, "deferred": deferred}


def manifest_path(module):
    return Path(module).with_suffix(".build.json")


def write_json(path, value):
    path = Path(path)
    with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as stream:
        temporary = Path(stream.name)
        try:
            stream.write((json.dumps(value, sort_keys=True, indent=2) + "\n").encode())
            stream.flush()
            os.fsync(stream.fileno())
            stream.close()
            temporary.replace(path)
        finally:
            temporary.unlink(missing_ok=True)


def read_manifest(module):
    try:
        data = json.loads(manifest_path(module).read_text(encoding="utf-8"))
        if (data["schema"] == 1 and isinstance(data["inputs"], dict)
                and data["fingerprint"] == digest(data["inputs"])):
            return data
    except (OSError, ValueError, TypeError, KeyError):
        pass
    return None


def verified_module(module, manifest, contract):
    try:
        return (manifest is not None and manifest["inputs"].get("contract") == contract
                and marker_value(module, MODULE_MARKER) == contract
                and marker_value(module, FINGERPRINT_MARKER) == manifest["fingerprint"]
                and file_hash(module) == manifest.get("module_sha256"))
    except OSError:
        return False


def manifest_ids(manifest):
    try:
        return {name: data[0] for name, data in manifest["inputs"]["game"]["modules"].items()}
    except (AttributeError, IndexError, KeyError, TypeError):
        return {}
