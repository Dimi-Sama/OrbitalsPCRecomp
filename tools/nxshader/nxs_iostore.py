#!/usr/bin/env python3
# SwitchRecomp - Copyright 2026 MZ Labs
# Licensed under the GNU Affero General Public License v3.0, see LICENSE.txt and NOTICE.txt.
# Forks and derived works have to keep the credit to SwitchRecomp by MZ Labs and the startup screen.
"""nxs_iostore: aggregate inventory and bounded extraction of the shader chunks of an UE5 IoStore container, and an
optional comparison of two folders of captured NVN2 shaders.

  nxs_iostore.py inventory CONTAINER.utoc [...]     counts ShaderCodeLibrary (type 8) and ShaderCode (type 9) chunk ids
  nxs_iostore.py coverage DIR_A DIR_B               counts the <key>.ctl/.code pairs both folders share
  nxs_iostore.py extract C.utoc C.ucas NEW_DIR      copies the type 8/9 chunks into a directory that does not exist yet
  nxs_iostore.py payloads NEW_DIR                   verifies an extraction and reports its shader library layout

inventory reads only the TOC header and the chunk id table, in blocks of a bounded size. Header: 16-byte magic, version
byte at 16, little-endian uint32 header size at 20 and entry count at 24, then 12-byte chunk ids from the header size on,
the chunk type in the id's byte 11. Only TOC version 8 is accepted.

extract reads the version 8 TOC forward in bounded pieces: the 144-byte header, chunk ids, offsets and lengths (two 40-bit
big-endian values in the uncompressed space), perfect hash seeds and unhashed chunk indices (skipped), and the 12-byte
compression blocks (40-bit little-endian .ucas offset, 24-bit compressed and uncompressed sizes, 8-bit method index; 0 is
uncompressed). A chunk starts in block offset / block size at offset % block size and can span blocks or share one with
another chunk. Only single-partition, unencrypted containers whose shader blocks are all uncompressed are supported; the
.ucas is read once in increasing offset order. Files are named by kind and ordinal, written to a fresh sibling directory
and renamed to the output only when every chunk was copied. The output holds report.json (aggregate) and manifest.json
(per file: TOC entry, chunk id, size, SHA-256); neither is printed.

payloads re-hashes the files a manifest lists and parses each library chunk as an IoStore shader code archive (uint32
version, then int32-counted arrays: shader map hashes, shader hashes, group chunk ids, shader map entries, shader entries,
group entries, shader indices). The layout counts as valid only when every count, index and range is consistent and the
data ends with the last array. Group entries are matched to the extracted code chunks by chunk id and stored size. The
command does not decompress shader groups or interpret their bytes.

Each stdout line is a JSON object. Reports carry counts only: inputs are named by position, never by path, and no chunk
id, shader key, content hash or payload byte is printed. Exit codes: 0 when every input was read (and, for extract, the
output published), 1 when an input was rejected, 130 for an interrupted extraction.

A listed shader chunk is not a shader the cache can prepare: shader groups can be compressed, and their relation to the
NVN2 programs the runtime captures is not established. No command writes to a shader cache."""
import argparse, hashlib, json, os, re, shutil, stat, struct, sys, tempfile
from array import array

MAGIC = b'-==--==--==--==-'
TOC_VERSION = 8
HEADER_MIN = 28                      # the fields read here end at byte 28
HEADER_MAX = 1 << 16
ID_SIZE = 12
IDS_PER_READ = 1 << 14               # 192 KiB per read
SHADER_KINDS = {8: 'shader_code_library', 9: 'shader_code'}
DUMP_NAME = re.compile(r'([0-9a-f]{16})\.(ctl|code)')   # as nxs_live
CTL_SIZES = (0xe0, 0x880)
CODE_MAX = 1 << 24

TOC_HEADER = 144                     # the version 8 header
OFFLEN_SIZE = 10
BLOCK_ENTRY_SIZE = 12
FLAG_ENCRYPTED = 2
MAX_ENTRIES = 1 << 22
MAX_BLOCKS = 1 << 22
MAX_BLOCK_SIZE = 1 << 24
MAX_METHOD_NAME = 1 << 10
MAX_SELECTED = 1 << 16
MAX_CHUNK = 1 << 28
MAX_TOTAL = 1 << 32
PROGRESS_EVERY = 512
KIND_DIRS = {8: 'library', 9: 'code'}
DIR_KINDS = {v: k for k, v in KIND_DIRS.items()}
PAYLOAD_NAME = re.compile(r'(library|code)/([0-9]{6})\.bin')
MANIFEST, REPORT = 'manifest.json', 'report.json'
MANIFEST_FORMAT = 'nxs_iostore.extract'
MANIFEST_MAX = 1 << 26
LIBRARY_MAX = 1 << 25
ARCHIVE_VERSION_MAX = 16
HASH_SIZE = 20
READ_PIECE = 1 << 20


class Rejected(ValueError):
    category = 'rejected'


class Malformed(Rejected):
    category = 'malformed'


class Unsupported(Rejected):
    category = 'unsupported'


class OverLimit(Rejected):
    category = 'limit'


def emit(phase, **fields):
    print(json.dumps({'phase': phase, **fields}), flush=True)


def scan_toc(stream, size):
    """→ aggregate counts of one TOC; stream is a binary file positioned anywhere, size its length in bytes"""
    stream.seek(0)
    head = stream.read(HEADER_MIN)
    if len(head) < HEADER_MIN or head[:16] != MAGIC:
        raise Rejected('not an IoStore TOC')
    version = head[16]
    if version != TOC_VERSION:
        raise Rejected(f'TOC version {version}, supported {TOC_VERSION}')
    header_size, entries = struct.unpack_from('<II', head, 20)
    if not HEADER_MIN <= header_size <= HEADER_MAX:
        raise Rejected(f'header size {header_size} outside {HEADER_MIN}..{HEADER_MAX}')
    end = header_size + ID_SIZE * entries
    if end > size:
        raise Rejected(f'{entries} chunk ids need {end} bytes, the file has {size}')
    counts = {'entries': entries, 'shader_code_library': 0, 'shader_code': 0, 'other': 0}
    stream.seek(header_size)
    left = entries
    while left:
        n = min(left, IDS_PER_READ)
        block = stream.read(ID_SIZE * n)
        if len(block) != ID_SIZE * n:
            raise Rejected('chunk id table ended early')
        for kind in block[ID_SIZE - 1::ID_SIZE]:
            counts[SHADER_KINDS.get(kind, 'other')] += 1
        left -= n
    return counts


def inventory(paths):
    total = {'containers': 0, 'rejected': 0, 'entries': 0, 'shader_code_library': 0, 'shader_code': 0}
    for index, path in enumerate(paths, 1):
        try:
            if not path.lower().endswith('.utoc'):
                raise Rejected('expected a .utoc file')
            if not os.path.isfile(path):
                raise Rejected('not a readable file')
            with open(path, 'rb') as stream:
                counts = scan_toc(stream, os.fstat(stream.fileno()).st_size)
        except (Rejected, OSError) as error:
            # OSError text names the path; report its kind only.
            reason = str(error) if isinstance(error, Rejected) else type(error).__name__
            total['rejected'] += 1
            emit('container_error', container=index, reason=reason)
            continue
        total['containers'] += 1
        for k in ('entries', 'shader_code_library', 'shader_code'): total[k] += counts[k]
        emit('container', container=index, version=TOC_VERSION, **counts)
    emit('inventory', **total)
    return 1 if total['rejected'] else 0


def capture_digests(folder):
    """→ ({key: content digest} of the complete valid pairs, counts); the keys and digests stay in this process"""
    files = {}
    for entry in os.scandir(folder):
        match = DUMP_NAME.fullmatch(entry.name)
        if match and entry.is_file(follow_symlinks=False):
            key, ext = match.groups()
            files.setdefault(key, set()).add(ext)
    digests, counts = {}, {'discovered': len(files), 'paired': 0, 'incomplete': 0, 'invalid': 0}
    for key, extensions in files.items():
        if len(extensions) != 2:
            counts['incomplete'] += 1
            continue
        with open(os.path.join(folder, key + '.ctl'), 'rb') as f: ctl = f.read(CTL_SIZES[-1] + 1)
        with open(os.path.join(folder, key + '.code'), 'rb') as f: code = f.read(CODE_MAX + 1)
        if len(ctl) not in CTL_SIZES or not 0 < len(code) < CODE_MAX:
            counts['invalid'] += 1
            continue
        h = hashlib.sha256()
        for part in (ctl, code): h.update(len(part).to_bytes(4, 'little')); h.update(part)
        digests[key] = h.digest()
        counts['paired'] += 1
    return digests, counts


def coverage(dir_a, dir_b):
    sides = {}
    for label, folder in (('a', dir_a), ('b', dir_b)):
        if not os.path.isdir(folder):
            emit('capture_error', folder=label, reason='not a directory')
            return 1
        try:
            sides[label], counts = capture_digests(folder)
        except OSError as error:
            emit('capture_error', folder=label, reason=type(error).__name__)
            return 1
        emit('captures', folder=label, **counts)
    a, b = sides['a'], sides['b']
    shared = a.keys() & b.keys()
    same = sum(a[k] == b[k] for k in shared)
    emit('coverage', shared=len(shared), same_content=same, different_content=len(shared) - same,
         only_a=len(a) - len(shared), only_b=len(b) - len(shared))
    return 0


def read_exact(stream, n, what):
    data = stream.read(n)
    if len(data) != n:
        raise Malformed(f'{what} ended early')
    return data


def read_toc_plan(stream, size, max_bytes):
    """→ (layout, chunks, blocks) for the type 8/9 chunks of one version 8 TOC, read forward in bounded pieces.
    layout holds header aggregates, chunks [entry, kind, chunk id, offset, length] in entry order, blocks
    {block index: (.ucas offset, size)} for the uncompressed blocks those chunks use"""
    stream.seek(0)
    head = stream.read(TOC_HEADER)
    if len(head) <= 16 or head[:16] != MAGIC:
        raise Malformed('not an IoStore TOC')
    if head[16] != TOC_VERSION:
        raise Unsupported(f'TOC version {head[16]}, supported {TOC_VERSION}')
    if len(head) < TOC_HEADER:
        raise Malformed('TOC header ended early')
    (header_size, entries, nblocks, block_entry, nmethods, method_len,
     block_size, _directory, partitions) = struct.unpack_from('<9I', head, 20)
    flags = head[80]   # after the container id (56) and the encryption key guid (64)
    seeds, = struct.unpack_from('<I', head, 84)
    unhashed, = struct.unpack_from('<I', head, 96)
    if not TOC_HEADER <= header_size <= HEADER_MAX:
        raise Malformed(f'header size {header_size} outside {TOC_HEADER}..{HEADER_MAX}')
    if flags & FLAG_ENCRYPTED:
        raise Unsupported('encrypted container')
    if partitions != 1:
        raise Unsupported(f'{partitions} partitions, supported 1')
    if block_entry != BLOCK_ENTRY_SIZE:
        raise Unsupported(f'block entry size {block_entry}, supported {BLOCK_ENTRY_SIZE}')
    if not 0 < block_size <= MAX_BLOCK_SIZE:
        raise Malformed(f'block size {block_size} outside 1..{MAX_BLOCK_SIZE}')
    if nmethods > 255 or (nmethods and not 0 < method_len <= MAX_METHOD_NAME):
        raise Malformed('compression method table')
    for name, n, cap in (('entries', entries, MAX_ENTRIES), ('blocks', nblocks, MAX_BLOCKS),
                         ('hash seeds', seeds, MAX_ENTRIES), ('unhashed chunks', unhashed, MAX_ENTRIES)):
        if n > cap:
            raise OverLimit(f'{n} {name}, limit {cap}')
    blocks_at = header_size + (ID_SIZE + OFFLEN_SIZE) * entries + 4 * (seeds + unhashed)
    end = blocks_at + BLOCK_ENTRY_SIZE * nblocks + nmethods * method_len
    if end > size:
        raise Malformed(f'TOC tables need {end} bytes, the file has {size}')

    chunks = []
    stream.seek(header_size)
    for first in range(0, entries, IDS_PER_READ):
        n = min(IDS_PER_READ, entries - first)
        table = read_exact(stream, ID_SIZE * n, 'chunk id table')
        for i in range(n):
            if table[ID_SIZE * i + ID_SIZE - 1] in SHADER_KINDS:
                if len(chunks) == MAX_SELECTED:
                    raise OverLimit(f'more than {MAX_SELECTED} shader chunks')
                cid = table[ID_SIZE * i:ID_SIZE * (i + 1)]
                chunks.append([first + i, cid[-1], cid, 0, 0])
    k = 0
    for first in range(0, entries, IDS_PER_READ):   # the offset table follows the ids
        n = min(IDS_PER_READ, entries - first)
        table = read_exact(stream, OFFLEN_SIZE * n, 'offset table')
        while k < len(chunks) and chunks[k][0] < first + n:
            o = OFFLEN_SIZE * (chunks[k][0] - first)
            chunks[k][3] = int.from_bytes(table[o:o + 5], 'big')
            chunks[k][4] = int.from_bytes(table[o + 5:o + 10], 'big')
            k += 1

    total, needed = 0, set()
    for _entry, _kind, _cid, offset, length in chunks:
        if length > MAX_CHUNK:
            raise OverLimit(f'a shader chunk of {length} bytes, limit {MAX_CHUNK}')
        total += length
        if total > max_bytes:
            raise OverLimit(f'the shader chunks hold more than {max_bytes} bytes')
        if length:
            last = (offset + length - 1) // block_size
            if last >= nblocks:
                raise Malformed('a shader chunk lies outside the block table')
            needed.update(range(offset // block_size, last + 1))

    needed = sorted(needed)
    blocks, k = {}, 0
    stream.seek(blocks_at)
    for first in range(0, nblocks, IDS_PER_READ):
        if k == len(needed):
            break
        n = min(IDS_PER_READ, nblocks - first)
        table = read_exact(stream, BLOCK_ENTRY_SIZE * n, 'block table')
        while k < len(needed) and needed[k] < first + n:
            o = BLOCK_ENTRY_SIZE * (needed[k] - first)
            e = table[o:o + BLOCK_ENTRY_SIZE]
            offset = int.from_bytes(e[0:5], 'little')
            csize, usize, method = int.from_bytes(e[5:8], 'little'), int.from_bytes(e[8:11], 'little'), e[11]
            if method > nmethods:
                raise Malformed('a shader block names a method outside the method table')
            if method:
                raise Unsupported(f'a shader block uses compression method {method}; only uncompressed blocks are supported')
            if csize != usize or usize > block_size:
                raise Malformed('an uncompressed shader block has inconsistent sizes')
            blocks[needed[k]] = (offset, usize)
            k += 1
    layout = {'version': TOC_VERSION, 'header_size': header_size, 'entries': entries, 'block_entries': nblocks,
              'block_size': block_size, 'partitions': partitions, 'flags': flags, 'methods': nmethods,
              'hash_seeds': seeds, 'unhashed_chunks': unhashed}
    return layout, chunks, blocks


class ForwardReader:
    """reads .ucas blocks in increasing offset order and keeps the last one for chunks that share it"""

    def __init__(self, stream):
        self.stream, self.cursor, self.last, self.data = stream, 0, None, b''
        self.blocks_read = self.blocks_reused = self.bytes_read = 0

    def block(self, index, offset, size):
        if index == self.last:
            self.blocks_reused += 1
            return self.data
        if offset < self.cursor:
            raise Unsupported('shader blocks are not stored in forward order')
        if offset != self.cursor:
            self.stream.seek(offset)
        self.data = memoryview(read_exact(self.stream, size, '.ucas data'))
        self.last, self.cursor = index, offset + size
        self.blocks_read += 1
        self.bytes_read += size
        return self.data


def write_chunks(toc, toc_size, ucas, ucas_size, folder, max_bytes):
    """copies the type 8/9 chunks into folder, with manifest.json and report.json → the aggregate report"""
    layout, chunks, blocks = read_toc_plan(toc, toc_size, max_bytes)
    block_size = layout['block_size']
    for offset, size in blocks.values():
        if offset + size > ucas_size:
            raise Malformed('a shader block lies outside the .ucas file')
    names, ordinals = {}, {8: 0, 9: 0}
    for entry, kind, *_ in chunks:
        ordinals[kind] += 1
        names[entry] = f'{KIND_DIRS[kind]}/{ordinals[kind]:06d}.bin'
    emit('extract_plan', **layout, shader_code_library=ordinals[8], shader_code=ordinals[9],
         bytes=sum(c[4] for c in chunks), blocks_needed=len(blocks))
    for kind, n in ordinals.items():
        if n: os.mkdir(os.path.join(folder, KIND_DIRS[kind]))

    reader = ForwardReader(ucas)
    stats = {'library_bytes': 0, 'code_bytes': 0, 'empty_chunks': 0, 'multi_block_chunks': 0, 'partial_block_chunks': 0}
    files = {}
    order = sorted(chunks, key=lambda c: (c[3], c[0]))
    for done, (entry, kind, cid, offset, length) in enumerate(order, 1):
        h, pos, end, spans, partial = hashlib.sha256(), offset, offset + length, 0, False
        with open(os.path.join(folder, *names[entry].split('/')), 'xb') as f:
            while pos < end:
                index, inner = divmod(pos, block_size)
                block_offset, size = blocks[index]
                take = min(end - pos, block_size - inner)
                if inner + take > size:
                    raise Malformed('a shader chunk extends past its block data')
                partial |= inner != 0 or take != size
                piece = reader.block(index, block_offset, size)[inner:inner + take]
                f.write(piece)
                h.update(piece)
                pos += take
                spans += 1
        stats['library_bytes' if kind == 8 else 'code_bytes'] += length
        stats['empty_chunks'] += not length
        stats['multi_block_chunks'] += spans > 1
        stats['partial_block_chunks'] += partial
        files[entry] = {'file': names[entry], 'kind': SHADER_KINDS[kind], 'entry': entry, 'chunk_id': cid.hex(),
                        'bytes': length, 'sha256': h.hexdigest()}
        if done % PROGRESS_EVERY == 0:
            emit('extract_progress', chunks=done, total=len(order))

    report = {**layout, 'shader_code_library': ordinals[8], 'shader_code': ordinals[9], **stats,
              'blocks_read': reader.blocks_read, 'blocks_reused': reader.blocks_reused, 'ucas_bytes_read': reader.bytes_read}
    with open(os.path.join(folder, MANIFEST), 'x', encoding='utf-8') as f:
        json.dump({'format': MANIFEST_FORMAT, 'version': 1, 'chunks': [files[c[0]] for c in chunks]}, f, indent=1)
    with open(os.path.join(folder, REPORT), 'x', encoding='utf-8') as f:
        json.dump({'format': MANIFEST_FORMAT, 'version': 1, **report}, f, indent=1)
    return report


def extract(toc_path, ucas_path, out, max_bytes):
    def fail(error):
        # OSError text names the path; report its kind only.
        if isinstance(error, Rejected): emit('extract_error', category=error.category, reason=str(error))
        else: emit('extract_error', category='io', reason=type(error).__name__)
        return 1
    try:
        if not toc_path.lower().endswith('.utoc') or not ucas_path.lower().endswith('.ucas'):
            raise Rejected('expected a .utoc and a .ucas file')
        if not (os.path.isfile(toc_path) and os.path.isfile(ucas_path)):
            raise Rejected('not a readable file')
        if os.path.lexists(out):
            raise Rejected('the output directory already exists')
        parent = os.path.dirname(os.path.abspath(out))
        if not os.path.isdir(parent):
            raise Rejected('the output parent is not a directory')
    except (Rejected, OSError) as error:
        return fail(error)
    staging = None
    try:
        staging = tempfile.mkdtemp(prefix='.nxs_extract-', dir=parent)
        with open(toc_path, 'rb') as toc, open(ucas_path, 'rb') as ucas:
            report = write_chunks(toc, os.fstat(toc.fileno()).st_size, ucas, os.fstat(ucas.fileno()).st_size,
                                  staging, max_bytes)
        os.rename(staging, out)   # fails rather than replace an output that appeared meanwhile
        staging = None
    except (Rejected, OSError) as error:
        return fail(error)
    except KeyboardInterrupt:
        emit('extract_error', category='interrupted', reason='interrupted')
        return 130
    finally:
        if staging: shutil.rmtree(staging, ignore_errors=True)
    emit('extracted', **report)
    return 0


def load_manifest(folder):
    """→ [(file, kind, chunk id, size, sha256 hex)] of an extraction manifest, checked field by field"""
    with open(os.path.join(folder, MANIFEST), 'rb') as f: raw = f.read(MANIFEST_MAX + 1)
    if len(raw) > MANIFEST_MAX:
        raise OverLimit('manifest larger than the limit')
    try:
        doc = json.loads(raw)
    except ValueError:
        raise Malformed('manifest is not JSON') from None
    if not isinstance(doc, dict) or doc.get('format') != MANIFEST_FORMAT or doc.get('version') != 1:
        raise Unsupported('not an nxs_iostore extraction manifest')
    chunks = doc.get('chunks')
    if not isinstance(chunks, list) or len(chunks) > MAX_SELECTED:
        raise Malformed('manifest chunk list')
    entries, seen = [], set()
    for c in chunks:
        name = c.get('file') if isinstance(c, dict) else None
        match = PAYLOAD_NAME.fullmatch(name) if isinstance(name, str) else None
        if not match or name in seen:
            raise Malformed('manifest file name')
        seen.add(name)
        kind = DIR_KINDS[match.group(1)]
        cid, size, digest = c.get('chunk_id'), c.get('bytes'), c.get('sha256')
        if (c.get('kind') != SHADER_KINDS[kind] or not isinstance(cid, str) or not re.fullmatch(r'[0-9a-f]{24}', cid)
                or int(cid[-2:], 16) != kind or type(size) is not int or not 0 <= size <= MAX_CHUNK
                or not isinstance(digest, str) or not re.fullmatch(r'[0-9a-f]{64}', digest)):
            raise Malformed('manifest chunk fields')
        entries.append((name, kind, bytes.fromhex(cid), size, digest))
    return entries


def verify_payload(folder, name, size, digest, keep):
    """→ (matches, bytes when keep); the file must be a regular file of the listed size and digest"""
    path = os.path.join(folder, *name.split('/'))
    if not stat.S_ISREG(os.lstat(path).st_mode):
        return False, None
    h, kept, left = hashlib.sha256(), bytearray() if keep else None, size + 1
    with open(path, 'rb') as f:
        while left:
            piece = f.read(min(left, READ_PIECE))
            if not piece: break
            h.update(piece)
            if keep: kept += piece
            left -= len(piece)
    ok = left == 1 and h.hexdigest() == digest
    return ok, bytes(kept) if ok and keep else None


def parse_library(data):
    """→ (aggregate fields, [(group chunk id, compressed size)]) of one IoStore shader code archive; Malformed when any
    count, index or range is inconsistent or bytes follow the last array"""
    view, p = memoryview(data), 0

    def take(n, what):
        nonlocal p
        if n > len(view) - p:
            raise Malformed(f'{what} run past the end')
        p += n
        return view[p - n:p]

    def counted(size, what):
        n = int.from_bytes(take(4, what), 'little', signed=True)
        if n < 0 or n * size > len(view) - p:
            raise Malformed(f'{what} count outside the library')
        return n, take(n * size, what)

    version = int.from_bytes(take(4, 'archive version'), 'little')
    if not 1 <= version <= ARCHIVE_VERSION_MAX:
        raise Malformed(f'archive version outside 1..{ARCHIVE_VERSION_MAX}')
    maps, _ = counted(HASH_SIZE, 'shader map hashes')
    shaders, _ = counted(HASH_SIZE, 'shader hashes')
    groups, ids = counted(ID_SIZE, 'group chunk ids')
    n, map_entries = counted(8, 'shader map entries')
    if n != maps: raise Malformed('shader map entries do not match the shader map hashes')
    n, _ = counted(8, 'shader entries')
    if n != shaders: raise Malformed('shader entries do not match the shader hashes')
    n, group_entries = counted(16, 'group entries')
    if n != groups: raise Malformed('group entries do not match the group chunk ids')
    nindices, raw = counted(4, 'shader indices')
    if p != len(view):
        raise Malformed('bytes follow the shader indices')
    indices = array('I' if array('I').itemsize == 4 else 'L')
    indices.frombytes(raw)
    if sys.byteorder == 'big': indices.byteswap()
    if indices and max(indices) >= shaders:
        raise Malformed('a shader index names no shader')
    for start, num in struct.iter_unpack('<II', map_entries):
        if start + num > nindices: raise Malformed('a shader map lists indices outside the index table')
    stats = {'archive_version': version, 'shader_maps': maps, 'shaders': shaders, 'groups': groups,
             'shader_indices': nindices, 'groups_raw': 0, 'groups_compressed': 0, 'groups_oversized': 0,
             'empty_groups': 0, 'max_shaders_per_group': 0, 'group_uncompressed_bytes': 0, 'group_compressed_bytes': 0}
    refs = []
    for i, (start, num, usize, csize) in enumerate(struct.iter_unpack('<4I', group_entries)):
        if start + num > nindices: raise Malformed('a group lists indices outside the index table')
        cid = bytes(ids[ID_SIZE * i:ID_SIZE * (i + 1)])
        if cid[-1] != 9: raise Malformed('a group chunk id is not a shader code id')
        stats['groups_raw' if csize == usize else 'groups_compressed' if csize < usize else 'groups_oversized'] += 1
        stats['empty_groups'] += not num
        stats['max_shaders_per_group'] = max(stats['max_shaders_per_group'], num)
        stats['group_uncompressed_bytes'] += usize
        stats['group_compressed_bytes'] += csize
        refs.append((cid, csize))
    return stats, refs


def payloads(folder):
    if not os.path.isdir(folder):
        emit('payload_error', category='rejected', reason='not a directory')
        return 1
    files = {'library': 0, 'code': 0, 'verified': 0, 'mismatched': 0, 'missing': 0}
    code_sizes, libraries = {}, []
    try:
        for name, kind, cid, size, digest in load_manifest(folder):
            files[KIND_DIRS[kind]] += 1
            try:
                ok, data = verify_payload(folder, name, size, digest, kind == 8 and size <= LIBRARY_MAX)
            except FileNotFoundError:
                files['missing'] += 1
                continue
            if not ok:
                files['mismatched'] += 1
                continue
            files['verified'] += 1
            if kind == 9: code_sizes[cid] = size
            else: libraries.append(data)
    except (Rejected, OSError) as error:
        if isinstance(error, Rejected): emit('payload_error', category=error.category, reason=str(error))
        else: emit('payload_error', category='io', reason=type(error).__name__)
        return 1
    emit('payload_files', **files)

    groups = {'libraries': len(libraries), 'libraries_valid': 0, 'groups': 0, 'groups_found': 0, 'groups_missing': 0,
              'group_size_match': 0, 'group_size_mismatch': 0, 'code_chunks': len(code_sizes)}
    referenced = set()
    for position, data in enumerate(libraries, 1):
        if data is None:
            emit('library', library=position, layout='too_large')
            continue
        try:
            stats, refs = parse_library(data)
        except Malformed as error:
            emit('library', library=position, layout='invalid', reason=str(error))
            continue
        emit('library', library=position, layout='valid', **stats)
        groups['libraries_valid'] += 1
        for cid, csize in refs:
            groups['groups'] += 1
            if cid not in code_sizes:
                groups['groups_missing'] += 1
                continue
            referenced.add(cid)
            groups['groups_found'] += 1
            groups['group_size_match' if code_sizes[cid] == csize else 'group_size_mismatch'] += 1
    groups['code_chunks_unreferenced'] = len(code_sizes.keys() - referenced)
    emit('payloads', **groups)
    return 1 if files['mismatched'] or files['missing'] else 0


def byte_limit(text):
    n = int(text)
    if not 0 < n <= MAX_TOTAL:
        raise argparse.ArgumentTypeError(f'expected 1..{MAX_TOTAL}')
    return n


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    sub = p.add_subparsers(dest='command', required=True)
    s = sub.add_parser('inventory', help='count shader chunk ids in IoStore TOCs')
    s.add_argument('toc', nargs='+')
    s = sub.add_parser('coverage', help='compare two folders of NVN2 capture pairs')
    s.add_argument('dir_a')
    s.add_argument('dir_b')
    s = sub.add_parser('extract', help='copy the uncompressed shader chunks of one container into a new directory')
    s.add_argument('toc')
    s.add_argument('ucas')
    s.add_argument('out')
    s.add_argument('--max-bytes', type=byte_limit, default=MAX_TOTAL, help='limit on the total chunk bytes')
    s = sub.add_parser('payloads', help='verify an extraction and report its shader library layout')
    s.add_argument('folder')
    a = p.parse_args(argv)
    if a.command == 'inventory': return inventory(a.toc)
    if a.command == 'coverage': return coverage(a.dir_a, a.dir_b)
    if a.command == 'extract': return extract(a.toc, a.ucas, a.out, a.max_bytes)
    return payloads(a.folder)


if __name__ == '__main__':
    sys.exit(main())
