import contextlib
import io
import json
from pathlib import Path
import struct
import sys
import tempfile
import unittest
from unittest.mock import patch

TOOLS = Path(__file__).resolve().parents[1] / 'tools' / 'nxshader'
sys.path.insert(0, str(TOOLS))
import nxs_iostore as S


def toc(kinds, version=8, header_size=144, entries=None, tail=b''):
    head = bytearray(header_size)
    head[:16] = S.MAGIC
    head[16] = version
    struct.pack_into('<II', head, 20, header_size, len(kinds) if entries is None else entries)
    ids = b''.join(bytes([i & 0xff] * 11 + [k]) for i, k in enumerate(kinds))
    return bytes(head) + ids + tail


class IoStoreTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(self.enterContext(tempfile.TemporaryDirectory()))

    def run_main(self, *argv):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = S.main(list(argv))
        return code, [json.loads(line) for line in out.getvalue().splitlines()], out.getvalue()

    def write(self, name, data):
        path = self.root / name
        path.write_bytes(data)
        return str(path)

    def test_counts_shader_kinds_without_ids_or_paths(self):
        path = self.write('Secret-Name.utoc', toc([8, 9, 9, 2, 0, 9], tail=b'payload'))
        code, lines, text = self.run_main('inventory', path)
        self.assertEqual(code, 0)
        self.assertEqual(lines[0], {'phase': 'container', 'container': 1, 'version': 8, 'entries': 6,
                                    'shader_code_library': 1, 'shader_code': 3, 'other': 2})
        self.assertEqual(lines[-1]['shader_code'], 3)
        for leaked in ('Secret', str(self.root), (b'\x01' * 11).hex(), 'payload'):
            self.assertNotIn(leaked, text)

    def test_reads_ids_in_bounded_blocks(self):
        reads = []

        class Recording(io.BytesIO):
            def read(self, n=-1):
                reads.append(n)
                return super().read(n)
        data = toc([9] * 50 + [8] * 7, tail=bytes(4096))
        with patch.object(S, 'IDS_PER_READ', 8):
            counts = S.scan_toc(Recording(data), len(data))
        self.assertEqual((counts['shader_code'], counts['shader_code_library'], counts['other']), (50, 7, 0))
        self.assertEqual(reads, [S.HEADER_MIN] + [8 * S.ID_SIZE] * 7 + [S.ID_SIZE])

    def test_rejects_unsupported_input(self):
        cases = {
            'magic.utoc': b'x' * 200,
            'version.utoc': toc([9], version=7),
            'small_header.utoc': toc([9], header_size=144)[:20] + struct.pack('<II', 16, 1) + bytes(200),
            'huge_header.utoc': toc([9])[:20] + struct.pack('<II', 1 << 20, 1) + bytes(200),
            'count.utoc': toc([9, 9], entries=1000),
            'short.utoc': toc([])[:10],
            'wrong.ucas': toc([9]),
        }
        paths = [self.write(n, d) for n, d in cases.items()] + [str(self.root / 'missing.utoc')]
        code, lines, text = self.run_main('inventory', *paths)
        self.assertEqual(code, 1)
        self.assertEqual([l['phase'] for l in lines], ['container_error'] * len(paths) + ['inventory'])
        self.assertEqual(lines[-1]['rejected'], len(paths))
        self.assertIn('version 7', lines[1]['reason'])
        self.assertNotIn(str(self.root), text)

    def capture(self, folder, key, ctl=bytes(0xe0), code=b'\x4d\x79' + bytes(14)):
        folder.mkdir(exist_ok=True)
        if ctl is not None: (folder / f'{key}.ctl').write_bytes(ctl)
        if code is not None: (folder / f'{key}.code').write_bytes(code)

    def test_coverage_reports_counts_only(self):
        a, b = self.root / 'a', self.root / 'b'
        keys = ['%016x' % (0xabc0 + i) for i in range(6)]
        self.capture(a, keys[0]); self.capture(b, keys[0])
        self.capture(a, keys[1]); self.capture(b, keys[1], code=b'\x01' * 16)
        self.capture(a, keys[2])
        self.capture(b, keys[3], ctl=bytes(0x880))
        self.capture(a, keys[4], code=None)
        self.capture(b, keys[5], ctl=bytes(0x10))
        code, lines, text = self.run_main('coverage', str(a), str(b))
        self.assertEqual(code, 0)
        self.assertEqual(lines[0], {'phase': 'captures', 'folder': 'a', 'discovered': 4, 'paired': 3, 'incomplete': 1, 'invalid': 0})
        self.assertEqual(lines[1], {'phase': 'captures', 'folder': 'b', 'discovered': 4, 'paired': 3, 'incomplete': 0, 'invalid': 1})
        self.assertEqual(lines[2], {'phase': 'coverage', 'shared': 2, 'same_content': 1, 'different_content': 1, 'only_a': 1, 'only_b': 1})
        for key in keys: self.assertNotIn(key, text)
        self.assertNotIn(str(self.root), text)

    def test_coverage_rejects_missing_folder(self):
        (self.root / 'a').mkdir()
        code, lines, _ = self.run_main('coverage', str(self.root / 'a'), str(self.root / 'nope'))
        self.assertEqual((code, lines[-1]), (1, {'phase': 'capture_error', 'folder': 'b', 'reason': 'not a directory'}))


def cid(index, kind):
    return index.to_bytes(4, 'little') + bytes(7) + bytes([kind])


def payload(n, seed):
    return bytes((seed * 7 + i) % 251 for i in range(n))


SEEDS = 3


def container(chunks, block=16, align=True, methods=(), method_of=None, flags=9, partitions=1, physical=None, header=()):
    """→ (.utoc, .ucas) of a synthetic version 8 container with uncompressed blocks unless method_of says otherwise"""
    logical, offsets = bytearray(), []
    for _kind, data in chunks:
        if align: logical += bytes(-len(logical) % block)
        offsets.append(len(logical))
        logical += data
    pieces = [bytes(logical[i:i + block]) for i in range(0, len(logical), block)]
    ucas, where = bytearray(), {}
    for b in (physical(len(pieces)) if physical else range(len(pieces))):
        where[b] = len(ucas)
        ucas += pieces[b]
    head = bytearray(144)
    head[:16] = S.MAGIC
    head[16] = 8
    struct.pack_into('<9I', head, 20, 144, len(chunks), len(pieces), 12, len(methods), 32, block, 0, partitions)
    head[80] = flags
    struct.pack_into('<I', head, 84, SEEDS)
    for offset, fmt, value in header: struct.pack_into(fmt, head, offset, value)
    toc = bytes(head) + b''.join(cid(i, k) for i, (k, _) in enumerate(chunks))
    toc += b''.join(o.to_bytes(5, 'big') + len(d).to_bytes(5, 'big') for o, (_, d) in zip(offsets, chunks))
    toc += bytes(4 * SEEDS)
    for b, piece in enumerate(pieces):
        toc += where[b].to_bytes(5, 'little') + len(piece).to_bytes(3, 'little') * 2 + bytes([method_of(b) if method_of else 0])
    toc += b''.join(name.ljust(32, b'\0') for name in methods)
    return toc + b'directory index', bytes(ucas)


def block_at(chunks, index):
    return 144 + 22 * chunks + 4 * SEEDS + 12 * index


def library(groups, shaders=4, version=1, tail=b''):
    """a serialized shader code archive; groups are (chunk id, first index, shaders, uncompressed, compressed)"""
    i32 = lambda n: struct.pack('<i', n)
    out = struct.pack('<I', version) + i32(1) + bytes(20) + i32(shaders) + bytes(20 * shaders)
    out += i32(len(groups)) + b''.join(g[0] for g in groups)
    out += i32(1) + struct.pack('<II', 0, shaders) + i32(shaders) + bytes(8 * shaders)
    out += i32(len(groups)) + b''.join(struct.pack('<4I', *g[1:]) for g in groups)
    return out + i32(shaders) + struct.pack(f'<{shaders}I', *range(shaders)) + tail


class ExtractTests(unittest.TestCase):
    run_main = IoStoreTests.run_main

    def setUp(self):
        self.root = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.out = self.root / 'out'

    def pair(self, toc, ucas, name='Secret-Name'):
        (self.root / f'{name}.utoc').write_bytes(toc)
        (self.root / f'{name}.ucas').write_bytes(ucas)
        return str(self.root / f'{name}.utoc'), str(self.root / f'{name}.ucas')

    def extract(self, toc, ucas, *extra):
        return self.run_main('extract', *self.pair(toc, ucas), str(self.out), *extra)

    def assertNothingPublished(self):
        self.assertFalse(self.out.exists())
        self.assertEqual([p.name for p in self.root.iterdir() if p.name.startswith('.nxs_extract-')], [])

    def test_extracts_partial_shared_and_multi_block_chunks(self):
        chunks = [(8, payload(10, 1)), (2, payload(20, 2)), (9, payload(40, 3)), (9, payload(5, 4)), (9, b''), (9, payload(16, 5))]
        code, lines, text = self.extract(*container(chunks, align=False))
        self.assertEqual(code, 0)
        self.assertEqual(lines[0]['phase'], 'extract_plan')
        self.assertEqual((lines[0]['shader_code_library'], lines[0]['shader_code'], lines[0]['bytes']), (1, 4, 71))
        report = lines[-1]
        self.assertEqual(report['phase'], 'extracted')
        expected = {'library_bytes': 10, 'code_bytes': 61, 'empty_chunks': 1, 'multi_block_chunks': 2,
                    'partial_block_chunks': 4, 'blocks_read': 6, 'blocks_reused': 2, 'ucas_bytes_read': 91}
        self.assertEqual({k: report[k] for k in expected}, expected)
        self.assertEqual((self.out / 'library' / '000001.bin').read_bytes(), chunks[0][1])
        for ordinal, entry in enumerate((2, 3, 4, 5), 1):
            self.assertEqual((self.out / 'code' / f'{ordinal:06d}.bin').read_bytes(), chunks[entry][1])
        manifest = json.loads((self.out / 'manifest.json').read_text())
        self.assertEqual([c['entry'] for c in manifest['chunks']], [0, 2, 3, 4, 5])
        self.assertEqual(manifest['chunks'][1]['chunk_id'], cid(2, 9).hex())
        self.assertEqual(json.loads((self.out / 'report.json').read_text())['blocks_reused'], 2)
        self.assertEqual(sorted(p.name for p in self.root.iterdir()), ['Secret-Name.ucas', 'Secret-Name.utoc', 'out'])
        for leaked in ('Secret', str(self.root), cid(2, 9).hex(), chunks[2][1][:8].hex(), manifest['chunks'][0]['sha256']):
            self.assertNotIn(leaked, text)

    def test_ignores_compressed_blocks_of_other_chunks(self):
        chunks = [(2, payload(40, 1)), (9, payload(20, 2))]
        toc, ucas = container(chunks, methods=(b'Oodle',), method_of=lambda b: 1 if b < 3 else 0)
        code, lines, _ = self.extract(toc, ucas)
        self.assertEqual((code, lines[-1]['shader_code']), (0, 1))
        self.assertEqual((self.out / 'code' / '000001.bin').read_bytes(), chunks[1][1])

    def check_rejected(self, cases, category):
        for name, (toc, ucas) in cases.items():
            with self.subTest(name):
                code, lines, text = self.extract(toc, ucas)
                self.assertEqual(code, 1)
                self.assertEqual((lines[-1]['phase'], lines[-1]['category']), ('extract_error', category))
                self.assertNotIn(str(self.root), text)
                self.assertNothingPublished()

    def test_rejects_unsupported_containers(self):
        chunks = [(9, payload(40, 1))]
        self.check_rejected({
            'encrypted': container(chunks, flags=10),
            'multipart': container(chunks, partitions=2),
            'compressed shader block': container(chunks, methods=(b'Oodle',), method_of=lambda b: 1),
            'backward blocks': container(chunks, physical=lambda n: reversed(range(n))),
            'version': container(chunks, header=[(16, '<B', 7)]),
        }, 'unsupported')

    def test_rejects_malformed_tables_and_eof(self):
        chunks = [(9, payload(40, 1))]
        toc, ucas = container(chunks)

        def patched(offset, value):
            data = bytearray(toc)
            data[offset:offset + len(value)] = value
            return bytes(data), ucas
        self.check_rejected({
            'not iostore': (b'x' * 200, ucas),
            'short header': (toc[:100], ucas),
            'header size': container(chunks, header=[(20, '<I', 100)]),
            'truncated toc': (toc[:block_at(1, 2) + 4], ucas),
            'truncated ucas': (toc, ucas[:-3]),
            'unknown method': container(chunks, methods=(b'Oodle',), method_of=lambda b: 2),
            'block sizes': patched(block_at(1, 0) + 5, (15).to_bytes(3, 'little')),
            'outside block table': patched(144 + 12, (1000).to_bytes(5, 'big')),
            'past block data': patched(block_at(1, 2) + 5, (4).to_bytes(3, 'little') * 2),
        }, 'malformed')

    def test_enforces_limits(self):
        self.check_rejected({'entries': container([(9, b'x')], header=[(24, '<I', 1 << 23)])}, 'limit')
        code, lines, _ = self.extract(*container([(9, payload(40, 1))]), '--max-bytes', '39')
        self.assertEqual((code, lines[-1]['category']), (1, 'limit'))
        self.assertNothingPublished()

    def test_requires_a_fresh_output_and_known_extensions(self):
        self.out.mkdir()
        (self.out / 'keep.txt').write_text('mine')
        code, lines, _ = self.extract(*container([(9, b'abc')]))
        self.assertEqual((code, lines[-1]['reason']), (1, 'the output directory already exists'))
        self.assertEqual([p.name for p in self.out.iterdir()], ['keep.txt'])
        toc, ucas = self.pair(*container([(9, b'abc')]))
        code, lines, _ = self.run_main('extract', ucas, toc, str(self.root / 'other'))
        self.assertEqual((code, lines[-1]['reason']), (1, 'expected a .utoc and a .ucas file'))

    def extract_library_fixture(self):
        groups = [(cid(1, 9), 0, 1, 30, 30), (cid(2, 9), 1, 2, 50, 20), (cid(7, 9), 3, 1, 9, 9)]
        chunks = [(8, library(groups)), (9, payload(30, 1)), (9, payload(21, 2)), (9, payload(7, 3)),
                  (8, library(groups, tail=b'x'))]
        code, _, _ = self.extract(*container(chunks, align=False))
        self.assertEqual(code, 0)

    def test_payloads_reports_library_layout_and_group_coverage(self):
        self.extract_library_fixture()
        code, lines, text = self.run_main('payloads', str(self.out))
        self.assertEqual(code, 0)
        self.assertEqual(lines[0], {'phase': 'payload_files', 'library': 2, 'code': 3, 'verified': 5, 'mismatched': 0, 'missing': 0})
        self.assertEqual(lines[1], {'phase': 'library', 'library': 1, 'layout': 'valid', 'archive_version': 1, 'shader_maps': 1,
                                    'shaders': 4, 'groups': 3, 'shader_indices': 4, 'groups_raw': 2, 'groups_compressed': 1,
                                    'groups_oversized': 0, 'empty_groups': 0, 'max_shaders_per_group': 2,
                                    'group_uncompressed_bytes': 89, 'group_compressed_bytes': 59})
        self.assertEqual(lines[2], {'phase': 'library', 'library': 2, 'layout': 'invalid', 'reason': 'bytes follow the shader indices'})
        self.assertEqual(lines[3], {'phase': 'payloads', 'libraries': 2, 'libraries_valid': 1, 'groups': 3, 'groups_found': 2,
                                    'groups_missing': 1, 'group_size_match': 1, 'group_size_mismatch': 1, 'code_chunks': 3,
                                    'code_chunks_unreferenced': 1})
        for leaked in (str(self.root), cid(1, 9).hex(), cid(7, 9).hex()):
            self.assertNotIn(leaked, text)

    def test_payloads_detects_changed_and_missing_files(self):
        self.extract_library_fixture()
        (self.out / 'code' / '000001.bin').write_bytes(b'changed')
        (self.out / 'code' / '000002.bin').unlink()
        code, lines, _ = self.run_main('payloads', str(self.out))
        self.assertEqual((code, lines[0]['verified'], lines[0]['mismatched'], lines[0]['missing']), (1, 3, 1, 1))
        manifest = json.loads((self.out / 'manifest.json').read_text())
        manifest['chunks'][0]['file'] = '../library/000001.bin'
        (self.out / 'manifest.json').write_text(json.dumps(manifest))
        code, lines, _ = self.run_main('payloads', str(self.out))
        self.assertEqual((code, lines[-1]['phase'], lines[-1]['category']), (1, 'payload_error', 'malformed'))

    def test_library_parser_rejects_inconsistent_layouts(self):
        good = [(cid(1, 9), 0, 4, 8, 8)]
        S.parse_library(library(good))
        cases = {
            'version': library(good, version=0),
            'truncated': library(good)[:-2],
            'index': library([(cid(1, 9), 2, 4, 8, 8)]),
            'kind': library([(cid(1, 2), 0, 4, 8, 8)]),
            'count': library(good)[:4] + struct.pack('<i', -1) + library(good)[8:],
        }
        for name, data in cases.items():
            with self.subTest(name), self.assertRaises(S.Malformed):
                S.parse_library(data)


if __name__ == '__main__':
    unittest.main()
