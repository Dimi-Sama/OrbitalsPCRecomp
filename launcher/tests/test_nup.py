# Orbitals PC Recomp, based on SwitchRecomp by MZ Labs (AGPL v3, see NOTICE.txt).
"""Synthetic NUP archives built in temporary folders. Fixtures contain only test bytes."""

import hashlib
import io
import struct
import tempfile
import unittest
import zipfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from launcher import core, nup, nup_codec
from launcher.tests.test_launcher import build_fixture

try:
    from compression import zstd
except ImportError:
    try:
        from backports import zstd
    except ImportError:
        zstd = None


def archive_bytes(files, *, package_kind=0, compressed=None):
    return package_archive([(package_kind, files, compressed or {})])


def package_archive(packages):
    """Encode a small archive using the layouts in the NUP v1 specification."""
    dirs, files, compressed = set(), {}, {}
    for package_index, (_, package_files, frames) in enumerate(packages):
        root = (package_index,)
        dirs.add(root)
        files.update((root + parts, payload) for parts, payload in package_files.items())
        compressed.update((root + parts, frame) for parts, frame in frames.items())
    for parts in files:
        dirs.update(parts[:length] for length in range(2, len(parts)))
    dirs = sorted(dirs)
    pool, slots, dir_records, file_records = (bytearray() for _ in range(4))

    def name(parts):
        raw = parts[-1].encode() if len(parts) > 1 else b""
        offset = len(pool)
        pool.extend(raw)
        return offset, len(raw)

    for parts in dirs:
        children = [index for index, path in enumerate([*dirs, *files]) if path[:-1] == parts]
        dir_records.extend(struct.pack("<IIIIQ", *name(parts), len(slots) // 4, len(children), 0))
        for index in children:
            slots.extend(struct.pack("<I", index))
    dir_ids = {parts: index for index, parts in enumerate(dirs)}
    package_records = bytearray()
    identity = bytearray()
    has_base = any(kind == 0 for kind, _, _ in packages)
    for index, (kind, _, _) in enumerate(packages):
        root = (index,)
        version = index << 16
        flags = int(kind == 1 and not has_base)
        package_records.extend(struct.pack("<QIIIIBBHIQI20x", 0, dir_ids[root],
                                           dir_ids.get(root + ("exefs",), 0xFFFFFFFF),
                                           dir_ids.get(root + ("romfs",), 0xFFFFFFFF),
                                           version, kind, flags, 0, 0, 0, 0))
        identity.extend(struct.pack("<QIB", 0, version, kind))
    file_names = {parts: name(parts) for parts in files}
    pool_offset = 48 + len(package_records) + len(dir_records) + 80 * len(files) + len(slots)
    toc_size = pool_offset + len(pool)
    blobs_at = (128 + toc_size + 15) & ~15
    blobs = bytearray()
    dedup = {}
    for parts, payload in files.items():
        packed = compressed.get(parts, payload)
        if packed and packed not in dedup:
            blobs.extend(b"\0" * (-len(blobs) % 16))
            dedup[packed] = blobs_at + len(blobs)
            blobs.extend(packed)
        file_records.extend(struct.pack("<IIQQQ32sB15x", *file_names[parts], len(payload), dedup.get(packed, 0),
                                        len(packed), hashlib.sha256(payload).digest(), int(parts in compressed)))
    toc = (struct.pack("<4sIQQQQQ", b"TOC\x01", len(packages), len(dirs), len(files), pool_offset, len(pool), 0)
           + package_records + dir_records + file_records + slots + pool)
    uuid = hashlib.sha256(identity).digest()[:16]
    header = struct.pack("<4sHHQQ32sQQII16s32x", b"NUP\x01", 128, 1, 128, len(toc), hashlib.sha256(toc).digest(),
                         blobs_at, blobs_at + len(blobs), len(packages), 0, uuid)
    return bytearray(header + toc + bytes(blobs_at - 128 - len(toc)) + blobs)


class NupTest(unittest.TestCase):
    def setUp(self):
        workspace = tempfile.TemporaryDirectory()
        self.addCleanup(workspace.cleanup)
        self.root = Path(workspace.name).resolve()
        self.archive = self.root / "local.nup"
        self.output = self.root / "output"
        self.files = {("exefs", "main"): b"program", ("romfs", "hello.txt"): b"hello"}

    def extract(self, blob, progress=lambda *_: None):
        self.archive.write_bytes(blob)
        nup.extract_base(self.archive, self.output, lambda: zstd, progress)

    def test_extracts_only_game_trees_and_verifies_optional_data(self):
        files = self.files | {("data", "optional.txt"): b"optional", ("romfs", "empty.txt"): b"",
                              ("romfs", "nested", "duplicate.txt"): b"hello"}
        progress = []
        self.extract(archive_bytes(files), lambda done, total: progress.append((done, total)))
        self.assertEqual((self.output / "exefs/main").read_bytes(), b"program")
        self.assertEqual((self.output / "romfs/nested/duplicate.txt").read_bytes(), b"hello")
        self.assertEqual((self.output / "romfs/empty.txt").read_bytes(), b"")
        self.assertFalse((self.output / "data").exists())
        total = sum(map(len, files.values()))
        self.assertEqual(progress[0], (0, total))
        self.assertEqual(progress[-1], (total, total))

    def test_rejects_bad_toc_payload_and_truncation(self):
        for where, message in ((129, "table of contents"), (-1, "SHA-256")):
            with self.subTest(where=where):
                blob = archive_bytes(self.files)
                blob[where] ^= 1
                self.output = self.root / str(where)
                with self.assertRaisesRegex(nup.NupError, message):
                    self.extract(blob)
        with self.assertRaisesRegex(nup.NupError, "archive size"):
            self.extract(archive_bytes(self.files)[:-1])

    def test_extracts_the_base_when_update_precedes_it(self):
        update = {("exefs", "main"): b"patched program", ("romfs", "hello.txt"): b"patched data"}
        addon = {("romfs", "dlc.txt"): b"hello"}  # shared extent with the base
        self.archive.write_bytes(package_archive([
            (1, update, {("exefs", "main"): b"ignored compressed bytes"}),
            (0, self.files, {}),
            (2, addon, {}),
        ]))
        progress = []
        nup.extract_base(self.archive, self.output, lambda: self.fail("Update payload should be skipped"),
                         lambda done, total: progress.append((done, total)))
        for parts, payload in self.files.items():
            self.assertEqual(self.output.joinpath(*parts).read_bytes(), payload)
        self.assertFalse((self.output / "romfs/dlc.txt").exists())
        total = sum(map(len, self.files.values()))
        self.assertEqual(progress[0], (0, total))
        self.assertEqual(progress[-1], (total, total))

    def test_rejects_archives_without_exactly_one_base(self):
        for kind in (1, 2):
            with self.assertRaisesRegex(nup.NupError, "no base game package"):
                self.extract(archive_bytes(self.files, package_kind=kind))
        with self.assertRaisesRegex(nup.NupError, "more than one base game package"):
            self.extract(package_archive([(0, self.files, {}), (0, self.files, {})]))
        self.assertFalse(self.output.exists())

    def test_checks_multi_package_count_and_identity(self):
        for offset, message in ((0x48, "table of contents"), (0x50, "package identity")):
            blob = package_archive([(0, self.files, {}), (1, self.files, {})])
            blob[offset] ^= 1
            with self.assertRaisesRegex(nup.NupError, message):
                self.extract(blob)
        self.assertFalse(self.output.exists())

    def test_base_cannot_use_another_packages_exefs(self):
        blob = package_archive([(0, self.files, {}), (1, self.files, {})])
        update_exefs, = struct.unpack_from("<I", blob, 128 + 48 + 64 + 12)
        struct.pack_into("<I", blob, 128 + 48 + 12, update_exefs)
        toc_size, = struct.unpack_from("<Q", blob, 16)
        blob[24:56] = hashlib.sha256(blob[128:128 + toc_size]).digest()
        with self.assertRaisesRegex(nup.NupError, "directory reference"):
            self.extract(blob)
        self.assertFalse(self.output.exists())

    def test_rejects_unsafe_and_conflicting_names_before_writing(self):
        for name in ("..", "a/b", "a\\b", "C:asset", "NUL.txt", "bad.", "new\x00name", "HELLO.TXT"):
            with self.subTest(name=name):
                with self.assertRaisesRegex(nup.NupError, "unsafe path|conflicting paths"):
                    self.extract(archive_bytes(self.files | {("romfs", name): b"test"}))
                self.assertFalse(self.output.exists())

    def test_rejects_repeated_tree_nodes(self):
        blob = archive_bytes(self.files)
        toc_size, = struct.unpack_from("<Q", blob, 16)
        slot = 128 + 48 + 64 + 3 * 24 + 2 * 80
        struct.pack_into("<I", blob, slot, 0)
        blob[24:56] = hashlib.sha256(blob[128:128 + toc_size]).digest()
        with self.assertRaisesRegex(nup.NupError, "repeated or out-of-range child"):
            self.extract(blob)
        self.assertFalse(self.output.exists())

    def test_checks_disk_space_before_creating_output(self):
        with patch.object(nup.shutil, "disk_usage", return_value=SimpleNamespace(free=0)):
            with self.assertRaisesRegex(nup.NupError, "disk space"):
                self.extract(archive_bytes(self.files))
        self.assertFalse(self.output.exists())

    @unittest.skipIf(zstd is None, "needs Python 3.14 or backports.zstd for fixture compression")
    def test_streams_single_zstandard_frames_and_rejects_trailing_data(self):
        member = ("romfs", "hello.txt")
        payload = b"hello" * (1 << 20)
        files = self.files | {member: payload}
        frame = zstd.compress(payload)
        self.extract(archive_bytes(files, compressed={member: frame}))
        self.assertEqual((self.output / "romfs/hello.txt").read_bytes(), payload)
        for suffix, bad in (("trailing", frame + frame), ("truncated", frame[:-1]), ("wrong-size", zstd.compress(b"no"))):
            with self.subTest(suffix=suffix):
                self.output = self.root / suffix
                with self.assertRaisesRegex(nup.NupError, "Zstandard"):
                    self.extract(archive_bytes(files, compressed={member: bad}))


class CodecTest(unittest.TestCase):
    def test_only_verified_wheel_is_cached_and_reused(self):
        with tempfile.TemporaryDirectory() as work:
            cache = Path(work) / "cache"
            target = io.BytesIO()
            with zipfile.ZipFile(target, "w") as archive:
                archive.writestr("test.txt", "fixture")
            body = target.getvalue()
            digest = hashlib.sha256(body).hexdigest()
            wheels = {("cp312", "win-amd64"): ("win_amd64", "test", digest)}
            with patch.object(nup_codec, "WHEELS", wheels), patch.object(nup_codec.urllib.request, "urlopen") as fetch:
                fetch.return_value = io.BytesIO(body + b"changed")
                with self.assertRaisesRegex(nup_codec.CodecError, "SHA-256"):
                    nup_codec.install_wheel(cache, "cp312", "win-amd64")
                self.assertFalse(cache.exists())
                fetch.return_value = io.BytesIO(body)
                installed = nup_codec.install_wheel(cache, "cp312", "win-amd64")
                self.assertEqual((installed / "test.txt").read_text(), "fixture")
                self.assertEqual(nup_codec.install_wheel(cache, "cp312", "win-amd64"), installed)
                self.assertEqual(fetch.call_count, 2)


class StagedInstallTest(unittest.TestCase):
    def setUp(self):
        workspace = tempfile.TemporaryDirectory()
        self.addCleanup(workspace.cleanup)
        self.root = Path(workspace.name).resolve()
        self.shared = self.root / "kit" / "games"
        self.external = self.root / "Jeux [locaux]"
        self.external.mkdir()
        self.destination = self.external / "Orbitals été"
        self.source = build_fixture(self.root / "dump")
        self.archive = self.root / "local.nup"
        self.files = {path.relative_to(self.source).parts: path.read_bytes() for path in self.source.rglob("*") if path.is_file()}
        self.archive.write_bytes(archive_bytes(self.files))

    def fake_setup(self, data, install_dir, on_progress, *, game_dir):
        self.assertEqual(install_dir, self.shared)
        if data != game_dir / core.DATA:
            (game_dir / core.DATA).mkdir(parents=True)
            for name in nup.GAME_TREES:
                core.link_directory(game_dir / core.DATA / name, data / name)
        (game_dir / core.EXE).write_bytes(b"MZfixture" if core.WINDOWS else b"\x7fELFfixture")
        (game_dir / core.EXE).chmod(0o755)
        (game_dir / core.MODULE).write_bytes(b"code")
        on_progress(5, 5, "Ready")
        return core.installation(game_dir)

    def test_nup_custom_folder_is_published_without_data_links_and_remembered(self):
        self.destination.mkdir()
        update = {("exefs", "main"): b"patched program", ("romfs", "patch.txt"): b"patched data"}
        self.archive.write_bytes(package_archive([(0, self.files, {}), (1, update, {})]))
        progress = []
        compilation = []
        with patch.object(core, "install_from_files", side_effect=self.fake_setup) as installer:
            game = core.stage_install(self.archive, self.destination, from_nup=True, install_dir=self.shared,
                                      on_extract=progress.append, on_progress=lambda *event: compilation.append(event))
        self.assertEqual(game.root, self.destination)
        self.assertEqual(game.exefs, self.destination / core.DATA / "exefs")
        self.assertEqual((game.exefs / "main").read_bytes(), self.files["exefs", "main"])
        self.assertFalse((game.romfs / "patch.txt").exists())
        self.assertEqual(core.game_source(game), self.destination / core.DATA)
        self.assertEqual(installer.call_args.args[0], installer.call_args.kwargs["game_dir"] / core.DATA)
        self.assertEqual(list(self.external.glob(".orbitals-stage-*")), [])
        self.assertEqual(progress[-1].done, progress[-1].total)
        self.assertEqual(compilation[-1], (5, 5, "Ready"))
        self.assertEqual(core.inspect_install_destination(self.destination)[1], game)
        self.assertIn(f"Published installation: {self.destination}", (self.shared / "setup.log").read_text(encoding="utf-8"))

    def test_folder_method_keeps_default_path_and_links(self):
        with patch.object(core, "install_from_files", side_effect=self.fake_setup):
            game = core.stage_install(self.source, install_dir=self.shared)
        self.assertEqual(game.root, self.shared / "Orbitals")
        self.assertEqual(game.exefs, self.source / "exefs")
        self.assertEqual(game.romfs, self.source / "romfs")

    def test_extraction_error_cleans_staging_and_keeps_existing_empty_folder(self):
        self.destination.mkdir()
        blob = bytearray(self.archive.read_bytes())
        blob[-1] ^= 1
        self.archive.write_bytes(blob)
        with patch.object(core, "install_from_files") as setup:
            with self.assertRaisesRegex(core.LauncherError, "SHA-256"):
                core.stage_install(self.archive, self.destination, from_nup=True, install_dir=self.shared)
        setup.assert_not_called()
        self.assertEqual(list(self.external.iterdir()), [self.destination])
        self.assertEqual(list(self.destination.iterdir()), [])

    def test_stop_after_extraction_cleans_temporary_data_and_allows_retry(self):
        from launcher.tasks import Stopped, Task

        self.destination.mkdir()
        task = Task()

        def stop_when_written(progress):
            if progress.total and progress.done == progress.total:
                task.stop()

        with patch.object(core, "install_from_files", side_effect=self.fake_setup) as setup:
            with self.assertRaisesRegex(Stopped, "temporary data was removed"):
                core.stage_install(self.archive, self.destination, from_nup=True, install_dir=self.shared,
                                   task=task, on_extract=stop_when_written)
            setup.assert_not_called()
            self.assertEqual(list(self.external.iterdir()), [self.destination])
            self.assertEqual(list(self.destination.iterdir()), [])
            game = core.stage_install(self.archive, self.destination, from_nup=True, install_dir=self.shared, task=Task())
        self.assertEqual(game.root, self.destination)

    def test_failed_compilation_cleans_links_leaves_source_and_allows_retry(self):
        def fail(*args, **kwargs):
            self.fake_setup(*args, **kwargs)
            raise core.LauncherError("AOT failed")

        with patch.object(core, "install_from_files", side_effect=fail):
            with self.assertRaisesRegex(core.LauncherError, "AOT failed"):
                core.stage_install(self.source, self.destination, install_dir=self.shared)
        self.assertTrue((self.source / "exefs/main").is_file())
        self.assertEqual(list(self.external.iterdir()), [])
        with patch.object(core, "install_from_files", side_effect=self.fake_setup):
            game = core.stage_install(self.source, self.destination, install_dir=self.shared)
        self.assertEqual(game.root, self.destination)
        self.assertEqual(game.romfs, self.source / "romfs")

    def test_existing_files_and_an_unwritable_parent_are_reported(self):
        self.destination.mkdir()
        marker = self.destination / "keep.txt"
        marker.write_text("user files")
        with patch.object(core, "install_from_files") as setup:
            with self.assertRaisesRegex(core.LauncherError, "contains files"):
                core.stage_install(self.source, self.destination, install_dir=self.shared)
            with patch.object(core.tempfile, "TemporaryDirectory", side_effect=PermissionError("denied")):
                with self.assertRaisesRegex(core.LauncherError, "writable folder"):
                    core.stage_install(self.source, self.external / "Unavailable", install_dir=self.shared)
        setup.assert_not_called()
        self.assertEqual(marker.read_text(), "user files")

    def test_preserves_files_created_in_the_destination_during_the_build(self):
        self.destination.mkdir()
        marker = self.destination / "created-during-build.txt"

        def finish(*args, **kwargs):
            game = self.fake_setup(*args, **kwargs)
            marker.write_text("user files")
            return game

        with patch.object(core, "install_from_files", side_effect=finish):
            with self.assertRaisesRegex(core.LauncherError, "contains files"):
                core.stage_install(self.source, self.destination, install_dir=self.shared)
        self.assertEqual(list(self.external.iterdir()), [self.destination])
        self.assertEqual(list(self.destination.iterdir()), [marker])
        self.assertEqual(marker.read_text(), "user files")

    def test_selects_inside_a_mounted_volume_to_keep_staging_on_that_volume(self):
        self.destination.mkdir()
        with patch.object(Path, "is_mount", return_value=True):
            with self.assertRaisesRegex(core.LauncherError, "inside the mounted drive"):
                core.inspect_install_destination(self.destination)
