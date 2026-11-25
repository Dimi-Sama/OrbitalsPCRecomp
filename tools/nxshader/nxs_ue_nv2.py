#!/usr/bin/env python3
# SwitchRecomp - Copyright 2026 MZ Labs
# Licensed under the GNU Affero General Public License v3.0, see LICENSE.txt and NOTICE.txt.
# Forks and derived works have to keep the credit to SwitchRecomp by MZ Labs and the startup screen.
"""nxs_ue_nv2: NVN2 capture pairs for nxs_live.py --offline from the shader groups an nxs_iostore.py extraction holds.

  nxs_ue_nv2.py EXTRACTION NEW_DIR --oodle LIBRARY [--keys FILE] [--max-bytes N]

EXTRACTION is a directory written by nxs_iostore.py extract. Every library and code chunk is re-hashed against its
manifest. Each library must be a version 1 IoStore shader code archive: seven int32-counted arrays after the version,
with strides 20, 20, 12, 8, 8, 16 and 4 (shader map hashes, shader hashes, group chunk ids, shader map entries, shader
entries, group entries, shader indices). A shader entry is a uint64: frequency in bits 0..3, group in bits 4..33 and the
byte offset in the decoded group from bit 34. A group entry holds its first index, index count and uint32 raw and stored
lengths. A group lists shaders through the index table; each listed shader must name that group and start inside its raw
length. The sorted distinct offsets split the group into records, the last ending at the raw length.

Groups are matched to code chunks by chunk id and stored length. A group whose stored length equals its raw length is
used as is; a shorter one is decoded by OodleLZ_Decompress from the shared library named by --oodle, which is loaded from
that path only and never located, downloaded or copied. The decoder must return exactly the raw length.

In a record, every 8-byte NVN2 marker (34 12 76 98 C9 00 00 00) starts a candidate control. Its uint32 at +0x30 is the
declared control size and at +0x44 the code length; the code ends 4 bytes before the control. A candidate is valid when
the declared control lies inside the record, the code starts inside it, nxs_live.verify_nvn2_dump accepts the first 0xE0
control bytes and the code under the runtime key, and nxs_live.stage_of names a stage. A record with no valid candidate
or more than one is rejected. Records that yield one key are duplicates when their code and their controls with the size
field zeroed agree; otherwise the key is conflicting and not published.

--keys selects the runtime keys to publish, one 16-digit hex key per line ('#' comments). The <key>.ctl (0xE0 bytes) and
<key>.code pairs and report.json are written to a fresh sibling directory renamed to NEW_DIR when complete.

Each stdout line is a JSON object with counts only: libraries are named by position, never by path, and no chunk id,
shader key, content hash or payload byte is printed. Exit codes: 0 when the output was published, 1 when an input was
rejected, 130 when interrupted. Rejected records and groups are counted and do not fail the run."""
import argparse, hashlib, json, os, re, shutil, struct, sys, tempfile
from collections import Counter

HERE = os.path.dirname(os.path.realpath(__file__))
sys.path.insert(0, HERE)
import nxs_iostore as S, nxs_live as L

ARCHIVE_VERSION = 1
STRIDES = (S.HASH_SIZE, S.HASH_SIZE, S.ID_SIZE, 8, 8, 16, 4)
FREQUENCY_MASK = 0xf
GROUP_SHIFT, GROUP_MASK = 4, (1 << 30) - 1
OFFSET_SHIFT = 34
GROUP_MAX = 1 << 26

MARKER = bytes.fromhex('34127698c9000000')
CTL_SIZE_AT, CODE_LEN_AT = 0x30, 0x44
CTL_HEAD = CODE_LEN_AT + 4
CTL_KEEP = 0xe0
CTL_DECLARED = (0xe0, 0x880)          # 224..424 observed in the validated archive
CODE_GAP = 4
TRAILING_OBSERVED = 22                # bytes after the declared control in every matched record so far

KEY = re.compile(r'[0-9a-f]{16}')
KEYS_MAX = 1 << 22
REPORT, REPORT_FORMAT = 'report.json', 'nxs_ue_nv2'

# OodleLZ_Decompress arguments after the four buffer arguments
FUZZ_SAFE, CHECK_CRC, VERBOSITY, THREAD_PHASE = 1, 0, 0, 3

GROUP_COUNTS = ('groups', 'empty', 'raw', 'decoded', 'missing', 'size_mismatch', 'oversized', 'layout_invalid',
                'over_limit', 'decode_failed', 'decoded_bytes')
RECORD_COUNTS = ('records', 'valid', 'no_marker', 'no_valid_candidate', 'ambiguous', 'in_failed_groups',
                 'trailing_22', 'trailing_other')


class GroupFailed(Exception):
    """a group none of whose records can be read; the message is its groups counter"""


class RecordFailed(Exception):
    """a record that yields no pair; the message is its records counter"""


def emit(phase, **fields):
    print(json.dumps({'phase': phase, **fields}), flush=True)


def histogram(counter):
    return {str(k): counter[k] for k in sorted(counter)}


def oodle_decoder(path):
    """→ decode(stored, raw length) through OodleLZ_Decompress of the shared library at path, which is made absolute so
    that no search path applies; the library is loaded from there only"""
    import ctypes
    path = os.path.abspath(path)
    if not os.path.isfile(path):
        raise S.Rejected('the Oodle library is not a readable file')
    try:
        lib = ctypes.CDLL(path)
    except OSError:
        raise S.Rejected('the Oodle library could not be loaded') from None
    try:
        fn = lib.OodleLZ_Decompress
    except AttributeError:
        raise S.Unsupported('the library does not export OodleLZ_Decompress') from None
    vp, size, i32 = ctypes.c_void_p, ctypes.c_ssize_t, ctypes.c_int
    fn.argtypes = (vp, size, vp, size, i32, i32, i32, vp, size, vp, vp, vp, size, i32)
    fn.restype = size

    def decode(stored, raw):
        if not stored or not 0 < raw <= GROUP_MAX:
            return None
        src = (ctypes.c_char * len(stored)).from_buffer_copy(stored)
        dst = (ctypes.c_char * raw)()
        n = fn(src, len(stored), dst, raw, FUZZ_SAFE, CHECK_CRC, VERBOSITY, None, 0, None, None, None, 0, THREAD_PHASE)
        return dst.raw if n == raw else None
    return decode


def load_keys(path):
    """→ the set of runtime keys a selection file lists"""
    with open(path, 'rb') as f: raw = f.read(KEYS_MAX + 1)
    if len(raw) > KEYS_MAX:
        raise S.OverLimit('the key file is larger than the limit')
    try:
        text = raw.decode('ascii')
    except UnicodeError:
        raise S.Malformed('the key file is not ASCII') from None
    keys = set()
    for line in text.splitlines():
        line = line.strip().lower()
        if not line or line.startswith('#'):
            continue
        if not KEY.fullmatch(line):
            raise S.Malformed('the key file holds a line that is not a 16-digit shader key')
        keys.add(line)
    return keys


def parse_archive(data):
    """→ (aggregate fields, groups [(chunk id, first, count, raw, stored)], shaders [(frequency, group, offset)], shader
    indices) of a version 1 archive; nxs_iostore.parse_library checks the counts and ranges first"""
    stats, _refs = S.parse_library(data)
    if stats['archive_version'] != ARCHIVE_VERSION:
        raise S.Unsupported(f"archive version {stats['archive_version']}, supported {ARCHIVE_VERSION}")
    arrays, p = [], 4
    for stride in STRIDES:
        n, = struct.unpack_from('<i', data, p)
        arrays.append(data[p + 4:p + 4 + n * stride])
        p += 4 + n * stride
    _maps, _hashes, ids, _map_entries, entries, table, indices = arrays
    shaders = [(e & FREQUENCY_MASK, e >> GROUP_SHIFT & GROUP_MASK, e >> OFFSET_SHIFT) for e, in struct.iter_unpack('<Q', entries)]
    groups = [(ids[S.ID_SIZE * i:S.ID_SIZE * (i + 1)], *g) for i, g in enumerate(struct.iter_unpack('<4I', table))]
    return stats, groups, shaders, [i for i, in struct.iter_unpack('<I', indices)]


def record_spans(group, first, count, raw, shaders, index):
    """→ [(start, end, frequency)] of the distinct shader offsets a group lists, in increasing order"""
    starts = {}
    for s in index[first:first + count]:
        frequency, owner, offset = shaders[s]
        if owner != group or offset >= raw:
            raise GroupFailed('layout_invalid')
        starts.setdefault(offset, frequency)
    order = sorted(starts)
    return [(o, end, starts[o]) for o, end in zip(order, order[1:] + [raw])]


def runtime_key(ctl, code):
    """the runtime's default NVN2 key, as nxs_live.verify_nvn2_dump checks it"""
    digest = hashlib.sha256(ctl[:0x30] + bytes(4) + ctl[0x34:0x48])
    digest.update(code)
    return digest.hexdigest()[:16]


def normalized(ctl):
    return ctl[:CTL_SIZE_AT] + bytes(4) + ctl[CTL_SIZE_AT + 4:]


def candidate(record, at):
    """→ (key, ctl, code, stage, declared control size, trailing bytes) for the marker at offset at, or why not"""
    if at + CTL_HEAD > len(record):
        return 'control_truncated'
    declared, = struct.unpack_from('<I', record, at + CTL_SIZE_AT)
    code_len, = struct.unpack_from('<I', record, at + CODE_LEN_AT)
    if not CTL_DECLARED[0] <= declared <= CTL_DECLARED[1]:
        return 'control_size'
    if at + declared > len(record):
        return 'control_truncated'
    start = at - CODE_GAP - code_len
    if not code_len or start < 0:
        return 'code_bounds'
    ctl, code = record[at:at + CTL_KEEP], record[start:at - CODE_GAP]
    key = runtime_key(ctl, code)
    try:
        L.verify_nvn2_dump(key, ctl, code)
    except ValueError:
        return 'nvn2_lengths'
    stage = L.stage_of(ctl, code)
    if not stage:
        return 'stage'
    return key, ctl, code, stage, declared, len(record) - at - declared


def record_pair(record, rejections):
    """→ the one valid candidate of a record; RecordFailed when there is none or more than one"""
    found, at = [], record.find(MARKER)
    if at < 0:
        raise RecordFailed('no_marker')
    while at >= 0:
        result = candidate(record, at)
        if isinstance(result, str): rejections[result] += 1
        else: found.append(result)
        at = record.find(MARKER, at + 1)
    if not found:
        raise RecordFailed('no_valid_candidate')
    if len(found) > 1:
        raise RecordFailed('ambiguous')
    return found[0]


def group_bytes(folder, chunk, raw, stored, decode, groups, max_bytes):
    """→ the raw bytes of one group from its verified code chunk"""
    if chunk is None:
        raise GroupFailed('missing')
    name, size, digest = chunk
    if size != stored:
        raise GroupFailed('size_mismatch')
    if stored > raw:
        raise GroupFailed('oversized')
    if raw > GROUP_MAX:
        raise GroupFailed('over_limit')
    if groups['decoded_bytes'] + raw > max_bytes:
        raise S.OverLimit(f'the groups hold more than {max_bytes} decoded bytes')
    ok, data = S.verify_payload(folder, name, size, digest, True)
    if not ok:
        raise S.Malformed('a code chunk does not match the manifest')
    if stored == raw:
        groups['raw'] += 1
        groups['decoded_bytes'] += raw
        return data
    out = decode(data, raw)
    if out is None or len(out) != raw:
        raise GroupFailed('decode_failed')
    groups['decoded'] += 1
    groups['decoded_bytes'] += raw
    return bytes(out)


def convert(folder, decode, max_bytes):
    """→ ({key: (ctl, code, stage, declared size)}, conflicting keys, report) of every library of an extraction"""
    files = S.load_manifest(folder)
    chunks = {cid: (name, size, digest) for name, kind, cid, size, digest in files if kind == 9}
    libraries = [(name, size, digest) for name, kind, _cid, size, digest in files if kind == 8]
    groups, records = dict.fromkeys(GROUP_COUNTS, 0), dict.fromkeys(RECORD_COUNTS, 0)
    rejections, stages, sizes, frequencies = Counter(), Counter(), Counter(), Counter()
    pairs, conflicting, duplicates = {}, set(), 0
    for position, (name, size, digest) in enumerate(libraries, 1):
        if size > S.LIBRARY_MAX:
            raise S.OverLimit('a library chunk is larger than the limit')
        ok, data = S.verify_payload(folder, name, size, digest, True)
        if not ok:
            raise S.Malformed('a library chunk does not match the manifest')
        stats, table, shaders, index = parse_archive(data)
        library_records = 0
        for g, (cid, first, count, raw, stored) in enumerate(table):
            groups['groups'] += 1
            if not count:
                groups['empty'] += 1
                continue
            spans = ()
            try:
                spans = record_spans(g, first, count, raw, shaders, index)
                group = group_bytes(folder, chunks.get(cid), raw, stored, decode, groups, max_bytes)
            except GroupFailed as failure:
                groups[str(failure)] += 1
                records['in_failed_groups'] += len(spans)
                continue
            finally:
                library_records += len(spans)
                records['records'] += len(spans)
            for start, end, frequency in spans:
                try:
                    key, ctl, code, stage, declared, trailing = record_pair(group[start:end], rejections)
                except RecordFailed as failure:
                    records[str(failure)] += 1
                    continue
                records['valid'] += 1
                records['trailing_22' if trailing == TRAILING_OBSERVED else 'trailing_other'] += 1
                stages[stage] += 1
                sizes[declared] += 1
                frequencies[frequency] += 1
                held = pairs.get(key)
                if held is None:
                    pairs[key] = (ctl, code, stage, declared)
                elif held[1] == code and normalized(held[0]) == normalized(ctl):
                    duplicates += 1
                else:
                    conflicting.add(key)
        emit('library', library=position, archive_version=stats['archive_version'], shader_maps=stats['shader_maps'],
             shaders=stats['shaders'], groups=stats['groups'], shader_indices=stats['shader_indices'],
             records=library_records)
    records.update(candidate_rejections=histogram(rejections), stages=histogram(stages),
                   control_sizes=histogram(sizes), frequencies=histogram(frequencies))
    keys = {'validated': len(pairs), 'duplicate_records': duplicates, 'conflicting': len(conflicting),
            'usable': len(pairs) - len(conflicting)}
    return pairs, conflicting, {'libraries': len(libraries), 'groups': groups, 'records': records, 'keys': keys}


def publish(pairs, chosen, out, report):
    """writes the chosen pairs and report.json to a fresh sibling directory and renames it to out"""
    staging = tempfile.mkdtemp(prefix='.nxs_ue_nv2-', dir=os.path.dirname(os.path.abspath(out)))
    try:
        for key in sorted(chosen):
            ctl, code = pairs[key][:2]
            with open(os.path.join(staging, key + '.ctl'), 'xb') as f: f.write(ctl)
            with open(os.path.join(staging, key + '.code'), 'xb') as f: f.write(code)
        with open(os.path.join(staging, REPORT), 'x', encoding='utf-8') as f:
            json.dump({'format': REPORT_FORMAT, 'version': 1, **report}, f, indent=1)
        os.rename(staging, out)   # fails rather than replace an output that appeared meanwhile
        staging = None
    finally:
        if staging: shutil.rmtree(staging, ignore_errors=True)


def run(folder, out, oodle, keys_path=None, max_bytes=S.MAX_TOTAL, decoder=oodle_decoder):
    try:
        if not os.path.isdir(folder):
            raise S.Rejected('the extraction is not a directory')
        if os.path.lexists(out):
            raise S.Rejected('the output directory already exists')
        if not os.path.isdir(os.path.dirname(os.path.abspath(out))):
            raise S.Rejected('the output parent is not a directory')
        selection = load_keys(keys_path) if keys_path else None
        decode = decoder(oodle)
        pairs, conflicting, report = convert(folder, decode, max_bytes)
        emit('groups', **report['groups'])
        emit('records', **report['records'])
        emit('keys', **report['keys'])
        chosen = pairs.keys() - conflicting
        if selection is not None:
            report['selection'] = {'requested': len(selection), 'selected': len(chosen & selection),
                                   'conflicting': len(conflicting & selection), 'absent': len(selection - pairs.keys())}
            chosen &= selection
            emit('selection', **report['selection'])
        report['published'] = {'pairs': len(chosen), 'stages': histogram(Counter(pairs[k][2] for k in chosen)),
                               'control_sizes': histogram(Counter(pairs[k][3] for k in chosen))}
        publish(pairs, chosen, out, report)
    except (S.Rejected, OSError) as error:
        # OSError text names the path; report its kind only.
        if isinstance(error, S.Rejected): emit('convert_error', category=error.category, reason=str(error))
        else: emit('convert_error', category='io', reason=type(error).__name__)
        return 1
    except KeyboardInterrupt:
        emit('convert_error', category='interrupted', reason='interrupted')
        return 130
    emit('published', **report['published'])
    return 0


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    p.add_argument('extraction', help='a directory written by nxs_iostore.py extract')
    p.add_argument('out', help='a new directory for the <key>.ctl and <key>.code pairs')
    p.add_argument('--oodle', required=True, help='the Oodle shared library that decodes compressed groups')
    p.add_argument('--keys', help='publish only the runtime keys this file lists, one per line')
    p.add_argument('--max-bytes', type=S.byte_limit, default=S.MAX_TOTAL, help='limit on the decoded group bytes')
    a = p.parse_args(argv)
    return run(a.extraction, a.out, a.oodle, a.keys, a.max_bytes)


if __name__ == '__main__':
    sys.exit(main())
