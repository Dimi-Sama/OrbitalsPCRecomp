from types import SimpleNamespace
import unittest

import codegen


class OrbitalsDisplayDispatchTest(unittest.TestCase):
    def test_only_the_validated_parser_is_kept_in_dispatch(self):
        entry = codegen.ORBITALS_RES_PARSER
        words = {entry: 0xd503237f, entry + 4: 0xd10243ff}
        build_id = bytes.fromhex("0f8ef52cf4eee37628f366a539d5d6ad")
        settings_module = SimpleNamespace(name="main", base=0x8021000, text=(0, entry + 8),
                                          build_id=build_id, word=words.get)
        self.assertEqual(codegen.dynamic_call_targets([settings_module]), {settings_module.base + entry})
        settings_module.build_id = bytes(32)
        self.assertEqual(codegen.dynamic_call_targets([settings_module]), set())
        settings_module.build_id = build_id
        words[entry + 4] = 0xd503201f
        self.assertEqual(codegen.dynamic_call_targets([settings_module]), set())

    def test_known_calls_and_tail_branches_use_the_dispatch_table(self):
        start, entry = 0x1000, 0x3000
        caller = codegen.Func(start, [start, start + 4], None)
        callee = codegen.Func(entry, [entry], None)
        funcs = {start: caller, entry: callee}

        def decode(pc):
            return (0, ("bl" if pc == start else "b", entry))

        prog = SimpleNamespace(dyn_calls=set(), decode=decode)
        self.assertEqual(codegen.emit_function(prog, caller, funcs).count("F_3000(c,12288)"), 2)
        prog.dyn_calls.add(entry)
        output = codegen.emit_function(prog, caller, funcs)
        self.assertEqual(output.count("CALLDYN(12288)"), 2)
        self.assertNotIn("F_3000(c,12288)", output)
