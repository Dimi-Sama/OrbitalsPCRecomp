"""Build the Orbitals Linux ELF files (runtime and game module) on Windows with zig cc, for SteamOS / the Steam Deck.

    python tools/steamdeck/cross/build.py runtime [--jobs N] [--out DIR]
    python tools/steamdeck/cross/build.py code    [--jobs N] [--out DIR] [--generated DIR]

The runtime is linked as a position independent executable. A fixed-address executable (zig's default) is loaded at
0x1000000, and Linux puts the brk heap up to 1 GB after it, i.e. inside the game's 0x8000000-0x2000000000 range, which
renderer=vulkan maps at the same addresses on the host: the start then fails with "Could not reserve the game's addresses".
A PIE is loaded near 0x55xxxxxxxxxx and its heap follows it, far above the game's 128 GB.

Inputs (downloaded, not in git; BUILDING.md):
  ORBITALS_LINUX_CROSS  zig-x86_64-windows-0.15.2/ and sysroot/   default: tools/linux-cross (python tools/linux-cross/fetch_zig.py,
                        prepare-linux-sysroot.py, prepare-opus.py), else <worktrees>/Orbitals-Dev/build/linux-cross
  ORBITALS_TOOLCHAIN    vulkan-bin/ (glslang) and external/   default: external/orbitals-toolchain (tools/release/get_orbitals_deps.py),
                        else <worktrees>/Switch2RECOMP/build/orbitals-debug/toolchain
  runtime/opus/lin/libopus.a   copied from the cross folder's sysroot when missing
  --generated           the C of a code generation (switchrecomp.py <game> --no-build ... : <outdir>/Orbitals_build)
"""
import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

cli = argparse.ArgumentParser()
cli.add_argument("what", choices=("runtime", "code"))
cli.add_argument("--jobs", type=int, default=max(2, (os.cpu_count() or 4) - 4))
cli.add_argument("--out")
cli.add_argument("--generated")
settings = cli.parse_args()

project = Path(__file__).resolve().parents[3]
worktrees = project.parent


def first_existing(*paths):
    for p in paths:
        if p.exists(): return p
    return paths[0]


# In the repository first (tools/linux-cross: fetch_zig.py, prepare-linux-sysroot.py, prepare-opus.py; external/orbitals-toolchain:
# tools/release/get_orbitals_deps.py), then the development machines' sibling folders
cross = Path(os.environ.get("ORBITALS_LINUX_CROSS") or first_existing(project / "tools" / "linux-cross" / "zig-x86_64-windows-0.15.2", worktrees / "Orbitals-Dev" / "build" / "linux-cross" / "zig-x86_64-windows-0.15.2").parent)
local_tools = Path(os.environ.get("ORBITALS_TOOLCHAIN") or first_existing(project / "external" / "orbitals-toolchain" / "vulkan-bin", worktrees / "Switch2RECOMP" / "build" / "orbitals-debug" / "toolchain" / "vulkan-bin").parent)
zig = cross / "zig-x86_64-windows-0.15.2" / "zig.exe"
sysroot = cross / "sysroot" / "usr"
library = sysroot / "lib" / "x86_64-linux-gnu"
out = Path(settings.out) if settings.out else project / "build" / "steamdeck-linux"
out.mkdir(parents=True, exist_ok=True)
for need in (zig, sysroot / "include" / "X11" / "Xlib.h", local_tools / "vulkan-bin"):
    if not need.exists():
        raise SystemExit(f"missing build input: {need}")
opus = project / "runtime" / "opus" / "lin" / "libopus.a"
if not opus.exists() and (library / "libopus.a").exists():
    opus.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(library / "libopus.a", opus)

os.environ["S2R_EXTERNAL"] = str(local_tools / "external")
os.environ["PATH"] = str(local_tools / "vulkan-bin") + os.pathsep + os.environ["PATH"]
os.environ["ZIG_GLOBAL_CACHE_DIR"] = str(cross / "cache")
os.chdir(project)
sys.path[:0] = [str(project), str(project / "tools")]
system_run = subprocess.run


def run_target(cmd, **options):
    parts = list(map(str, cmd))
    if parts[0] in ("gcc", "g++"):
        mode = "c++" if parts[0] == "g++" else "cc"
        new = [str(zig), mode, "-target", "x86_64-linux-gnu.2.34", "-isystem", str(sysroot / "include"),
               f"-ffile-prefix-map={project}=.", f"-ffile-prefix-map={cross}=linux-cross"]   # no build machine paths in the binaries
        shared = "-shared" in parts
        if any(Path(arg).name == "module.c" for arg in parts):
            new += ["-mfma"]
        if not shared:
            new += ["-fPIE"]
        if "-c" not in parts:
            new += ["-L" + str(library)]
            if not shared:
                new += ["-pie"]
        for arg in parts[1:]:
            if arg == "-lstdc++":
                new.append("-lc++")
            elif arg == "-Wl,-S" and not shared:
                continue   # zig's linker then drops .symtab too: keep the runtime's symbols for perf on the Deck
            elif arg == "-rdynamic" and not shared:
                continue   # the module imports nothing from the runtime; exports only interpose system libraries
            elif arg not in ("-static-libgcc", "-std=gnu17"):
                new.append(arg)
        return system_run(new, **options)
    if parts[0] == "ar":
        return system_run([str(zig), *parts], **options)
    return system_run(cmd, **options)


subprocess.run = run_target
import switchrecomp as sw

if settings.what == "runtime":
    # libnvn.a again with -fPIE (its objects go into the PIE)
    shutil.rmtree(project / "build" / "nvn_lin", ignore_errors=True)
    sys.argv = [sys.argv[0], "--linux", "--jobs", str(settings.jobs)]
    import build_nvn
    build_nvn.main()
    sw.build_runtime("gcc", str(out / "Orbitals"), False, "x11", print)
    artifact = out / "Orbitals"
else:
    if not settings.generated:
        cli.error("--generated is required for code. Generate the current C with switchrecomp.py --no-build.")
    baseline = Path(settings.generated).resolve()
    try:
        inputs = json.loads((baseline / "generation.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        raise SystemExit("Generate the current C and its identity with switchrecomp.py --no-build.")
    if inputs.get("contract") != sw.module_build.runtime_contract():
        raise SystemExit("This generated C was made for a different runtime contract. Regenerate it first.")
    generated = out / "Orbitals_build"
    generated.mkdir(exist_ok=True)
    if not (baseline / "module.c").is_file() or not all((baseline / name).is_file() for name in inputs["units"]):
        raise SystemExit(f"Saved code generation is incomplete: {baseline}")
    files = [str(baseline / name) for name in inputs.pop("units")]
    compiler = {"driver": "zig-cc", "version": subprocess.check_output([zig, "version"], text=True).strip(),
                "target": "x86_64-linux-gnu.2.34", "driver_sha256": sw.module_build.file_hash(zig)}
    inputs.update(options=sw.module_options("gcc", sw.DEFAULT_OPT, False, ()), compiler=compiler,
                  compiler_environment=sw.module_compiler_environment("gcc", sw.DEFAULT_OPT, False, (), compiler))
    inputs["options"]["cross_recipe"] = sw.module_build.source_hash(("tools/steamdeck/cross/build.py",))
    files.append(sw.module_identity_file(str(generated), inputs))
    objs = sw.compile_all(files, "gcc", sw.DEFAULT_OPT, str(generated), False, settings.jobs,
                          lambda s: print(s, flush=True), compiler=compiler)
    artifact = out / "Orbitals_code.so"
    sw.link_module(objs, "gcc", str(artifact), False, print)
    sw.module_build.write_json(sw.module_build.manifest_path(artifact),
                               {"schema": 1, "fingerprint": sw.module_build.digest(inputs), "inputs": inputs,
                                "module_sha256": sw.module_build.file_hash(artifact)})

header = artifact.open("rb").read(20)
assert header[:6] == b"\x7fELF\x02\x01" and header[18:20] == b">\0", header
kind = int.from_bytes(header[16:18], "little")
if settings.what == "runtime" and kind != 3:
    raise SystemExit(f"{artifact}: ELF type {kind}, expected 3 (PIE)")
print(f"ELF x86-64 type {kind}: {artifact} ({artifact.stat().st_size} bytes)", flush=True)
