#!/usr/bin/env python3
"""ucas_map.py <container.utoc> [log ...] : maps the .ucas reads the runtime logs with SWR_TRACE_UCAS ("ucas read ... off X size Y") to the
IoStore chunks and, when the container has a directory index, to their file names. Reads the game's .utoc only (local, nothing written).

  ucas_map.py Orbitals-Switch2.utoc Orbitals.log            reads in the log -> files
  ucas_map.py Orbitals-Switch2.utoc --find Movies/          files whose path contains the text

IoStore TOC (UE5): 144-byte header, chunk ids (12 B), offset+length (10 B, two 40-bit big-endian values in the uncompressed space),
perfect hash seeds, chunks without perfect hash, compression blocks (12 B: 40-bit LE offset in the .ucas, 24-bit compressed size,
24-bit uncompressed size, 8-bit method), method names (32 B each), then the directory index (mount point, directories, files, strings)."""
import bisect, re, struct, sys


def u40be(b): return int.from_bytes(b, 'big')


class Toc:
    def __init__(self, path):
        d = open(path, 'rb').read()
        if d[:16] != b'-==--==--==--==-': raise ValueError('not an IoStore TOC')
        self.version = d[16]
        (hsize, n, nblk, blksz, nmeth, methlen, cblock, dirsize, nparts) = struct.unpack_from('<9I', d, 20)
        flags = d[80]   # after the container id (56) and the encryption key guid (64): 1 compressed, 2 encrypted, 4 signed, 8 indexed
        nseeds = struct.unpack_from('<I', d, 84)[0]
        nnoph = struct.unpack_from('<I', d, 96)[0]
        o = hsize
        self.ids = [d[o + 12 * i:o + 12 * i + 12] for i in range(n)]; o += 12 * n
        self.offs = []; self.lens = []
        for i in range(n):
            self.offs.append(u40be(d[o:o + 5])); self.lens.append(u40be(d[o + 5:o + 10])); o += 10
        o += 4 * nseeds
        if self.version >= 5: o += 4 * nnoph
        self.blocks = []
        for i in range(nblk):
            b = d[o:o + 12]; o += blksz
            off = int.from_bytes(b[0:5], 'little'); csz = int.from_bytes(b[5:8], 'little'); usz = int.from_bytes(b[8:11], 'little')
            self.blocks.append((off, csz, usz, b[11]))
        self.methods = [d[o + methlen * i:o + methlen * (i + 1)].rstrip(b'\0').decode() for i in range(nmeth)]; o += methlen * nmeth
        if flags & 4:   # signed: hash size, toc and block signatures, block hashes
            hs = struct.unpack_from('<i', d, o)[0]; o += 4 + 2 * hs + 20 * nblk
        self.cblock = cblock; self.flags = flags
        self.block_offs = [b[0] for b in self.blocks]
        self.names = {}
        if dirsize and not (flags & 2):   # not encrypted
            try: self._dir(d[o:o + dirsize])
            except Exception as e: print('directory index not read:', e)
        order = sorted(range(n), key=lambda i: self.offs[i])
        self.sorted_offs = [self.offs[i] for i in order]; self.sorted_idx = order

    def _dir(self, b):
        p = [0]
        def i32():
            v = struct.unpack_from('<i', b, p[0])[0]; p[0] += 4; return v
        def fstr():
            k = i32()
            if k == 0: return ''
            if k < 0: s = b[p[0]:p[0] - 2 * k].decode('utf-16-le'); p[0] += -2 * k
            else: s = b[p[0]:p[0] + k].decode('latin-1'); p[0] += k
            return s.rstrip('\0')
        mount = fstr()
        dirs = [struct.unpack_from('<4I', b, p[0] + 16 * j) for j in range(i32())]; p[0] += 16 * len(dirs)
        files = [struct.unpack_from('<3I', b, p[0] + 12 * j) for j in range(i32())]; p[0] += 12 * len(files)
        strs = [fstr() for _ in range(i32())]
        NONE = 0xFFFFFFFF
        def walk(di, path):
            name, child, sib, f = dirs[di]
            here = path + (strs[name] + '/' if name != NONE else '')
            while f != NONE:
                fn, nxt, toc = files[f]; self.names[toc] = mount + here + strs[fn]; f = nxt
            c = child
            while c != NONE: walk(c, here); c = dirs[c][2]
        if dirs: walk(0, '')

    def at(self, ucas_off):
        """the chunk (index) whose data the .ucas offset belongs to"""
        bi = bisect.bisect_right(self.block_offs, ucas_off) - 1
        if bi < 0: return None
        unc = bi * self.cblock
        k = bisect.bisect_right(self.sorted_offs, unc) - 1
        if k < 0: return None
        i = self.sorted_idx[k]
        return i if unc < self.offs[i] + self.lens[i] else None

    def label(self, i):
        cid = self.ids[i]
        return '%s (chunk %s type %d, %d KB)' % (self.names.get(i, '?'), cid[:8].hex(), cid[11], self.lens[i] // 1024)


def main():
    t = Toc(sys.argv[1])
    print('%s: version %d, %d chunks, %d blocks of %d KB, methods %s, %d names' % (sys.argv[1], t.version, len(t.ids), len(t.blocks), t.cblock // 1024, t.methods, len(t.names)))
    if len(sys.argv) > 3 and sys.argv[2] == '--find':
        for i, nm in sorted(t.names.items(), key=lambda x: x[1]):
            if sys.argv[3] in nm: print('  ', t.label(i))
        return
    for lp in sys.argv[2:]:
        last = None
        for l in open(lp, encoding='utf-8', errors='replace'):
            m = re.search(r'\[\s*([\d.]+)\] ucas read (\S+) off (0x[0-9a-f]+) size (0x[0-9a-f]+)', l)
            if not m: continue
            i = t.at(int(m.group(3), 16))
            if i is None: print('%s  off %s: no chunk' % (m.group(1), m.group(3))); continue
            if i != last: print('%8s  %s' % (m.group(1), t.label(i))); last = i


if __name__ == '__main__':
    main()
