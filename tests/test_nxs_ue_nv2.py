import contextlib
import ctypes
import hashlib
import io
import json
import os
from pathlib import Path
import struct
import sys
import tempfile
import types
import unittest
from unittest.mock import patch

TOOLS = Path(__file__).resolve().parents[1] / 'tools' / 'nxshader'
sys.path.insert(0, str(TOOLS))
import nxs_iostore as S
import nxs_live as L
import nxs_ue_nv2 as U

MARKER = bytes.fromhex('34127698c9000000')


def cid(index, kind):
    return index.to_bytes(4, 'little') + bytes(7) + bytes([kind])


def payload(n, seed):
    return bytes((seed * 7 + i) % 251 for i in range(n))


def program(seed, declared=0xf0, compute=True, code_len=64, lead=b'binding metadata', flip=None):
    """→ (record, runtime key, published control, code) of one synthetic NVN2 program as the groups store it"""
    code = bytearray(payload(code_len, seed))
    struct.pack_into('<I', code, 0, 1)                    # a vertex SPH word unless the control says compute
    ctl = bytearray(payload(declared, seed + 50))
    ctl[:8] = MARKER
    struct.pack_into('<I', ctl, 0x30, declared)
    struct.pack_into('<4I', ctl, 0x38, code_len - 8, 0, code_len, code_len)
    ctl[0x56] = 5 if compute else 0
    if flip is not None: ctl[flip] ^= 0xff
    key = hashlib.sha256(bytes(ctl[:0x30]) + bytes(4) + bytes(ctl[0x34:0x48]) + bytes(code)).hexdigest()[:16]
    record = lead + bytes(code) + b'\xee' * 4 + bytes(ctl) + payload(22, seed + 99)
    return record, key, bytes(ctl[:0xe0]), bytes(code)


def archive(groups, shaders, indices, version=1):
    """a version 1 shader code archive; groups (chunk id, first, count, raw, stored), shaders (frequency, group, offset)"""
    i32 = lambda n: struct.pack('<i', n)
    out = struct.pack('<I', version) + i32(1) + bytes(20) + i32(len(shaders)) + bytes(20 * len(shaders))
    out += i32(len(groups)) + b''.join(g[0] for g in groups)
    out += i32(1) + struct.pack('<II', 0, len(indices))
    out += i32(len(shaders)) + b''.join(struct.pack('<Q', f | g << 4 | o << 34) for f, g, o in shaders)
    out += i32(len(groups)) + b''.join(struct.pack('<4I', *g[1:]) for g in groups)
    return out + i32(len(indices)) + struct.pack(f'<{len(indices)}I', *indices)


class Codec:
    """stands in for Oodle: a stored group is a short token the decoder maps back to its raw bytes"""
    def __init__(self):
        self.table, self.calls = {}, 0

    def pack(self, raw, decoded=None):
        token = b'tok' + hashlib.sha256(raw).digest()[:5]
        self.table[token] = raw if decoded is None else decoded
        return token

    def decode(self, stored, n):
        self.calls += 1
        return self.table.get(bytes(stored))


def offsets(*records):
    out, at = [], 0
    for r in records:
        out.append(at)
        at += len(r)
    return out


class ConvertTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.folder, self.out = self.root / 'extraction', self.root / 'out'
        self.codec = Codec()

    def extraction(self, libraries, codes):
        """writes an nxs_iostore extraction: libraries are bytes, codes {chunk id: bytes}"""
        (self.folder / 'library').mkdir(parents=True)
        (self.folder / 'code').mkdir()
        chunks = []
        for kind, items in ((8, [(cid(100 + i, 8), d) for i, d in enumerate(libraries)]), (9, list(codes.items()))):
            for ordinal, (chunk_id, data) in enumerate(items, 1):
                name = f'{S.KIND_DIRS[kind]}/{ordinal:06d}.bin'
                (self.folder / name).write_bytes(data)
                chunks.append({'file': name, 'kind': S.SHADER_KINDS[kind], 'entry': len(chunks), 'chunk_id': chunk_id.hex(),
                               'bytes': len(data), 'sha256': hashlib.sha256(data).hexdigest()})
        (self.folder / 'manifest.json').write_text(json.dumps({'format': S.MANIFEST_FORMAT, 'version': 1, 'chunks': chunks}))

    def run_tool(self, keys=None, max_bytes=S.MAX_TOTAL):
        out = io.StringIO()
        keys_path = None
        if keys is not None:
            keys_path = self.root / 'Secret-keys.txt'
            keys_path.write_text(keys)
        with contextlib.redirect_stdout(out):
            code = U.run(str(self.folder), str(self.out), str(self.root / 'Secret-oodle.dll'), keys_path and str(keys_path),
                         max_bytes, decoder=lambda path: self.codec.decode)
        return code, {l['phase']: l for l in map(json.loads, out.getvalue().splitlines())}, out.getvalue()

    def fixture(self):
        """two libraries: compressed, missing, undecodable, empty and raw groups with valid, duplicate, conflicting,
        ambiguous and unreadable records"""
        a, b = program(1), program(2, compute=False)
        a2, b2 = program(1, declared=0x100), program(2, compute=False, flip=0x60)
        ambiguous = program(3)[0] + program(4)[0]
        unmarked, bad_control = payload(40, 9), b'meta' + MARKER + bytes(0x100)
        c = program(6, compute=False, lead=b'')
        g0, g1 = a[0] + b[0], a2[0] + b2[0] + ambiguous + unmarked + bad_control
        o0, o1 = offsets(a[0], b[0]), offsets(a2[0], b2[0], ambiguous, unmarked, bad_control)
        shaders = [(5, 0, o0[0]), (0, 0, o0[1]), (5, 0, o0[0])] + [(1, 1, o) for o in o1] + [(0, 2, 0), (0, 3, 0)]
        s0, s1 = self.codec.pack(g0), self.codec.pack(g1)
        s3 = self.codec.pack(payload(30, 7), decoded=payload(29, 7))
        groups = [(cid(1, 9), 0, 3, len(g0), len(s0)), (cid(2, 9), 3, 5, len(g1), len(s1)),
                  (cid(3, 9), 8, 1, 30, 5), (cid(4, 9), 9, 1, 30, len(s3)), (cid(5, 9), 10, 0, 0, 0)]
        first = archive(groups, shaders, list(range(10)))
        second = archive([(cid(6, 9), 0, 1, len(c[0]), len(c[0]))], [(0, 0, 0)], [0])
        self.extraction([first, second], {cid(1, 9): s0, cid(2, 9): s1, cid(4, 9): s3, cid(6, 9): c[0]})
        self.decoded_bytes = len(g0) + len(g1) + len(c[0])
        return a, b, c

    def test_converts_groups_into_verified_capture_pairs(self):
        a, b, c = self.fixture()
        code, lines, text = self.run_tool()
        self.assertEqual(code, 0)
        self.assertEqual(lines['library']['library'], 2)
        self.assertEqual(lines['groups'], {'phase': 'groups', 'groups': 6, 'empty': 1, 'raw': 1, 'decoded': 2, 'missing': 1,
                                           'size_mismatch': 0, 'oversized': 0, 'layout_invalid': 0, 'over_limit': 0,
                                           'decode_failed': 1, 'decoded_bytes': self.decoded_bytes})
        records = lines['records']
        self.assertEqual({k: records[k] for k in U.RECORD_COUNTS},
                         {'records': 10, 'valid': 5, 'no_marker': 1, 'no_valid_candidate': 1, 'ambiguous': 1,
                          'in_failed_groups': 2, 'trailing_22': 5, 'trailing_other': 0})
        self.assertEqual(records['stages'], {'cs': 2, 'vs': 3})
        self.assertEqual(records['control_sizes'], {'240': 4, '256': 1})
        self.assertEqual(records['frequencies'], {'0': 2, '1': 2, '5': 1})
        self.assertEqual(records['candidate_rejections'], {'control_size': 1})
        self.assertEqual(lines['keys'], {'phase': 'keys', 'validated': 3, 'duplicate_records': 1, 'conflicting': 1, 'usable': 2})
        self.assertEqual(lines['published'], {'phase': 'published', 'pairs': 2, 'stages': {'cs': 1, 'vs': 1},
                                              'control_sizes': {'240': 2}})
        self.assertNotIn('selection', lines)
        self.assertEqual(self.codec.calls, 3)
        names = sorted(p.name for p in self.out.iterdir())
        self.assertEqual(names, sorted([f'{a[1]}.ctl', f'{a[1]}.code', f'{c[1]}.ctl', f'{c[1]}.code', 'report.json']))
        for _record, key, ctl, code_area in (a, c):
            self.assertEqual((self.out / f'{key}.ctl').read_bytes(), ctl)
            self.assertEqual((self.out / f'{key}.code').read_bytes(), code_area)
            L.verify_nvn2_dump(key, ctl, code_area)
        report = json.loads((self.out / 'report.json').read_text())
        self.assertEqual((report['format'], report['keys']['usable'], report['published']['pairs']), ('nxs_ue_nv2', 2, 2))
        for leaked in ('Secret', str(self.root), a[1], b[1], c[1], cid(1, 9).hex(), a[3][:8].hex()):
            self.assertNotIn(leaked, text)
        self.assertNotIn(a[1], (self.out / 'report.json').read_text())

    def test_publishes_only_selected_keys(self):
        a, b, c = self.fixture()
        code, lines, text = self.run_tool(keys=f'# local selection\n{a[1].upper()}\n\n{b[1]}\n{"0" * 16}\n{a[1]}\n')
        self.assertEqual(code, 0)
        self.assertEqual(lines['selection'], {'phase': 'selection', 'requested': 3, 'selected': 1, 'conflicting': 1, 'absent': 1})
        self.assertEqual(lines['published']['pairs'], 1)
        self.assertEqual(sorted(p.name for p in self.out.iterdir()), [f'{a[1]}.code', f'{a[1]}.ctl', 'report.json'])
        self.assertNotIn(a[1], text)

    def test_rejects_groups_that_list_foreign_or_outside_shaders(self):
        a = program(1)
        for shaders in ([(0, 1, 0)], [(0, 0, len(a[0]))]):
            with self.subTest(shaders=shaders):
                self.setUp()
                token = self.codec.pack(a[0])
                groups = [(cid(1, 9), 0, 1, len(a[0]), len(token)), (cid(2, 9), 0, 0, 0, 0)]
                self.extraction([archive(groups, shaders, [0])], {cid(1, 9): token})
                code, lines, _ = self.run_tool()
                self.assertEqual((code, lines['groups']['layout_invalid'], lines['published']['pairs']), (0, 1, 0))
                self.assertEqual(self.codec.calls, 0)

    def test_counts_size_mismatch_oversized_and_group_limit(self):
        a = program(1)
        token = self.codec.pack(a[0])
        groups = [(cid(1, 9), 0, 1, len(a[0]), len(token) + 1), (cid(2, 9), 1, 1, 4, 8), (cid(3, 9), 2, 1, len(a[0]), len(token))]
        self.extraction([archive(groups, [(0, 0, 0), (0, 1, 0), (0, 2, 0)], [0, 1, 2])],
                        {cid(1, 9): token, cid(2, 9): bytes(8), cid(3, 9): token})
        with patch.object(U, 'GROUP_MAX', len(a[0]) - 1):
            code, lines, _ = self.run_tool()
        self.assertEqual(code, 0)
        self.assertEqual([lines['groups'][k] for k in ('size_mismatch', 'oversized', 'over_limit', 'decoded')], [1, 1, 1, 0])

    def assertRejected(self, category, **run):
        code, lines, text = self.run_tool(**run)
        self.assertEqual((code, lines['convert_error']['category']), (1, category))
        self.assertNotIn(str(self.root), text)
        self.assertFalse(self.out.exists())
        self.assertEqual([p.name for p in self.root.iterdir() if p.name.startswith('.nxs_ue_nv2-')], [])
        return lines['convert_error']

    def test_rejects_changed_chunks_versions_limits_and_selections(self):
        self.fixture()
        self.assertRejected('limit', max_bytes=100)
        self.assertRejected('malformed', keys='not a key\n')
        (self.folder / 'code' / '000002.bin').write_bytes(b'changed!')
        self.assertIn('code chunk', self.assertRejected('malformed')['reason'])
        self.setUp()
        self.extraction([archive([], [], [], version=2)], {})
        self.assertRejected('unsupported')

    def test_requires_a_fresh_output(self):
        self.fixture()
        self.out.mkdir()
        (self.out / 'keep.txt').write_text('mine')
        code, lines, _ = self.run_tool()
        self.assertEqual((code, lines['convert_error']['reason']), (1, 'the output directory already exists'))
        self.assertEqual([p.name for p in self.out.iterdir()], ['keep.txt'])


class OodleTests(unittest.TestCase):
    def test_calls_the_exact_decompress_signature(self):
        root = Path(self.enterContext(tempfile.TemporaryDirectory()))
        dll = root / 'oodle.dll'
        dll.write_bytes(b'')
        calls = []

        def decompress(*args):
            calls.append(args)
            ctypes.memmove(args[2], b'raw!', 4)
            return 4 if args[1] == 3 else -1
        lib = types.SimpleNamespace(OodleLZ_Decompress=decompress)
        with patch('ctypes.CDLL', return_value=lib) as load:
            decode = U.oodle_decoder(str(dll))
        load.assert_called_once_with(os.path.abspath(str(dll)))
        self.assertEqual(len(decompress.argtypes), 14)
        self.assertIs(decompress.restype, ctypes.c_ssize_t)
        self.assertEqual(decode(b'abc', 4), b'raw!')
        self.assertIsNone(decode(b'abcd', 4))
        self.assertIsNone(decode(b'', 4))
        self.assertEqual(len(calls), 2)
        self.assertEqual((calls[0][1], calls[0][3]), (3, 4))
        self.assertEqual(calls[0][4:], (1, 0, 0, None, 0, None, None, None, 0, 3))

    def test_never_searches_for_the_library(self):
        with patch('ctypes.CDLL') as load, self.assertRaises(S.Rejected):
            U.oodle_decoder('absent-decoder.dll')
        load.assert_not_called()


if __name__ == '__main__':
    unittest.main()
