# Orbitals PC Recomp, based on SwitchRecomp by MZ Labs. AGPL-3.0 with NOTICE.txt terms.

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import module_build as build
import switchrecomp as sw
from launcher import code_update as update, core
from test_launcher import build_fixture


class CodeUpdateTest(unittest.TestCase):
    def setUp(self):
        scratch = tempfile.TemporaryDirectory()
        self.addCleanup(scratch.cleanup)
        self.root = Path(scratch.name).resolve()
        self.kit = self.root / "kit"
        self.kit.mkdir()
        self.game_dir = self.root / "custom portable installation"
        build_fixture(self.game_dir)
        self.game = core.installation(self.game_dir)
        self.module = self.game_dir / core.MODULE
        self.contract = build.runtime_contract()
        self.runtime = self.kit / "new runtime"
        self.enterContext(patch.object(update, "available_runtime", return_value=self.runtime))
        self.enterContext(patch.object(core, "REPO", self.kit))
        self.enterContext(patch.object(update, "_check_native_pair"))
        self.enterContext(patch.object(sw, "compiler_identity", return_value={"version": "gcc test"}))
        self.enterContext(patch.object(sw, "module_compiler_environment", return_value=None))
        self.enterContext(patch.dict(os.environ, {"SWR_CFLAGS": ""}))
        self.write_runtime(self.runtime, "new")

    def write_runtime(self, path, tag, contract=None):
        magic = b"MZ\0\0" if core.WINDOWS else b"\x7fELF"
        path.write_bytes(magic + (build.RUNTIME_MARKER + (contract or self.contract) + "\0" + tag).encode())
        path.chmod(0o755)

    def stamp(self, **overrides):
        self.write_runtime(self.game.exe, "old")
        inputs = sw.orbitals_inputs(self.game.exefs, self.game.romfs, [], core.WINDOWS, {"version": "gcc test"})
        inputs.update(overrides)
        fingerprint = build.digest(inputs)
        self.module.write_bytes((build.MODULE_MARKER + inputs["contract"] + "\0" +
                                 build.FINGERPRINT_MARKER + fingerprint + "\0").encode())
        build.write_json(build.manifest_path(self.module), {"schema": 1, "inputs": inputs,
                         "fingerprint": fingerprint, "module_sha256": build.file_hash(self.module)})

    def test_quick_update_and_rollback_preserve_the_module_and_user_data(self):
        self.stamp()
        old = self.game.exe.read_bytes()
        self.game.saves.mkdir()
        cache = self.game_dir / "Orbitals_nvn"
        cache.mkdir()
        profile = self.root / "profiles"
        profile.mkdir()
        untouched = [self.game.saves / "save", cache / "shader", profile / "profile",
                     self.game_dir / "Orbitals.ini", self.module, build.manifest_path(self.module)]
        for path in untouched[:4]:
            path.write_bytes(path.name.encode())
        before = {path: (path.stat(), path.read_bytes()) for path in untouched}
        self.assertEqual(update.plan(self.game), update.FAST)
        updated = update.apply(self.game, update.FAST)
        self.assertEqual(updated.exe.read_bytes(), self.runtime.read_bytes())
        self.assertEqual(update.plan(updated), update.READY)
        self.assertTrue(update.can_restore(updated.root))
        update.rollback(updated.root)
        self.assertEqual(updated.exe.read_bytes(), old)
        for path, (info, contents) in before.items():
            self.assertTrue(os.path.samestat(path.stat(), info))
            self.assertEqual(path.read_bytes(), contents)

    def test_legacy_and_codegen_changes_force_recompilation(self):
        self.assertEqual(update.plan(self.game), update.RECOMPILE)
        self.stamp(contract="e" * 64)
        self.assertEqual(update.plan(self.game), update.RECOMPILE)

    def test_tools_can_be_updated_with_the_same_runtime_binary(self):
        self.stamp()
        self.runtime.write_bytes(self.game.exe.read_bytes())
        old_tools = self.game.root / "nxshader"
        new_tools = self.kit / "tools/nxshader"
        for directory in (old_tools, new_tools):
            directory.mkdir(parents=True)
            (directory / "nxs_live.py").write_text(directory.name, encoding="ascii")
        self.assertTrue(update.kit_differs(self.game))
        self.assertEqual(update.plan(self.game), update.FAST)
        game = update.apply(self.game, update.FAST)
        self.assertEqual(core.shader_tools(game).resolve(), new_tools)
        self.assertEqual(update.plan(game), update.READY)

    def test_compiler_generation_options_and_game_input_are_checked(self):
        self.stamp(chunk=100)
        self.assertEqual(update.plan(self.game), update.RECOMPILE)
        self.stamp()
        (self.game.exefs / "main.npdm").write_bytes(b"META changed")
        self.assertEqual(update.plan(self.game), update.RECOMPILE)
        self.stamp()
        with patch.object(sw, "extra_cflags", return_value=["-march=native"]):
            self.assertEqual(update.plan(self.game), update.RECOMPILE)
        with patch.dict(os.environ, {"SWR_A64_NO_INLINE_SIMD": "1"}):
            self.assertEqual(update.plan(self.game), update.RECOMPILE)

    def test_changed_module_is_refused_before_any_file_is_replaced(self):
        self.stamp()
        old = self.game.exe.read_bytes()
        self.module.write_bytes(self.module.read_bytes() + b"bad module")
        self.assertEqual(update.plan(self.game), update.RECOMPILE)
        with self.assertRaisesRegex(core.LauncherError, "Quick update refused"):
            update.apply(self.game, update.FAST)
        with self.assertRaisesRegex(core.LauncherError, "incompatible"):
            update.assert_launchable(self.game)
        self.assertEqual(self.game.exe.read_bytes(), old)
        self.assertFalse(update.can_restore(self.game.root))

    def test_an_older_kit_keeps_a_newer_installation(self):
        self.stamp()
        with self.game.exe.open("ab") as stream:
            stream.write(b"\0" + b"99.0.0 1234567\0")
        self.assertFalse(update.kit_differs(self.game))
        self.assertEqual(update.plan(self.game), update.READY)

    def test_failed_publication_restores_old_runtime_and_tools(self):
        self.stamp()
        old = self.game.exe.read_bytes()
        tools = self.game_dir / "nxshader"
        tools.mkdir()
        (tools / "marker").write_bytes(b"old tools")
        new_tools = self.kit / "tools/nxshader"
        new_tools.mkdir(parents=True)
        rename = Path.rename

        def fail_runtime(path, destination):
            if path.name == core.EXE and path.parent.name == "new":
                raise OSError("file locked")
            return rename(path, destination)

        with patch.object(Path, "rename", fail_runtime):
            with self.assertRaisesRegex(OSError, "file locked"):
                update.apply(self.game, update.FAST)
        self.assertEqual(self.game.exe.read_bytes(), old)
        self.assertEqual((tools / "marker").read_bytes(), b"old tools")
        self.assertFalse((self.game.root / update.JOURNAL).exists())
        update.assert_launchable(self.game)

    def test_interrupted_publication_recovers_before_opening_installation(self):
        self.stamp()
        old = self.game.exe.read_bytes()
        work = self.game.root / ".orbitals-payload-interrupted"
        (work / "previous").mkdir(parents=True)
        (work / "discard").mkdir()
        self.game.exe.rename(work / "previous" / core.EXE)
        build.write_json(self.game.root / update.JOURNAL, {"phase": "pending", "work": work.name,
                         "files": {core.EXE: True}})
        self.assertEqual(core.installation(self.game.root).exe.read_bytes(), old)
        self.assertFalse(work.exists())


class ObjectCacheTest(unittest.TestCase):
    def test_cache_uses_content_not_mtime_and_reuses_objects_in_another_stage(self):
        with tempfile.TemporaryDirectory() as work:
            root = Path(work)
            a, b = root / "a", root / "b"
            for path in (a, b):
                path.mkdir()
                (path / "code_001.c").write_text("int code;", encoding="ascii")

            def compile_one(cmd, _):
                Path(cmd[-1]).write_bytes(b"object")

            def compile_stage(path):
                return sw.compile_all([str(path / "code_001.c")], "gcc", "2", path, core.WINDOWS, 1, lambda _: None,
                                      object_cache=root / "cache", compiler={"version": "gcc test"})

            with (patch.object(sw, "object_cache_context", return_value="context"),
                  patch.object(sw, "run_cc", side_effect=compile_one) as cc):
                cached = compile_stage(a)
                self.assertEqual(compile_stage(b), cached)
                source = b / "code_001.c"
                info = source.stat()
                source.write_text("int data;", encoding="ascii")
                os.utime(source, ns=(info.st_atime_ns, info.st_mtime_ns))
                self.assertNotEqual(compile_stage(b), cached)
                self.assertEqual(cc.call_count, 2)


class CodeContractTest(unittest.TestCase):
    def test_detects_changes_to_dispatch_and_codegen(self):
        baseline = build.runtime_contract()

        def changed(name, old, new):
            return build.runtime_contract(lambda path: build.source_bytes(path).replace(old, new)
                                          if path == name else build.source_bytes(path))

        self.assertNotEqual(changed("runtime/main.c", b"g_disp=calloc", b"g_disp=malloc"), baseline)
        self.assertNotEqual(changed("codegen.py", b"def emit_function", b"def changed_emit_function"), baseline)
        self.assertEqual(changed("runtime/main.c", b"void gamepad_report", b"void changed_gamepad_report"), baseline)
