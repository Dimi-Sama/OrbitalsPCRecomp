import struct
import unittest

from nxloader import Module


class RelativeRelocationTests(unittest.TestCase):
    def targets(self, entries, *, size=None, entry_size=8):
        image = bytearray(0x600)
        struct.pack_into('<I', image, 4, 0x40)
        image[0x40:0x44] = b'MOD0'
        struct.pack_into('<i', image, 0x44, 0x40)
        for i, item in enumerate(((36, 0x120), (35, size if size is not None else len(entries) * 8),
                                  (37, entry_size), (0, 0))):
            struct.pack_into('<qQ', image, 0x80 + 16 * i, *item)
        for i, entry in enumerate(entries):
            struct.pack_into('<Q', image, 0x120 + 8 * i, entry)
        for offset, target in ((0x200, 0x410), (0x208, 0x414), (0x210, 0x412),
                               (0x3f8, 0x454), (0x400, 0x458), (0x408, 0x41c),
                               (0x510, 0x428), (0x518, 0x464)):
            struct.pack_into('<Q', image, offset, target)
        return Module('fixture', bytes(image), (0x400, 0x60), (0, 0), (0, 0), 0).relptrs

    def test_reads_address_and_bitmaps_and_keeps_aligned_code_targets(self):
        entries = [0x200, 1 | (1 << 1) | (1 << 2) | (1 << 63), 7, 0x510, 3]
        self.assertEqual(self.targets(entries), {0x410, 0x414, 0x454, 0x458, 0x41c, 0x428})

    def test_malformed_or_unsupported_tables_leave_no_targets(self):
        for entries, size, stride in (([3, 0x200], None, 8), ([0x200], 7, 8),
                                      ([0x200], 0x600, 8), ([0x200], None, 4)):
            with self.subTest(entries=entries, size=size, stride=stride):
                self.assertEqual(self.targets(entries, size=size, entry_size=stride), set())

    def test_locations_outside_the_file_are_ignored(self):
        self.assertEqual(self.targets([0x5fa, 3, 0x200]), {0x410})


if __name__ == '__main__':
    unittest.main()
