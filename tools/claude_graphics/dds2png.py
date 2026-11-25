"""Preview of a BC1/BC3 (DXT1/DXT5) .dds dump as PNG, one pixel per 4x4 block (the block's mean colour), stdlib only.
usage: python -I dds2png.py in.dds out.png"""
import struct, sys, zlib


def rgb565(c): return ((c >> 11 & 31) * 255 // 31, (c >> 5 & 63) * 255 // 63, (c & 31) * 255 // 31)


def main(src, dst):
    d = open(src, 'rb').read()
    assert d[:4] == b'DDS '
    h, w = struct.unpack_from('<II', d, 12)
    fourcc = d[84:88]
    bs = 8 if fourcc == b'DXT1' else 16
    off = 128 + (20 if fourcc == b'DX10' else 0)
    if fourcc == b'DX10':
        fmt = struct.unpack_from('<I', d, 128)[0]; bs = 8 if fmt in (70, 71, 72) else 16
    bw, bh = (w + 3) // 4, (h + 3) // 4
    rows = []
    for by in range(bh):
        row = bytearray([0])
        for bx in range(bw):
            p = off + (by * bw + bx) * bs + (bs - 8)
            c0, c1, idx = struct.unpack_from('<HHI', d, p)
            a, b = rgb565(c0), rgb565(c1)
            pal = [a, b, tuple((2 * x + y) // 3 for x, y in zip(a, b)), tuple((x + 2 * y) // 3 for x, y in zip(a, b))] if c0 > c1 or bs == 16 else \
                  [a, b, tuple((x + y) // 2 for x, y in zip(a, b)), (0, 0, 0)]
            s = [0, 0, 0]
            for i in range(16):
                q = pal[idx >> (2 * i) & 3]; s[0] += q[0]; s[1] += q[1]; s[2] += q[2]
            row += bytes(v // 16 for v in s)
        rows.append(bytes(row))
    def chunk(t, b): return struct.pack('>I', len(b)) + t + b + struct.pack('>I', zlib.crc32(t + b) & 0xffffffff)
    png = b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', struct.pack('>IIBBBBB', bw, bh, 8, 2, 0, 0, 0)) + chunk(b'IDAT', zlib.compress(b''.join(rows))) + chunk(b'IEND', b'')
    open(dst, 'wb').write(png)
    print(f'{src}: {w}x{h} {fourcc} -> {dst} {bw}x{bh}')


if __name__ == '__main__':
    main(sys.argv[1], sys.argv[2])
