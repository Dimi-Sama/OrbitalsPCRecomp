from pathlib import Path
import struct

def read_elf(path):
    with path.open('rb') as f:
        def get(offset, count):
            f.seek(offset)
            data = f.read(count)
            assert len(data) == count
            return data
        def name(strings, start):
            return strings[start:strings.index(b'\0', start)].decode()
        h = struct.unpack('<16sHHIQQQIHHHHHH', get(0, 64))
        assert h[0][:6] == b'\x7fELF\x02\x01' and h[2] == 62
        _, typ, _, _, _, phoff, shoff, _, _, phsize, phnum, shsize, shnum, names_idx = h
        phdrs = [struct.unpack('<IIQQQQQQ', get(phoff+i*phsize, 56)) for i in range(phnum)]
        shdrs = [struct.unpack('<IIQQQQIIQQ', get(shoff+i*shsize, 64)) for i in range(shnum)]
        names_hdr = shdrs[names_idx]
        names = get(names_hdr[4], names_hdr[5])
        sections = {name(names, sh[0]): sh for sh in shdrs if sh[0]}
        dynstr = sections['.dynstr']
        strings = get(dynstr[4], dynstr[5])
        dynamic = sections['.dynamic']
        needed = [name(strings, val) for tag, val in struct.iter_unpack('<qQ', get(dynamic[4], dynamic[5])) if tag == 1]
        dsyms = sections['.dynsym']
        exported = {name(strings, nm) for nm, info, other, idx, value, size in struct.iter_unpack('<IBBHQQ', get(dsyms[4], dsyms[5])) if idx and (info >> 4) != 0}
        undefined = {name(strings, nm) for nm, info, other, idx, value, size in struct.iter_unpack('<IBBHQQ', get(dsyms[4], dsyms[5])) if not idx and (info >> 4) == 1}
        interp = [get(ph[2], ph[5]).rstrip(b'\0').decode() for ph in phdrs if ph[0] == 3]
        stack = [ph[1] for ph in phdrs if ph[0] == 0x6474e551]
        assert stack and all(not flags & 1 for flags in stack)
        print(f"{path.name}: {path.stat().st_size} bytes, ELF type {typ}, interpreter {interp}, NEEDED {needed}, stack non-executable")
        return exported, undefined, needed, interp

root = Path('build/orbitals-linux')
runtime, _, deps, interp = read_elf(root / 'Orbitals')
assert interp == ['/lib64/ld-linux-x86-64.so.2'] and 'libX11.so.6' in deps
assert 'opus_decoder_create' in runtime
module, undefined, _, interp = read_elf(root / 'Orbitals_code.so')
assert 'swr_module' in module and not interp
assert not {s for s in undefined if s.startswith(('F_', 'plt_', 'swr_'))}, undefined
print("PASS ELF x86-64 and swr_module export")
