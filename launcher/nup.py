# Orbitals PC Recomp, based on SwitchRecomp by MZ Labs (AGPL v3, see NOTICE.txt).
"""Read the base game from a NUP v1 archive. Format: https://github.com/a55uka/nup/blob/meow/SPEC.md."""

import hashlib
import os
import re
import shutil
import stat
import struct
import unicodedata
from contextlib import nullcontext
from dataclasses import dataclass
from pathlib import Path

HEADER = struct.Struct("<4sHHQQ32sQQII16s32s")
TOC = struct.Struct("<4sIQQQQQ")
PACKAGE = struct.Struct("<QIIIIBBHIQI20s")
DIRECTORY = struct.Struct("<IIIIQ")
FILE = struct.Struct("<IIQQQ32sB15s")
CHILD = struct.Struct("<I")
META = struct.Struct("<HHI")
KIND_BASE = 0
KIND_UPDATE = 1
NO_DIR = 0xFFFFFFFF
CHUNK = 1 << 20
MAX_TOC = 64 << 20
MAX_METADATA = 16 << 20
MAX_NODES = 250_000
MAX_DEPTH = 64
MAX_WINDOW_LOG = 27  # 128 MiB of Zstandard history
GAME_TREES = ("exefs", "romfs")
DEVICE = re.compile(r"(?:CON|PRN|AUX|NUL|CONIN\$|CONOUT\$|(?:COM|LPT)[1-9¹²³])", re.IGNORECASE)
FORBIDDEN = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


class NupError(ValueError):
    """Invalid archive or unsupported NUP feature."""


@dataclass(frozen=True, slots=True)
class Extent:
    size: int
    offset: int
    stored: int
    digest: bytes
    codec: int


def read_exact(stream, size):
    data = stream.read(size)
    if len(data) != size:
        raise NupError("The NUP archive is truncated.")
    return data


def component(raw):
    try:
        name = raw.decode("utf-8")
    except UnicodeError as error:
        raise NupError("A NUP path is not UTF-8.") from error
    if (not name or name.endswith((".", " ")) or FORBIDDEN.search(name)
            or DEVICE.fullmatch(name.split(".", 1)[0].rstrip(" "))
            or len(raw) > 255):
        raise NupError("The NUP archive contains an unsafe path component.")
    return name


def read_plan(stream):
    """Validate the TOC and return directories and files in traversal order."""
    info = os.fstat(stream.fileno())
    if not stat.S_ISREG(info.st_mode):
        raise NupError("Choose a regular .nup file.")
    (magic, header_size, version, toc_start, toc_size, toc_hash, blob_start,
     length, package_count, flags, uuid, reserved) = HEADER.unpack(read_exact(stream, HEADER.size))
    if (magic, version, flags) != (b"NUP\x01", 1, 0) or any(reserved):
        raise NupError("Unsupported NUP header. Choose a NUP v1 archive.")
    if not (header_size == toc_start == HEADER.size and TOC.size <= toc_size <= MAX_TOC
            and toc_start + toc_size <= blob_start <= length == info.st_size and blob_start % 16 == 0):
        raise NupError("Invalid NUP header or archive size.")
    toc = read_exact(stream, toc_size)
    if hashlib.sha256(toc).digest() != toc_hash:
        raise NupError("The NUP table of contents failed its SHA-256 check.")

    magic, count, ndirs, nfiles, pool, pool_size, reserved = TOC.unpack_from(toc)
    dirs_start = TOC.size + package_count * PACKAGE.size
    files_start = dirs_start + ndirs * DIRECTORY.size
    children_start = files_start + nfiles * FILE.size
    node_count = ndirs + nfiles
    slot_count = node_count - package_count
    if (magic != b"TOC\x01" or count != package_count or reserved
            or not 1 <= package_count <= ndirs <= node_count <= MAX_NODES
            or pool != children_start + slot_count * CHILD.size or pool + pool_size > toc_size):
        raise NupError("Invalid NUP table of contents.")

    def name_bytes(offset, length):
        if not (length <= 255 and offset + length <= pool_size):
            raise NupError("Invalid NUP name reference.")
        return toc[pool + offset:pool + offset + length]

    base = None
    roots = set()
    metadata_ranges = []
    identity = hashlib.sha256()
    for index in range(package_count):
        title, root, exefs, romfs, version, kind, flags, reserved, reserved2, meta_at, meta_size, tail = (
            PACKAGE.unpack_from(toc, TOC.size + index * PACKAGE.size))
        allowed_flags = 1 if kind == KIND_UPDATE else 0  # standalone update
        if (kind > 4 or flags & ~allowed_flags or reserved or reserved2 or any(tail)
                or root >= ndirs or root in roots):
            raise NupError("Invalid NUP package record.")
        if any(directory != NO_DIR and directory >= ndirs for directory in (exefs, romfs)):
            raise NupError("Invalid NUP ExeFS or RomFS directory reference.")
        if (meta_size > MAX_METADATA or (meta_size and not blob_start <= meta_at <= length - meta_size)
                or (not meta_size and meta_at)):
            raise NupError("Invalid NUP metadata extent.")
        roots.add(root)
        identity.update(struct.pack("<QIB", title, version, kind))
        if meta_size:
            metadata_ranges.append((meta_at, meta_at + meta_size))
        if kind == KIND_BASE:
            if base is not None:
                raise NupError("The NUP archive contains more than one base game package.")
            base = root, exefs, romfs, meta_at, meta_size
    if uuid != identity.digest()[:16]:
        raise NupError("Invalid NUP package identity.")
    if base is None:
        raise NupError("The NUP archive has no base game package. Choose an archive containing the base game.")
    root, exefs, romfs, meta_at, meta_size = base
    if exefs == romfs or max(exefs, romfs) >= ndirs or exefs in roots or romfs in roots:
        raise NupError("The NUP base package must contain both ExeFS and RomFS.")

    dirs = []
    for index in range(ndirs):
        offset, size, first, count, reserved = DIRECTORY.unpack_from(toc, dirs_start + index * DIRECTORY.size)
        if reserved or first + count > slot_count:
            raise NupError("Invalid NUP directory record.")
        dirs.append((name_bytes(offset, size), first, count))

    files = []
    extents = {}
    for index in range(nfiles):
        offset, size, unpacked, start, stored, digest, codec, reserved = FILE.unpack_from(
            toc, files_start + index * FILE.size)
        if codec not in (0, 1) or any(reserved) or (codec == 0 and stored != unpacked):
            raise NupError("Invalid or unsupported NUP file codec.")
        extent = Extent(unpacked, start, stored, digest, codec)
        if unpacked:
            if not (stored and blob_start <= start <= length - stored and start % 16 == 0):
                raise NupError("A NUP file extent lies outside of the blob region.")
            if extents.setdefault(start, extent) != extent:
                raise NupError("Conflicting NUP file extents share an offset.")
        elif start or stored or codec:
            raise NupError("An empty NUP file has an extent.")
        files.append((name_bytes(offset, size), extent))

    ranges = [(offset, offset + entry.stored) for offset, entry in extents.items()]
    ranges.extend(metadata_ranges)
    end = blob_start
    for start, stop in sorted(ranges):
        if start < end:
            raise NupError("NUP blob extents overlap.")
        end = stop
    if meta_size:
        read_metadata(stream, meta_at, meta_size)

    root_name, _, _ = dirs[root]
    if root_name:
        component(root_name)
    selected = {exefs: b"exefs", romfs: b"romfs"}
    directories = []
    entries = []
    seen = roots.copy()
    used_slots = bytearray(slot_count)

    def walk(index, path, keep, depth):
        _, start, count = dirs[index]
        if depth >= MAX_DEPTH and count:
            raise NupError("The NUP directory tree is too deep.")
        names = set()
        for slot in range(start, start + count):
            child, = CHILD.unpack_from(toc, children_start + slot * CHILD.size)
            if used_slots[slot] or child in seen or child >= node_count:
                raise NupError("Invalid NUP tree: repeated or out-of-range child.")
            used_slots[slot] = 1
            seen.add(child)
            is_dir = child < ndirs
            child_path = None
            copy = False
            if path is not None:
                raw = dirs[child][0] if is_dir else files[child - ndirs][0]
                name = component(raw)
                folded = unicodedata.normalize("NFC", name.casefold())
                if folded in names:
                    raise NupError("The NUP tree contains conflicting paths.")
                names.add(folded)
                child_path = path / name
                if child in selected and (index != root or raw != selected[child]):
                    raise NupError("Invalid NUP ExeFS or RomFS directory reference.")
                copy = keep or child in selected
            if is_dir:
                if copy:
                    directories.append(child_path)
                walk(child, child_path, copy, depth + 1)
            elif child_path is not None:
                entries.append((child_path, files[child - ndirs][1], copy))

    walk(root, Path(), False, 0)
    if not selected.keys() <= seen:
        raise NupError("Invalid NUP ExeFS or RomFS directory reference.")
    for other_root in roots - {root}:
        walk(other_root, None, False, 0)
    if len(seen) != node_count:
        raise NupError("The NUP tree has unreachable nodes.")
    return directories, entries


def read_metadata(stream, offset, size):
    end = offset + size
    stream.seek(offset)
    while end - stream.tell() >= META.size:
        _, reserved, length = META.unpack(read_exact(stream, META.size))
        if reserved or length > end - stream.tell():
            raise NupError("Invalid NUP metadata record.")
        stream.seek(length, os.SEEK_CUR)


def base_fingerprint(archive):
    """Identity of the trees the installer extracts, independent of bundled updates."""
    with archive.open("rb") as stream:
        directories, entries = read_plan(stream)
    digest = hashlib.sha256()
    for path in sorted(directory.as_posix() for directory in directories):
        digest.update(b"D" + path.encode("utf-8") + b"\0")
    files = sorted((relative.as_posix(), extent.digest) for relative, extent, copy in entries if copy)
    for path, content in files:
        digest.update(b"F" + path.encode("utf-8") + b"\0" + content)
    return digest.hexdigest()


def file_blocks(stream, extent, zstd):
    remaining = extent.stored
    stream.seek(extent.offset)
    if not extent.codec:
        while remaining:
            data = read_exact(stream, min(CHUNK, remaining))
            remaining -= len(data)
            yield data
        return

    data = read_exact(stream, min(CHUNK, remaining))
    remaining -= len(data)
    if data[:4] != b"\x28\xb5\x2f\xfd" or zstd.get_frame_info(data).decompressed_size != extent.size:
        raise NupError("The NUP Zstandard frame has an invalid content size or header.")
    decoder = zstd.ZstdDecompressor(options={zstd.DecompressionParameter.window_log_max: MAX_WINDOW_LOG})
    while not decoder.eof:
        if decoder.needs_input and not data:
            if not remaining:
                raise NupError("A NUP Zstandard frame is truncated.")
            data = read_exact(stream, min(CHUNK, remaining))
            remaining -= len(data)
        decoded = decoder.decompress(data, max_length=CHUNK)
        data = b""
        if decoded:
            yield decoded
    if remaining or decoder.unused_data:
        raise NupError("Unexpected data after a NUP Zstandard frame.")


def extract_base(archive, destination, get_zstd, progress):
    """Write verified ExeFS/RomFS into a new staging folder owned by the caller."""
    with archive.open("rb") as stream:
        directories, entries = read_plan(stream)
        total = sum(entry.size for _, entry, _ in entries)
        bytes_to_write = sum(entry.size for _, entry, copy in entries if copy)
        if bytes_to_write > shutil.disk_usage(destination.parent).free:
            raise NupError(f"Not enough disk space to extract the NUP ({bytes_to_write / 2**30:.1f} GiB needed).")
        zstd = get_zstd() if any(entry.codec for _, entry, _ in entries) else None
        decode_error = zstd.ZstdError if zstd is not None else ()
        destination.mkdir()
        for relative in directories:
            (destination / relative).mkdir()
        done = 0
        progress(done, total)
        for relative, extent, copy in entries:
            digest = hashlib.sha256()
            size = 0
            target = (destination / relative).open("xb") if copy else nullcontext()
            with target as output:
                try:
                    for block in file_blocks(stream, extent, zstd):
                        size += len(block)
                        if size > extent.size:
                            raise NupError("A NUP file exceeds its declared size.")
                        digest.update(block)
                        if output is not None:
                            output.write(block)
                        done += len(block)
                        progress(done, total)
                except decode_error as error:
                    raise NupError(f"Invalid Zstandard data in NUP file {relative.as_posix()}.") from error
            if size != extent.size or digest.digest() != extent.digest:
                raise NupError(f"NUP file failed its size or SHA-256 check ({relative.as_posix()}).")
