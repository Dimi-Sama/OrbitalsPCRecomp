# SwitchRecomp - Copyright 2026 MZ Labs
import json, os, sys, tempfile, unittest
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'tools', 'nxshader'))
import nxs_prepare as P


def entry(vk, key, chain, val='ok'):
    open(os.path.join(vk, key + '.spv'), 'wb').write(b'\x03\x02\x23\x07')
    json.dump({'cache': {'chain': chain}, 'spirv_val': val}, open(os.path.join(vk, key + '.json'), 'w'))


class PrepareTests(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.TemporaryDirectory(); self.addCleanup(self.d.cleanup); self.root = self.d.name

    def test_stamp_follows_inputs(self):
        f = os.path.join(self.root, 'a.utoc'); open(f, 'wb').write(b'1')
        out = os.path.join(self.root, 'out'); os.makedirs(out)
        st = P.stamp_of(f, extra='x'); open(out + '.stamp', 'w').write(st)
        self.assertTrue(P.kept(out, P.stamp_of(f, extra='x')))
        open(f, 'ab').write(b'2')
        self.assertFalse(P.kept(out, P.stamp_of(f, extra='x')))

    def test_publish_drops_another_chain_and_keeps_captures(self):
        cache = os.path.join(self.root, 'cache'); vk = os.path.join(cache, 'vk'); os.makedirs(vk); os.makedirs(os.path.join(cache, 'dumps'))
        open(os.path.join(vk, 'CHAIN'), 'w').write('aaaaaaaaaaaaaaaa\n'); entry(vk, '0000000000000001', 'aaaaaaaaaaaaaaaa')
        open(os.path.join(cache, 'dumps', 'k.ctl'), 'wb').write(b'c')
        shard = os.path.join(self.root, 'shard'); svk = os.path.join(shard, 'vk'); os.makedirs(svk)
        entry(svk, '0000000000000002', 'bbbbbbbbbbbbbbbb'); entry(svk, '0000000000000003', 'bbbbbbbbbbbbbbbb', 'error: x')
        P.publish(cache, 'bbbbbbbbbbbbbbbb', [shard])
        self.assertEqual(sorted(P.current_keys(cache, 'bbbbbbbbbbbbbbbb')), ['0000000000000002', '0000000000000003'])
        self.assertFalse(os.path.exists(os.path.join(vk, '0000000000000001.json')))
        self.assertTrue(os.path.exists(os.path.join(cache, 'dumps', 'k.ctl')))
        self.assertEqual(P.summary(cache, 'bbbbbbbbbbbbbbbb'), (1, 1))

    def test_current_keys_needs_the_chain(self):
        cache = os.path.join(self.root, 'cache'); vk = os.path.join(cache, 'vk'); os.makedirs(vk)
        open(os.path.join(vk, 'CHAIN'), 'w').write('cccccccccccccccc\n')
        entry(vk, '0000000000000004', 'cccccccccccccccc'); entry(vk, '0000000000000005', 'dddddddddddddddd')
        self.assertEqual(P.current_keys(cache, 'cccccccccccccccc'), {'0000000000000004'})
        self.assertEqual(P.current_keys(cache, 'dddddddddddddddd'), set())


if __name__ == '__main__':
    unittest.main()
