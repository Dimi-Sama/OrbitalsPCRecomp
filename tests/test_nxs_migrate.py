import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

TOOLS = Path(__file__).resolve().parents[1] / 'tools' / 'nxshader'
sys.path.insert(0, str(TOOLS))
import nxs_cache as C
import nxs_migrate as M

SAME, CHANGED = 'a' * 16, 'b' * 16


def write_cache(root, chain, modules):
    """a cache as a validated prewarm publishes it, from synthetic module bytes (no game assets)"""
    (root / 'vk').mkdir(parents=True)
    (root / 'LAYOUT').write_text(C.LAYOUT + '\n', newline='')
    (root / 'vk' / 'CHAIN').write_text(chain + '\n', newline='')
    for key, spv in modules.items():
        meta = {'key': key, 'spirv_val': 'ok', 'cache': {'chain': chain, 'spv_sha256': hashlib.sha256(spv).hexdigest()}}
        (root / 'vk' / f'{key}.spv').write_bytes(spv)
        (root / 'vk' / f'{key}.json').write_text(json.dumps(meta, indent=1), newline='')


def snapshot(root):
    return {p.relative_to(root): p.read_bytes() for p in root.rglob('*') if p.is_file()}


class MigrateTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.old, self.current, self.out = self.root / 'old', self.root / 'current', self.root / 'new'
        write_cache(self.old, 'old-chain', {SAME: b'\x03\x02\x23\x07same', CHANGED: b'\x03\x02\x23\x07before'})
        write_cache(self.current, 'new-chain', {SAME: b'\x03\x02\x23\x07same', CHANGED: b'\x03\x02\x23\x07after'})

    def test_unchanged_reused_changed_copied(self):
        before = snapshot(self.old), snapshot(self.current)
        result = M.migrate(self.old, self.current, self.out)
        self.assertEqual((result['modules'], result['reused'], result['copied'], result['chain']), (2, 1, 1, 'new-chain'))
        self.assertEqual((snapshot(self.old), snapshot(self.current)), before)
        self.assertEqual(snapshot(self.out), snapshot(self.current))
        for key in (SAME, CHANGED):
            spv, meta = C.Cache(self.out).lookup(key)
            self.assertEqual(spv, (self.current / 'vk' / f'{key}.spv').read_bytes())
            self.assertEqual(meta['cache']['chain'], 'new-chain')

    def test_corrupt_current_leaves_no_destination(self):
        vk = self.current / 'vk'
        corruptions = {
            'spv_sha256': lambda: (vk / f'{CHANGED}.spv').write_bytes(b'\x03\x02\x23\x07damaged'),
            'spirv_val': lambda: (vk / f'{CHANGED}.json').write_text(json.dumps(
                dict(json.loads((vk / f'{CHANGED}.json').read_text()), spirv_val='validation error'))),
            'metadata key': lambda: (vk / f'{CHANGED}.json').write_text(json.dumps(
                dict(json.loads((vk / f'{CHANGED}.json').read_text()), key=SAME))),
            'chain': lambda: (vk / 'CHAIN').write_text('other-chain\n'),
        }
        for problem, corrupt in corruptions.items():
            with self.subTest(problem):
                original = snapshot(self.current)
                corrupt()
                before = snapshot(self.old)
                with self.assertRaisesRegex(ValueError, problem if problem != 'chain' else 'CHAIN is'):
                    M.migrate(self.old, self.current, self.out)
                self.assertEqual(snapshot(self.old), before)
                self.assertEqual(sorted(p.name for p in self.root.iterdir()), ['current', 'old'])
                for path, data in original.items():
                    (self.current / path).write_bytes(data)

    def test_failed_publish_leaves_no_destination(self):
        with patch.object(C.Cache, 'set_chain', side_effect=OSError('disk full')), self.assertRaisesRegex(OSError, 'disk full'):
            M.migrate(self.old, self.current, self.out)
        self.assertEqual(sorted(p.name for p in self.root.iterdir()), ['current', 'old'])

    def test_existing_destination_is_refused(self):
        self.out.mkdir()
        with self.assertRaisesRegex(ValueError, 'exists'):
            M.migrate(self.old, self.current, self.out)
        self.assertEqual(list(self.out.iterdir()), [])


if __name__ == '__main__':
    unittest.main()
