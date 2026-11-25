import hashlib
import json
import os
from pathlib import Path
import struct
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

TOOLS = Path(__file__).resolve().parents[1] / 'tools' / 'nxshader'
sys.path.insert(0, str(TOOLS))
import nxs_cache as C
import nxs_front as F
import nxs_live as L
import nxs_refl as R
import nxs_spv as S
import nxshader as N


def compute_capture():
    ctl = bytearray(0xe0)
    struct.pack_into('<II', ctl, 0, 0x98761234, 0xc9)
    struct.pack_into('<I4xII', ctl, 0x38, 16, 16, 16)
    ctl[0x56] = 5
    struct.pack_into('<3I', ctl, 0x58, 1, 1, 1)
    code = struct.pack('<QQ', 0x794d, 0)  # Ampere EXIT, see tests/sm86_mul/test.c.
    key = hashlib.sha256(ctl[:0x48] + code).hexdigest()[:16]
    struct.pack_into('<I', ctl, 0x30, len(ctl))
    return key, ctl, code


class TexelBufferSelectionTests(unittest.TestCase):
    def test_literal_widths_and_instruction_numbers_are_not_buffer_uses(self):
        words = [S.MAGIC, 0x00010600, 0, 100, 0,
                 4 << 16 | S.OpTypeInt, 1, 32, 0,
                 3 << 16 | S.OpTypeFloat, 2, 32,
                 6 << 16 | S.OpExtInst, 2, 3, 4, 32, 5,
                 6 << 16 | S.OpExtInst, 2, 6, 4, 1, 32]
        module = S.Module(struct.pack(f'<{len(words)}I', *words))
        self.assertEqual(list(S.Fetch1DTexelBuffer.value_uses(module, 32)), [3])

    def test_type_literals_are_not_uses(self):
        # %33 is a variable; 33 is also the R32ui format of an image type and the count word of a vector type: only id operands are uses
        words = [S.MAGIC, 0x00010600, 0, 100, 0,
                 4 << 16 | S.OpTypeInt, 1, 32, 0,
                 9 << 16 | 25, 44, 1, 5, 0, 0, 0, 2, 33,
                 4 << 16 | 32, 45, 0, 44,
                 4 << 16 | 23, 46, 1, 33,
                 4 << 16 | S.OpVariable, 45, 33, 0]
        module = S.Module(struct.pack(f'<{len(words)}I', *words))
        self.assertEqual(module.uses(33), [])
        self.assertEqual(module.uses(44), [2])
        self.assertEqual(module.uses(1), [1, 3])

    def test_workgroup_array_gets_an_undecorated_type(self):
        I = lambda op, *a: [(1 + len(a)) << 16 | op, *a]
        words = [S.MAGIC, 0x00010600, 0, 100, 0]
        ins = [I(S.OpDecorate, 4, 6, 4),                                   # %4 = uint[8] ArrayStride 4
               I(S.OpTypeInt, 1, 32, 0), I(S.OpConstant, 1, 2, 8), I(S.OpConstant, 1, 3, 0),
               I(S.OpTypeArray, 4, 1, 2), I(S.OpTypeStruct, 5, 4), I(S.OpTypePointer, 6, S.SC_StorageBuffer, 5),
               I(S.OpTypePointer, 7, S.SC_Workgroup, 4), I(S.OpTypePointer, 8, S.SC_Workgroup, 1),
               I(S.OpVariable, 6, 9, S.SC_StorageBuffer), I(S.OpVariable, 7, 10, S.SC_Workgroup),
               I(S.OpAccessChain, 8, 11, 10, 3)]
        for x in ins: words += x
        m = S.Module(struct.pack(f'<{len(words)}I', *words))
        self.assertTrue(S.WorkgroupLayout().applies(m, 'cs'))
        self.assertTrue(S.WorkgroupLayout().run(m, 'cs'))
        var = m.inst(10); ptr = m.inst(var[1]); arr = m.inst(ptr[3])
        self.assertNotEqual(arr[1], 4)
        self.assertEqual((ptr[2], arr[2], arr[3]), (S.SC_Workgroup, 1, 2))
        self.assertIsNone(m.deco(arr[1], 6))
        self.assertIsNotNone(m.deco(4, 6))
        self.assertLess(m.defs[arr[1]], m.defs[ptr[1]])
        self.assertLess(m.defs[ptr[1]], m.defs[10])

    def test_repeated_access_chain_is_the_same_coordinate_source(self):
        def instruction(op, *args):
            return [(1 + len(args)) << 16 | op, *args]

        def module(store_pointer):
            words = [S.MAGIC, 0x00010600, 0, 100, 0]
            words += instruction(S.OpVariable, 7, 8, S.SC_Function)
            words += instruction(S.OpVariable, 7, 11, S.SC_Function)
            words += instruction(S.OpAccessChain, 7, 1, 8, 9)
            words += instruction(S.OpAccessChain, 7, 2, 8, 9)
            words += instruction(S.OpAccessChain, 7, 3, 8, 10)
            words += instruction(S.OpLoad, 4, 5, 1)
            words += instruction(S.OpStore, store_pointer, 5)
            words += instruction(S.OpLoad, 4, 6, 2)
            words += instruction(S.OpLoad, 4, 12, 3)
            return S.Module(struct.pack(f'<{len(words)}I', *words))

        candidate = module(11)
        same = S.Fetch1DTexelBuffer.same_coordinate
        self.assertTrue(same(candidate, candidate.inst(5), candidate.inst(6)))
        self.assertFalse(same(candidate, candidate.inst(5), candidate.inst(12)))
        written = module(2)
        self.assertFalse(same(written, written.inst(5), written.inst(6)))

    def test_bindless_wrapped_fetches_in_known_one_dimensional_slots(self):
        variables = {1: 'cp_t_cb3_8', 2: 'cp_t_cb3_A', 3: 'cp_t_cb3_C', 4: 'cp_t_cb3_E'}
        module = SimpleNamespace(names=variables,
                                 global_vars=lambda: [(var, S.SC_UniformConstant, var) for var in variables])
        res = {'fetch1d': [0, 2], 'notes': [
            f'texture handle {handle} (constant buffer -1, slot {slot}) has no type in the answer table, using 2D'
            for handle, slot in (('8', 0), ('A', 1), ('C', 2), ('E', -1))
        ]}
        with patch.object(R, 'descriptor_of', return_value=('combined_image_sampler', 1, 1)), \
             patch.object(S.Fetch1DTexelBuffer, 'has_wrapped_fetches', side_effect=lambda _, var: var != 3):
            self.assertEqual(R.fetch1d_vars(module, 'cs', res), {1, 4})


class WrappedFetchIndexTests(unittest.TestCase):
    (UINT, INT, FLOAT, VEC4, UVEC2, IMAGE, SAMPLED, SAMPLED_PTR, TEXTURE, MASK, SHIFT, NARROW, TEMP_PTR, VOID, FUNCTION_TYPE,
     INPUT_PTR, INPUT, INT_INPUT_PTR, INT_INPUT, FUNCTION, ENTRY, TEMP, LOW, X, LO, HI, COORD) = range(1, 28)

    @staticmethod
    def instruction(op, *args):
        return [(1 + len(args)) << 16 | op, *args]

    def halves(self, lo_scalar, hi_scalar, mask=None, shift=S.Fetch1DTexelBuffer.OpShiftRightLogical):
        I = self.instruction
        return [I(S.Fetch1DTexelBuffer.OpBitwiseAnd, self.UINT, self.LO, lo_scalar, mask or self.MASK),
                I(shift, self.UINT, self.HI, hi_scalar, self.SHIFT),
                I(S.OpCompositeConstruct, self.UVEC2, self.COORD, self.LO, self.HI)]

    def fetch_index(self, body):
        """Run fetch1d_tbuf on a fragment function whose body defines COORD, and return the module and the coordinate of its fetch."""
        I, F = self.instruction, S.Fetch1DTexelBuffer
        program = [
            I(S.OpTypeInt, self.UINT, 32, 0), I(S.OpTypeInt, self.INT, 32, 1), I(S.OpTypeFloat, self.FLOAT, 32),
            I(S.OpTypeVector, self.VEC4, self.FLOAT, 4), I(S.OpTypeVector, self.UVEC2, self.UINT, 2),
            I(S.OpTypeImage, self.IMAGE, self.FLOAT, 1, 0, 0, 0, 1, 0), I(S.OpTypeSampledImage, self.SAMPLED, self.IMAGE),
            I(S.OpTypePointer, self.SAMPLED_PTR, S.SC_UniformConstant, self.SAMPLED), I(S.OpTypePointer, self.TEMP_PTR, S.SC_Function, self.UINT),
            I(S.OpTypePointer, self.INPUT_PTR, S.SC_Input, self.UINT), I(S.OpTypePointer, self.INT_INPUT_PTR, S.SC_Input, self.INT),
            I(S.OpTypeVoid, self.VOID), I(S.OpTypeFunction, self.FUNCTION_TYPE, self.VOID),
            I(S.OpConstant, self.UINT, self.MASK, 16383), I(S.OpConstant, self.UINT, self.SHIFT, 14), I(S.OpConstant, self.UINT, self.NARROW, 8191),
            I(S.OpVariable, self.SAMPLED_PTR, self.TEXTURE, S.SC_UniformConstant), I(S.OpVariable, self.INPUT_PTR, self.INPUT, S.SC_Input),
            I(S.OpVariable, self.INT_INPUT_PTR, self.INT_INPUT, S.SC_Input),
            I(S.OpFunction, self.VOID, self.FUNCTION, 0, self.FUNCTION_TYPE), I(S.OpLabel, self.ENTRY),
            I(S.OpVariable, self.TEMP_PTR, self.TEMP, S.SC_Function), I(S.OpVariable, self.TEMP_PTR, self.LOW, S.SC_Function),
            *body,
            I(S.OpLoad, self.SAMPLED, 28, self.TEXTURE), I(F.OpImage, self.IMAGE, 29, 28), I(F.OpImageFetch, self.VEC4, 30, 29, self.COORD),
            I(S.OpReturn), I(S.OpFunctionEnd)]
        words = [S.MAGIC, 0x00010600, 0, 100, 0] + [w for x in program for w in x]
        module = S.Module(struct.pack(f'<{len(words)}I', *words))
        module.fetch1d_vars = {self.TEXTURE}
        self.assertTrue(F().run(module, 'ps'))
        fetch = next(x for x in module.ins if x[0] & 0xffff == F.OpImageFetch)
        self.assertEqual(module.type_desc(module.inst(fetch[3])[1])['dim'], R.DIM_BUFFER)
        return module, fetch[4]

    def test_one_scalar_is_the_buffer_index(self):
        I, F = self.instruction, S.Fetch1DTexelBuffer
        module, index = self.fetch_index([I(S.OpLoad, self.UINT, self.X, self.INPUT), *self.halves(self.X, self.X)])
        self.assertEqual(index, self.X)
        self.assertFalse(module.has_op(F.OpShiftLeftLogical) or module.has_op(F.OpBitwiseOr))

    def test_scalar_through_block_temporaries_is_the_buffer_index(self):
        # The lowerer's form: the coordinate goes through a temporary and the low half through another.
        I, F = self.instruction, S.Fetch1DTexelBuffer
        module, index = self.fetch_index([
            I(S.OpLoad, self.UINT, self.X, self.INPUT), I(S.OpStore, self.TEMP, self.X),
            I(S.OpLoad, self.UINT, 40, self.TEMP), I(F.OpBitwiseAnd, self.UINT, self.LO, 40, self.MASK), I(S.OpStore, self.LOW, self.LO),
            I(S.OpLoad, self.UINT, 41, self.TEMP), I(F.OpShiftRightLogical, self.UINT, self.HI, 41, self.SHIFT),
            I(S.OpLoad, self.UINT, 42, self.LOW), I(S.OpCompositeConstruct, self.UVEC2, self.COORD, 42, self.HI)])
        self.assertEqual(index, self.X)
        self.assertFalse(module.has_op(F.OpShiftLeftLogical) or module.has_op(F.OpBitwiseOr))

    def test_other_coordinates_keep_the_rebuilt_index(self):
        I, F = self.instruction, S.Fetch1DTexelBuffer
        load = I(S.OpLoad, self.UINT, self.X, self.INPUT)
        stored = [load, I(S.OpStore, self.TEMP, self.X)]
        cases = {
            'repeated load': [load, I(S.OpLoad, self.UINT, 40, self.INPUT), *self.halves(self.X, 40)],
            'other mask': [load, *self.halves(self.X, self.X, mask=self.NARROW)],
            'arithmetic shift': [load, *self.halves(self.X, self.X, shift=195)],  # OpShiftRightArithmetic
            'signed scalar': [I(S.OpLoad, self.INT, self.X, self.INT_INPUT), *self.halves(self.X, self.X)],
            'temporary stored in another block': [*stored, I(S.LoopGuard.OpBranch, 43), I(S.OpLabel, 43),
                                                  I(S.OpLoad, self.UINT, 40, self.TEMP), *self.halves(40, self.X)],
            'temporary passed to a call': [*stored, I(F.OpFunctionCall, self.VOID, 44, 45, self.TEMP),
                                           I(S.OpLoad, self.UINT, 40, self.TEMP), *self.halves(40, self.X)],
        }
        for name, body in cases.items():
            with self.subTest(name):
                module, index = self.fetch_index(body)
                rebuilt = module.inst(index)
                self.assertEqual(rebuilt[0] & 0xffff, F.OpBitwiseOr)
                low, shifted = module.inst(rebuilt[3]), module.inst(rebuilt[4])
                self.assertEqual((low[0] & 0xffff, low[3:]), (S.OpCompositeExtract, [self.COORD, 0]))
                self.assertEqual(shifted[0] & 0xffff, F.OpShiftLeftLogical)


class ComputeJobTests(unittest.TestCase):
    @staticmethod
    def record(local=(128, 1, 1), shared=0):
        """An NVN2 compute record: the 0x38-byte header, 0x100 bytes of code, then the control section (magic, version 0xc9)"""
        ctl = bytearray(0x880)
        struct.pack_into('<II', ctl, 0, 0x98761234, 0xc9)
        struct.pack_into('<I', ctl, 0x38, 0x100)                     # instructions
        struct.pack_into('<II', ctl, 0x40, 0x100, 0x100)             # no c1 segment
        struct.pack_into('<3I', ctl, 0x58, *local)
        struct.pack_into('<I', ctl, 0x64, shared)
        return bytes(0x38) + bytes(0x100) + bytes(ctl)

    def job(self, rec):
        with tempfile.TemporaryDirectory() as w:
            return F.job_for('5c7fb5af900ce0bc', 'cs', rec, w, {})[0]

    def test_shared_memory_size_reaches_the_translator(self):
        # UE's radix sort upsweep: 8836 bytes; the translator's default (4096) cut its histogram at digit 7
        job = self.job(self.record(shared=8836))
        self.assertEqual(job['shared'], 8836)
        self.assertEqual(job['local'], [128, 1, 1])

    def test_no_shared_memory_keeps_the_translator_default(self):
        self.assertNotIn('shared', self.job(self.record(shared=0)))

    def test_shared_memory_size_is_rounded_to_words(self):
        self.assertEqual(self.job(self.record(shared=4962))['shared'], 4964)


class PrewarmTests(unittest.TestCase):
    def setUp(self):
        root = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.dump = root / 'captures'
        self.dump.mkdir()
        self.cache = root / 'cache'

    def offline(self, dotnet='dotnet', extra_dump=None):
        extra = ['--dump', str(extra_dump)] if extra_dump else []
        proc = subprocess.run([sys.executable, '-B', str(TOOLS / 'nxs_live.py'), '--offline',
                               '--dump', str(self.dump), *extra, '--cache', str(self.cache), '--dotnet', dotnet],
                              capture_output=True, text=True, timeout=30)
        self.assertTrue(proc.stdout, proc.stderr)
        return proc.returncode, [json.loads(line) for line in proc.stdout.splitlines()]

    def write_capture(self):
        key, ctl, code = compute_capture()
        (self.dump / f'{key}.ctl').write_bytes(ctl)
        (self.dump / f'{key}.code').write_bytes(code)
        return key

    def test_key_ignores_control_size_and_rejects_changed_code(self):
        key, ctl, code = compute_capture()
        L.verify_nvn2_dump(key, ctl, code)
        L.verify_nvn2_dump(key, ctl.ljust(0x880, b'\0'), code)
        with self.assertRaisesRegex(ValueError, 'lengths'):
            L.verify_nvn2_dump(key, ctl, code[:-1])
        with self.assertRaisesRegex(ValueError, 'shader key'):
            L.verify_nvn2_dump(key, ctl, code[:-1] + b'\x01')

    def test_incomplete_capture_is_reported_without_creating_cache(self):
        key, ctl, _ = compute_capture()
        (self.dump / f'{key}.ctl').write_bytes(ctl)
        code, report = self.offline()
        self.assertEqual(code, 2, report)
        self.assertIn({'phase': 'shader_error', 'key': key, 'status': 'incomplete capture'}, report)
        self.assertEqual(report[-1]['failed'], 1)
        self.assertFalse(self.cache.exists())

    def test_partial_captures_from_separate_folders_are_not_joined(self):
        other = self.dump.parent / 'other captures'
        other.mkdir()
        key, ctl, code = compute_capture()
        (self.dump / f'{key}.ctl').write_bytes(ctl)
        (other / f'{key}.code').write_bytes(code)
        status, report = self.offline(extra_dump=other)
        self.assertEqual(status, 2, report)
        self.assertEqual((report[-1]['discovered'], report[-1]['paired'], report[-1]['failed']), (1, 0, 1))
        self.assertFalse(self.cache.exists())

    def test_completed_duplicates_agree_on_translator_input(self):
        other = self.dump.parent / 'other captures'
        other.mkdir()
        key, ctl, code = compute_capture()
        self.write_capture()
        extended = ctl.ljust(0x880, b'\0')
        struct.pack_into('<I', extended, 0x30, len(extended))
        (other / f'{key}.ctl').write_bytes(extended)
        (other / f'{key}.code').write_bytes(code)
        corpus = L.DumpCorpus(None, verify_keys=True, paired_folders={key: [self.dump, other]})
        self.assertEqual(corpus.record(key), L.DumpCorpus(self.dump).record(key))
        extended[0x58] = 2
        (other / f'{key}.ctl').write_bytes(extended)
        with self.assertRaisesRegex(ValueError, 'conflicting completed capture pairs'):
            corpus.record(key)

    @unittest.skipUnless(os.environ.get('NXSHADER_TEST_DOTNET'), 'requires .NET 10 and SPIRV-Tools')
    def test_cold_warm_repair_and_chain_isolation(self):
        dotnet = os.environ['NXSHADER_TEST_DOTNET']
        key = self.write_capture()
        invalid = '0123456789abcdef'
        (self.dump / f'{invalid}.ctl').write_bytes((self.dump / f'{key}.ctl').read_bytes())
        (self.dump / f'{invalid}.code').write_bytes((self.dump / f'{key}.code').read_bytes())
        with C.prewarm_lock(self.cache):
            code, report = self.offline(dotnet)
            self.assertEqual(code, 1, report)
            self.assertIn('could not lock cache', report[-1]['error'])
        code, report = self.offline(dotnet)
        self.assertEqual(code, 2, report)
        self.assertEqual((report[-1]['prepared'], report[-1]['failed']), (1, 1))
        self.assertIn('shader key', next(event['error'] for event in report if event['phase'] == 'shader_error'))
        self.assertFalse((self.cache / 'vk' / f'{invalid}.spv').exists())
        (self.dump / f'{invalid}.ctl').unlink()
        (self.dump / f'{invalid}.code').unlink()
        cache = C.Cache(self.cache)
        offline_spv, offline_meta = cache.lookup(key)
        self.assertEqual(offline_meta['spirv_val'], 'ok')

        work = self.cache.parent / 'work'
        work.mkdir()
        live_cache = C.Cache(self.cache.parent / 'live')
        translator = F.Translator(TOOLS / 'xlate_bin', dotnet)
        live = N.Builder(L.DumpCorpus(self.dump), live_cache, translator, work, validate=False)
        self.assertEqual(live.make([key])[key]['status'], 'ok')
        live_spv, live_meta = live_cache.lookup(key, live.chain)
        self.assertEqual(offline_spv, live_spv)
        self.assertEqual(offline_meta['bindings'], live_meta['bindings'])

        module = self.cache / 'vk' / f'{key}.spv'
        written_at = module.stat().st_mtime_ns
        code, report = self.offline(dotnet)
        self.assertEqual(code, 0, report)
        self.assertEqual((report[-1]['prepared'], report[-1]['reused']), (0, 1))
        self.assertEqual(module.stat().st_mtime_ns, written_at)

        module.write_bytes(b'interrupted')
        d2 = offline_meta['cache']['d2']
        (self.cache / 'final' / d2[:2] / (d2 + '.spv.z')).write_bytes(b'damaged')
        code, report = self.offline(dotnet)
        self.assertEqual(code, 0, report)
        self.assertEqual(report[-1]['prepared'], 1)
        self.assertEqual(module.read_bytes(), offline_spv)

        cache.set_chain('other-chain')
        code, report = self.offline(dotnet)
        self.assertEqual(code, 1, report)
        self.assertIn('another shader chain', report[-1]['error'])
        self.assertEqual((self.cache / 'vk' / 'CHAIN').read_text().strip(), 'other-chain')
        self.assertEqual(module.read_bytes(), offline_spv)

    @unittest.skipUnless(os.environ.get('NXSHADER_TEST_DOTNET'), 'requires .NET 10 and SPIRV-Tools')
    def test_validation_failure_does_not_publish(self):
        key = self.write_capture()
        work = self.cache.parent / 'work'
        work.mkdir()
        translator = F.Translator(TOOLS / 'xlate_bin', os.environ['NXSHADER_TEST_DOTNET'])
        cache = C.Cache(self.cache)
        builder = N.Builder(L.DumpCorpus(self.dump), cache, translator, work, require_valid=True)
        with patch.object(N, 'spirv_val', return_value='validation error'):
            self.assertEqual(builder.make([key])[key]['status'], 'validation failed')
        self.assertFalse((self.cache / 'vk' / f'{key}.spv').exists())
        self.assertEqual(builder.make([key])[key]['status'], 'ok')


if __name__ == '__main__':
    unittest.main()
