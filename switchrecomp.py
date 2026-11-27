#!/usr/bin/env python3
# SwitchRecomp - Copyright 2026 MZ Labs
# Licensed under the GNU Affero General Public License v3.0, see LICENSE.txt and NOTICE.txt.
# Forks and derived works have to keep the credit to SwitchRecomp by MZ Labs and the startup screen.
"""
SwitchRecomp: static recompiler for Switch games, AArch64 -> C -> native.

The game code is translated to C ahead of time (plus a fallback interpreter built from the same
instruction templates). The runtime provides HLE kernel/services and a GL renderer for the GPU.

Usage:
  python switchrecomp.py GAME_FOLDER                   (with exefs/ and romfs/ from hactool)
  python switchrecomp.py game.nro                      (homebrew)
  python switchrecomp.py FOLDER -o Game --cc gcc -O 2 --jobs 8

Output (next to the executable):
  Game.exe             runtime (Windows) or Game (Linux)
  Game_code.dll/.so    the game code already translated to native
  Game_data/           exefs + romfs + save data
  Game.ini             options

LEGAL: does not include or download games, keys or firmware. Use your own copy.
"""
import argparse, os, sys, shlex, shutil, subprocess, time, hashlib, filecmp, re, struct, tempfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import nxloader, codegen, module_build

RT = os.path.join(HERE, 'runtime')
DEFAULT_CHUNK = 30000
DEFAULT_OPT = '2'
RUNTIME_SRC = ['plat', 'mem', 'kernel', 'ipc', 'svc_core', 'audio', 'svc_hid', 'svc_fs', 'svc_vi', 'nvdrv', 'svc_ns2', 'sm86', 'gpu', 'gpu_engines',
               'gpu_3d', 'loader', 'main', 'nvn_hook', 'nvn_glue', 'orbitals_settings', 'orbitals_input', 'orbitals_buttons']
# portable compilers next to us: tcc\, the GCC package (gcc\), w64devkit
CC_DIRS = [os.path.join(HERE, *d) for d in (('tcc',), ('tools', 'tcc'), ('gcc', 'bin'), ('gcc', 'Library', 'bin'),
                                             ('w64devkit', 'bin'))]



def replace_retry(tmp, dst):
    """os.replace that waits out Windows locks: antivirus or the search indexer often hold a file
    that was just written for a moment, and a rename then fails with WinError 32"""
    import time
    for k in range(40):
        try:
            os.replace(tmp, dst); return
        except PermissionError:
            if k == 39: raise
            time.sleep(0.25 * (1 + k // 8))

def find_cc(pref=None, target_win=False):
    exe = '.exe' if sys.platform.startswith('win') else ''

    def look(c):
        p = shutil.which(c) or (c if os.path.isfile(c) else None)
        for d in CC_DIRS:
            if p: break
            q = os.path.join(d, c + exe)
            if os.path.isfile(q): p = q
        return p
    if pref:
        # an explicit --cc must not silently turn into another compiler
        return look(pref)
    if target_win:
        # windows: prefer the bundled tcc\, builds in seconds
        cands = (['tcc'] if exe else []) + ['x86_64-w64-mingw32-gcc', 'gcc', 'clang', 'tcc']
    else:
        cands = ['gcc', 'clang', 'cc', 'tcc']
    for c in cands:
        p = look(c)
        if p: return p
    return None


def is_tcc(cc): return 'tcc' in os.path.basename(cc).lower()


def tcc_b(cc):
    # bundled tcc keeps include\ and lib\ next to the exe
    d = os.path.dirname(os.path.abspath(cc))
    return ['-B', d] if os.path.isdir(os.path.join(d, 'include')) else []


def cc_env(cc):
    # a portable gcc runs cc1/as/ld from its own folder and needs its DLLs on PATH
    d = os.path.dirname(os.path.abspath(cc))
    return dict(os.environ, PATH=d + os.pathsep + os.environ.get('PATH', ''))


def run_cc(cmd, cc, **kw):
    # compilers print in the console code page: never let a decode error hide the real message
    r = subprocess.run(cmd, capture_output=True, text=True, errors='replace', env=cc_env(cc), **kw)
    return (r.stderr or r.stdout or 'exit code %d' % r.returncode) if r.returncode else None


# ======================================================================= codegen
def write_if_changed(p, text):
    # don't touch unchanged files so make-style reuse of the .o works
    try:
        with open(p, 'r', encoding='utf-8') as fi:
            if fi.read() == text: return False
    except (OSError, UnicodeDecodeError):
        pass
    with open(p, 'w', encoding='utf-8') as fo: fo.write(text)
    return True


def gen_module(prog, mods, npdm, outdir, title, chunk_instrs, say):
    funcs = prog.funcs
    order = sorted(funcs)
    # split by instruction count
    chunks = []; cur = []; n = 0
    for a in order:
        f = funcs[a]; cur.append(f); n += len(f.addrs)
        if n >= chunk_instrs: chunks.append(cur); cur = []; n = 0
    if cur: chunks.append(cur)
    files = []
    t0 = time.time()
    for ci, ch in enumerate(chunks):
        text = '\n'.join(codegen.emit_function(prog, f, funcs) for f in ch)
        # only prototype what this chunk references
        refs = set(re.findall(r'\bF_[0-9A-F]+\b', text))
        protos = ''.join('void %s(CPU* RESTRICT c, u64 e);\n' % r for r in sorted(refs))
        p = os.path.join(outdir, 'code_%03d.c' % ci)
        write_if_changed(p, '#include "cpu.h"\n' + protos + text + '\n')
        files.append(p)
        if ci % 20 == 0 or ci == len(chunks) - 1:
            say('  C generated: %d/%d chunks (%.0fs)' % (ci + 1, len(chunks), time.time() - t0))
    # main module: tables + interpreter
    ents = []
    for a in order:
        f = funcs[a]
        for l in sorted(f.leaders): ents.append((l, f.name))
    names = sorted({f.name for f in funcs.values()})
    idx = {n: i for i, n in enumerate(names)}
    L = ['#include "module_abi.h"', '#include "cpu_helpers.c"']
    L += ['void %s(CPU* RESTRICT c, u64 e);' % n for n in names]
    L.append(codegen.gen_interp(step_mode=False))
    L.append('GuestFn swr_interp_entry;')
    L.append('static const GuestFn FNS[%d]={%s};' % (max(1, len(names)), ','.join(names) or '0'))
    L.append('static const u32 ENT_OFF[%d]={%s};' % (max(1, len(ents)), ','.join('%d' % (a - nxloader.CODE_BASE) for a, _ in ents) or '0'))
    L.append('static const u32 ENT_FN[%d]={%s};' % (max(1, len(ents)), ','.join(str(idx[n]) for _, n in ents) or '0'))
    L.append('static u64 ENT_ADDR[%d]; static GuestFn ENT_PTR[%d];' % (max(1, len(ents)), max(1, len(ents))))
    mi = []
    for m in mods:
        bid = (m.build_id + b'\0' * 32)[:32]
        mi.append('{"%s",0x%XULL,0x%XULL,{%s},%d,%d,%d,%d,%d,%d,%d,%d}' % (
            m.name, m.base, m.size, ','.join(str(b) for b in bid), m.text[0], m.text[1], m.ro[0], m.ro[1], m.data[0], m.data[1],
            m.bss, 2 if getattr(m, 'deferred', False) else 1 if getattr(m, 'nro', False) else 0))
    L.append('static const SwrModInfo MODS[%d]={%s};' % (len(mods), ','.join(mi)))
    lo = min(m.base + m.text[0] for m in mods); hi = max(m.base + m.text[0] + m.text[1] for m in mods)
    np_ = nxloader.parse_npdm(npdm)
    dyn = sorted(getattr(prog, 'dyn_calls', ()))
    L.append('SWR_EXPORT const u64 swr_dynamic_calls[%d]={%s};' % (len(dyn) + 1, ','.join('0x%XULL' % a for a in dyn + [0])))
    L.append('static const RtAPI* g_rt;')
    L.append('static void mod_init(const RtAPI* rt){ g_rt=rt; }')
    L.append('static SwrModule MOD;')
    L.append('SWR_EXPORT const SwrModule* swr_module(void){')
    L.append(' for(u32 i=0;i<%d;i++){ ENT_ADDR[i]=0x%XULL+ENT_OFF[i]; ENT_PTR[i]=FNS[ENT_FN[i]]; }' % (len(ents), nxloader.CODE_BASE))
    L.append(' swr_interp_entry=swr_interp;')
    L.append(' MOD.abi=SWR_MODULE_ABI; MOD.nmods=%d; MOD.mods=MODS; MOD.nentries=%d; MOD.entry_addr=ENT_ADDR; MOD.entry_fn=ENT_PTR; MOD.interp=swr_interp;' % (len(mods), len(ents)))
    L.append(' MOD.code_lo=0x%XULL; MOD.code_hi=0x%XULL; MOD.title="%s"; MOD.title_id=0x%XULL;' % (lo, hi, title.replace('"', ''), np_['title_id']))
    L.append(' MOD.main_stack=%d; MOD.main_prio=%d; MOD.main_core=%d; MOD.init=mod_init; return &MOD; }' % (np_['stack'], np_['prio'], np_['core']))
    p = os.path.join(outdir, 'module.c')
    write_if_changed(p, '\n'.join(L) + '\n')
    files.insert(0, p)
    say('C code: %d files, %.1f MB, %d entries' % (len(files), sum(os.path.getsize(x) for x in files) / 1e6, len(ents)))
    return files


def module_cflags(cc, opt, target_win, extra_flags=()):
    if is_tcc(cc):
        return ['-w', '-I', RT] + tcc_b(cc)
    flags = ['-O' + opt, '-fno-strict-aliasing', '-fwrapv', '-w', '-I', RT, '-foptimize-sibling-calls', '-fno-semantic-interposition']
    if not target_win:
        flags += ['-fPIC', '-fvisibility=hidden']
    return flags + list(extra_flags)


def module_ldflags(cc, target_win):
    if is_tcc(cc):
        return tcc_b(cc)
    return ['-static-libgcc'] if target_win else ['-lm']


def extra_cflags(cc, native=False):
    if is_tcc(cc):
        return []
    return (['-march=native'] if native else []) + os.environ.get('SWR_CFLAGS', '').split()


def compiler_output(cc, *args, **options):
    return subprocess.check_output([cc, *args], env=cc_env(cc), stderr=subprocess.STDOUT, timeout=30,
                                   creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0,
                                   **options)


def compiler_identity(cc):
    commands = [('version', '-v' if is_tcc(cc) else '--version')]
    if not is_tcc(cc):
        commands.append(('target', '-dumpmachine'))
    identity = {name: compiler_output(cc, flag).decode(errors='replace').splitlines()[0] for name, flag in commands}
    identity['driver_sha256'] = module_build.file_hash(shutil.which(cc) or cc)
    return identity


def module_options(cc, opt, target_win, extra_flags):
    return {
        'target': 'win64' if target_win else 'linux',
        'compile': ['<runtime>' if flag == RT else flag for flag in module_cflags(cc, opt, target_win, extra_flags)],
        'link': module_ldflags(cc, target_win),
        'environment': {key: os.environ[key] for key in ('CPATH', 'C_INCLUDE_PATH', 'GCC_EXEC_PREFIX', 'COMPILER_PATH',
                                                         'LIBRARY_PATH', 'SOURCE_DATE_EPOCH') if key in os.environ},
        'recipe': module_build.functions_hash({'module_cflags', 'module_ldflags', 'extra_cflags', 'compile_all',
                                                'link_module', 'gen_module'}),
        'windows_toolchain': module_build.source_hash(('tool/get_deps.py',)) if target_win else None,
    }


def read_hints(path):
    if not os.path.isfile(path):
        return []
    hints = set()
    with open(path) as stream:
        for line in stream:
            try: hints.add(int(line.strip(), 16))
            except ValueError: pass
    return sorted(hints)


def generation_environment():
    flags = [name for name in ('SWR_A64_NO_INLINE_SIMD', 'SWR_NO_BUILTIN_PATCHES') if os.environ.get(name)]
    return {'generation_flags': flags} if flags else {}


def generation_inputs(source, title, chunk, interp_only, hints, romfs=None):
    if os.path.isfile(source) and source.lower().endswith('.nro'):
        game = {'nro': module_build.file_hash(source)}
    else:
        game = module_build.game_inputs(Path(nxloader.find_exefs(source)), Path(romfs) if romfs else None)
    return {'contract': module_build.runtime_contract(), 'game': game, 'title': title,
            'chunk': chunk, 'interp_only': interp_only, 'hints': hints} | generation_environment()


def module_identity_file(build, inputs):
    path = os.path.join(build, 'module_identity.c')
    write_if_changed(path, '#include "cpu.h"\n'
                     'SWR_EXPORT const char swr_module_contract[] = "%s%s";\n'
                     'SWR_EXPORT const char swr_code_fingerprint[] = "%s%s";\n' %
                     (module_build.MODULE_MARKER, inputs['contract'],
                      module_build.FINGERPRINT_MARKER, module_build.digest(inputs)))
    return path


def orbitals_inputs(exefs, romfs, hints, target_win, compiler, extra_flags=(), *, compiler_environment=None):
    cc = 'x86_64-w64-mingw32-gcc' if target_win else 'gcc'
    return {'contract': module_build.runtime_contract(), 'game': module_build.game_inputs(exefs, romfs),
            'title': 'Orbitals', 'chunk': DEFAULT_CHUNK, 'interp_only': False, 'hints': hints,
            'options': module_options(cc, DEFAULT_OPT, target_win, extra_flags), 'compiler': compiler,
            'compiler_environment': compiler_environment} | generation_environment()


def object_cache_context(cc, flags, compiler):
    # All generated units include only these project headers. Hash the effective
    # preprocessing environment, including libc and compiler headers.
    headers = compiler_output(cc, *flags, '-E', '-P', '-x', 'c', '-',
                              input=b'#include "module_abi.h"\n#include "cpu_helpers.c"\n')
    tools = {}
    for name in (() if compiler.get('driver') == 'zig-cc' else ('cc1', 'as')):
        path = os.fsdecode(compiler_output(cc, '-print-prog-name=' + name).strip())
        path = shutil.which(path, path=cc_env(cc)['PATH']) or path
        if os.path.isfile(path):
            tools[name] = module_build.file_hash(path)
    return module_build.digest([compiler, tools, ['<runtime>' if flag == RT else flag for flag in flags],
                                hashlib.sha256(headers).hexdigest()])


def module_compiler_environment(cc, opt, target_win, flags, compiler):
    if is_tcc(cc) or flags:
        return None
    objects = object_cache_context(cc, module_cflags(cc, opt, target_win), compiler)
    if compiler.get('driver') == 'zig-cc':
        return objects  # the driver fingerprint already covers Zig's built-in linker
    inputs = []
    for query in ('-print-prog-name=ld', '-print-libgcc-file-name'):
        path = os.fsdecode(compiler_output(cc, query).strip())
        path = shutil.which(path, path=cc_env(cc)['PATH']) or path
        inputs.append(module_build.file_hash(path) if os.path.isfile(path) else None)
    return module_build.digest([objects, inputs])


def compile_all(files, cc, opt, outdir, target_win, jobs, say, extra_flags=(), *, object_cache=None, compiler=None):
    flags = module_cflags(cc, opt, target_win, extra_flags)
    # Custom switches can inject inputs outside the standard header set (e.g.
    # response files or plugins), and -march=native depends on the current CPU.
    cacheable = not is_tcc(cc) and not extra_flags and compiler is not None
    cache = Path(object_cache or Path(outdir) / 'objects-v1') if cacheable else None
    if cache:
        cache.mkdir(parents=True, exist_ok=True)
    context = object_cache_context(cc, flags, compiler) if cache else None
    t0 = time.time()

    def one(src):
        path = Path(src).resolve()
        if cache:
            key = module_build.digest([context, path.name, module_build.file_hash(path)])
            obj = cache / (key + '.o')
            if obj.is_file() and obj.stat().st_size:
                return obj, None, True
        else:
            obj = path.with_suffix('.o')
        fd, tmp = tempfile.mkstemp(suffix='.o', dir=obj.parent)
        os.close(fd)
        try:
            stable_path = [] if is_tcc(cc) else ['-ffile-prefix-map=%s=.' % path.parent]
            err = run_cc([cc, *flags, *stable_path, '-c', str(path), '-o', tmp], cc)
            if err is None:
                replace_retry(tmp, obj)
            return obj, err, False
        finally:
            Path(tmp).unlink(missing_ok=True)

    objs, hits = [], 0
    with ThreadPoolExecutor(max_workers=jobs) as ex:
        for n, (obj, err, reused) in enumerate(ex.map(one, files), 1):
            if err:
                ex.shutdown(cancel_futures=True)
                raise SystemExit('Compilation failed:\n' + err[-4000:])
            objs.append(obj)
            hits += reused
            if n % 10 == 0 or n == len(files):
                say('  compiled %d/%d (%.0fs, %d reused)' % (n, len(files), time.time() - t0, hits))
    say('Object cache: %d reused, %d compiled (%.2fs)' % (hits, len(files) - hits, time.time() - t0))
    return objs


def link_module(objs, cc, out, target_win, say):
    # big games have hundreds of objects and windows caps command lines at ~32K, so use an @rsp file
    # (gcc and tcc both take it) with short relative names
    out = os.path.abspath(out)
    if os.path.isfile(cc): cc = os.path.abspath(cc)
    with tempfile.TemporaryDirectory(dir=os.path.dirname(out), prefix='.link-') as work:
        rsp = Path(work) / 'objects.rsp'
        names = []
        for obj in objs:
            try:
                name = os.path.relpath(obj, work)
            except ValueError:  # an explicitly configured cache on a different Windows drive
                name = os.path.abspath(obj)
            names.append('"%s"\n' % Path(name).as_posix().replace('"', '\\"'))
        rsp.write_text(''.join(names), encoding='utf-8')
        cmd = [cc, '-shared', '-o', out, '@objects.rsp', *module_ldflags(cc, target_win)]
        err = run_cc(cmd, cc, cwd=work)
    if err: raise SystemExit('Linking failed:\n' + err[-4000:])
    if is_tcc(cc):
        # tcc also writes an export list next to the dll that nothing uses
        d = os.path.splitext(out)[0] + '.def'
        if os.path.isfile(d): os.remove(d)
        if not target_win: elf_stack_not_exec(out)


def elf_stack_not_exec(path):
    """tcc 0.9.27 writes no PT_GNU_STACK, so the loader thinks the library needs an executable stack
    and glibc 2.41+ refuses to dlopen it. we append a copy of the program headers plus a
    read/write PT_GNU_STACK at the end of the file and point the ELF header there, glibc copies
    program headers that no segment maps"""
    with open(path, 'r+b') as f:
        h = f.read(64)
        if h[:4] != b'\x7fELF' or h[4] != 2: return
        phoff, = struct.unpack_from('<Q', h, 32)
        phentsize, phnum = struct.unpack_from('<HH', h, 54)
        f.seek(phoff)
        ph = f.read(phentsize * phnum)
        types = [struct.unpack_from('<I', ph, i * phentsize)[0] for i in range(phnum)]
        # already there, or a PT_PHDR that would point at the old copy
        if 0x6474e551 in types or 6 in types: return
        end = f.seek(0, 2)
        pad = -end % 8
        f.write(bytes(1) * pad + ph + struct.pack('<IIQQQQQQ', 0x6474e551, 6, 0, 0, 0, 0, 0, 16))
        f.seek(32)
        f.write(struct.pack('<Q', end + pad))
        f.seek(56)
        f.write(struct.pack('<H', phnum + 1))


def runtime_path(target_win, backend):
    return os.path.join(HERE, 'bin', 'runtime_%s_%s%s' % ('win64' if target_win else 'linux', backend,
                                                           '.exe' if target_win else ''))


def release_id():
    """'<VERSION> <commit>': VERSION beside this script, the commit from git, else from a COMMIT file (source archives), else 'unknown'."""
    import re as _re, subprocess as _sp
    def read(name):
        try:
            with open(os.path.join(HERE, name), encoding='utf-8') as f:
                return f.read().strip()
        except OSError:
            return ''
    if os.environ.get('SWR_RELEASE'):   # set by whoever builds a release binary from another checkout of the same tree
        return _re.sub(r'[^\w.\- ]', '', os.environ['SWR_RELEASE'])[:80]
    commit = ''
    try:
        r = _sp.run(['git', '-C', HERE, 'rev-parse', '--short=12', 'HEAD'], stdout=_sp.PIPE, stderr=_sp.DEVNULL, timeout=10)
        if r.returncode == 0:
            commit = r.stdout.decode('ascii', 'replace').strip()
            d = _sp.run(['git', '-C', HERE, 'status', '--porcelain', '--untracked-files=no'], stdout=_sp.PIPE, stderr=_sp.DEVNULL, timeout=20)
            if d.returncode == 0 and d.stdout.strip():
                commit += '-modified'
    except (OSError, _sp.SubprocessError):
        pass
    commit = commit or read('COMMIT') or 'unknown'
    rid = '%s %s' % (read('VERSION') or 'dev', commit)
    return _re.sub(r'[^\w.\- ]', '', rid)[:80]


def build_runtime(cc, out, target_win, backend, say, opt='2'):
    if is_tcc(cc):
        # bcn, SPIRV-Cross and OpenH264 are C++
        raise SystemExit('TCC cannot build the runtime: build it once with GCC (--build-runtime --cc gcc), '
                         'or use the prebuilt one from the release (%s).' % os.path.relpath(runtime_path(target_win, backend), HERE))
    gl = backend != 'headless'
    extra = ['gpu_gl', 'gl_load', 'shader', 'shader_proc', 'astc', 'glq', 'glq_gen'] if gl else ['gpu_nogl', 'shader_proc']
    srcs = [os.path.join(RT, s + '.c') for s in RUNTIME_SRC + extra] + [os.path.join(RT, 'backend_%s.c' % backend), os.path.join(RT, 'entry.c')]
    if gl: srcs += [os.path.join(RT, 'bcn', 'bcn.cpp'), os.path.join(RT, 'bcn', 'bcdec.cpp')]
    # LSFG (uses the user's Lossless.dll), desktop GL only
    spvc = None
    if gl and backend in ('win32', 'x11'):
        spvc = os.path.join(RT, 'spvc', 'win' if target_win else 'lin', 'libspvc.a')
        if os.path.isfile(spvc): srcs += [os.path.join(RT, 'lsfg.c'), os.path.join(RT, 'lsfg_spvc.cpp')]
        else: spvc = None
    if gl and not spvc: srcs += [os.path.join(RT, 'lsfg_stub.c')]
    # renderer=vulkan: Eden's video_core (GPL-3.0) when runtime/edenvk/<os>/libedenvk.a is built (runtime/edenvk/build_lib.py)
    evk = os.path.join(RT, 'edenvk', 'win' if target_win else 'lin')
    evk_libs = [os.path.join(evk, 'libedenvk.a'), os.path.join(evk, 'libsirit.a')]
    edenvk = gl and backend in ('win32', 'x11') and all(os.path.isfile(x) for x in evk_libs) and not os.environ.get('SWR_NO_EDENVK')
    if not edenvk: srcs += [os.path.join(RT, 'edenvk_stub.c')]
    if target_win and backend == 'win32':
        srcs += [os.path.join(RT, name) for name in ('rec_win32.c', 'gamepad_win32.c')]
    # NVDEC/VIC video: link OpenH264 (BSD) statically if we have it for this target
    oh = os.path.join(RT, 'oh264', 'win' if target_win else 'lin')
    h264_libs = [os.path.join(oh, 'libdecoder.a'), os.path.join(oh, 'libcommon.a')]
    if not all(os.path.isfile(lib) for lib in h264_libs):
        h264_libs = [os.path.join(oh, 'libopenh264.a')]
    h264 = all(os.path.isfile(lib) for lib in h264_libs) and backend in ('win32', 'x11', 'headless')
    srcs += [os.path.join(RT, 'host1x.c')]
    if not target_win: srcs += [os.path.join(RT, 'glibc_compat.c')]   # runs on glibc 2.34+ (Ubuntu 22.04, Debian 12)
    # hwopus: libopus (BSD), same rule as OpenH264
    op = os.path.join(RT, 'opus', 'win' if target_win else 'lin')
    opus_libs = []
    if backend in ('win32', 'x11', 'headless'):
        archived_opus = os.path.join(op, 'libopus.a')
        if os.path.isfile(archived_opus):
            opus_libs = [archived_opus]
        elif not target_win and shutil.which('pkg-config'):
            result = subprocess.run(['pkg-config', '--libs', 'opus'], capture_output=True, text=True)
            if result.returncode == 0:
                opus_libs = shlex.split(result.stdout)
    # VP9 WebM movies: indexed from RomFS and decoded with libvpx (BSD), linked when runtime/vp9/<os>/libvpx.a exists
    vp = os.path.join(RT, 'vp9', 'win' if target_win else 'lin')
    vp9 = os.path.isfile(os.path.join(vp, 'libvpx.a')) and backend in ('win32', 'x11', 'headless')
    cmd = [cc] + ([] if target_win else ['-std=gnu17']) + ([] if is_tcc(cc) else ['-ffile-prefix-map=' + HERE + '=.']) + ['-O' + opt, '-w', '-fno-strict-aliasing', '-Wl,-S', '-I', RT, '-I', os.path.join(RT, 'bcn'), '-I', os.path.join(RT, 'spvc'), '-I', os.path.join(RT, 'oh264', 'include'), '-I', os.path.join(RT, 'opus', 'include')] + srcs + ['-o', out]
    cmd += ['-DSWR_RELEASE="%s"' % release_id()]   # the log's first line (bug reports): the release and the commit it was built from
    cmd += ['-DSWR_CODE_CONTRACT="%s"' % module_build.runtime_contract()]
    if target_win and backend == 'win32': cmd += ['-DSWR_RECORD_AUDIO']
    if not h264: cmd += ['-DSWR_NO_H264']
    if not opus_libs: cmd += ['-DSWR_NO_OPUS']
    if vp9: cmd += ['-DSWR_HAVE_VP9', '-I', os.path.join(RT, 'vp9', 'include')]
    if spvc: cmd += [spvc]
    # renderer=vulkan: the NVN layer (runtime/nvn, built by tools/build_nvn.py)
    nvn_lib = os.path.join(HERE, 'build', 'nvn', 'libnvn.a')
    if target_win and backend == 'win32' and os.path.isfile(nvn_lib) and not os.environ.get('SWR_NO_NVN'): cmd += ['-DSWR_HAVE_NVN', nvn_lib, '-lbcrypt', '-luuid']
    nvn_lin = os.path.join(HERE, 'build', 'nvn_lin', 'libnvn.a')   # tools/build_nvn.py --linux
    if not target_win and backend == 'x11' and os.path.isfile(nvn_lin) and not os.environ.get('SWR_NO_NVN'): cmd += ['-DSWR_HAVE_NVN', nvn_lin, '-ldl', '-lpthread']
    if h264: cmd += h264_libs
    cmd += opus_libs
    if vp9: cmd += [os.path.join(vp, 'libvpx.a')]
    if edenvk: cmd += evk_libs + (['-luuid', '-lole32', '-lshell32', '-lntdll'] if target_win else [])
    if gl or h264 or edenvk:
        # static on Linux too, so the runtime doesn't depend on the libstdc++ version of the distro
        cmd += ['-lstdc++'] if target_win else ['-Wl,-Bstatic', '-lstdc++', '-Wl,-Bdynamic', '-static-libgcc']
    if target_win:
        cmd += ['-static', '-lgdi32', '-lwinmm', '-luser32', '-lopengl32', '-lcomdlg32', '-lshell32', '-mwindows' if backend == 'win32' else '-mconsole']
        if backend == 'win32': cmd += ['-lmfplat', '-lmfreadwrite', '-lmfuuid', '-lole32']
    else:
        cmd += ['-lpthread', '-ldl', '-lm', '-rdynamic']
        if backend == 'x11': cmd += ['-lX11', '-lGL']
    err = run_cc(cmd, cc)
    if err: raise SystemExit('Runtime build failed:\n' + err[-4000:])


def sync_tree(src, dst):
    """copy the files that are new or changed (size or time); copy2 keeps the time for the next check"""
    # ROMFS trees can contain many large files. On Linux, let rsync compare and
    # transfer only changed files instead of opening and copying each one here.
    rsync = shutil.which('rsync') if sys.platform.startswith('linux') else None
    if rsync:
        os.makedirs(dst, exist_ok=True)
        cmd = [rsync, '-rlt', '--modify-window=2', '--itemize-changes',
               '--out-format=%i', '--', os.path.join(os.path.abspath(src), ''),
               os.path.join(os.path.abspath(dst), '')]
        result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                text=True, errors='replace')
        if result.returncode:
            detail = result.stderr.strip() or 'no error details'
            raise RuntimeError('rsync failed while copying ROMFS: ' + detail)
        # Itemized regular files and symlinks count as copied entries; directory
        # creation lines do not.
        return sum(line.startswith(('>f', '<f', '>L', '<L', 'cL'))
                   for line in result.stdout.splitlines())

    # Keep the portable path for Windows and Linux installs without rsync.
    copied = 0
    for root, dirs, names in os.walk(src):
        droot = os.path.join(dst, os.path.relpath(root, src))
        os.makedirs(droot, exist_ok=True)
        for n in names:
            s = os.path.join(root, n); d = os.path.join(droot, n)
            ss = os.stat(s)
            try:
                ds = os.stat(d)
                if ds.st_size == ss.st_size and abs(ds.st_mtime - ss.st_mtime) < 2: continue
            except OSError:
                pass
            shutil.copy2(s, d); copied += 1
    return copied


def copy_data(mods, npdm, romfs, entry, datadir, say):
    ex = os.path.join(datadir, 'exefs'); os.makedirs(ex, exist_ok=True)
    if os.path.isfile(entry) and entry.lower().endswith('.nro'):
        shutil.copyfile(entry, os.path.join(ex, 'main.nro'))
        if isinstance(romfs, (bytes, bytearray)):
            with open(os.path.join(datadir, 'romfs.bin'), 'wb') as fo: fo.write(romfs)
        # icon and title for the tool
        for which, name in ((0, 'icon.jpg'), (1, 'control.nacp')):
            blob = nxloader.nro_asset(mods[0], which)
            if blob: open(os.path.join(datadir, name), 'wb').write(blob)
        return
    # compare contents, not sizes: after a game update main.npdm (and sometimes an NSO) keeps its
    # size, and the runtime refuses an NSO whose build id differs from the recompiled one
    src = nxloader.find_exefs(entry)
    if os.path.normcase(os.path.realpath(src)) != os.path.normcase(os.path.realpath(ex)):
        for n in os.listdir(src):
            s = os.path.join(src, n); d = os.path.join(ex, n)
            if os.path.isfile(s) and not (os.path.isfile(d) and filecmp.cmp(s, d, shallow=False)):
                shutil.copyfile(s, d)
    # icon and title for the tool, if the dump has the control data (control/ or next to exefs/)
    root = os.path.dirname(os.path.normpath(src))
    for d in (root, os.path.join(root, 'control')):
        for name in ('control.nacp', 'icon_AmericanEnglish.dat', 'icon.jpg', 'icon.png'):
            s = os.path.join(d, name)
            if os.path.isfile(s): shutil.copyfile(s, os.path.join(datadir, name))
    if isinstance(romfs, str):
        dst = os.path.join(datadir, 'romfs')
        if os.path.normcase(os.path.realpath(romfs)) != os.path.normcase(os.path.realpath(dst)):
            first = not os.path.exists(dst)
            if first: say('Copying romfs (may take a while)...')
            if sys.platform.startswith('linux') and not shutil.which('rsync'):
                say('rsync is unavailable; using the built-in ROMFS copy fallback')
            n = sync_tree(romfs, dst)
            if n and not first: say('romfs: %d changed files copied' % n)


def check_writable(*paths):
    # a running game locks its exe and dll: say so before spending minutes compiling
    for p in paths:
        if os.path.exists(p):
            try:
                with open(p, 'ab'): pass
            except OSError:
                raise SystemExit('%s is in use. Close the game and try again.' % p)


INI = """; %(title)s - SwitchRecomp settings
; This file is rewritten (organized, with every option explained) the first time the game starts.
[Display]
language=1
"""


def main():
    ap = argparse.ArgumentParser(description='Recompiles a Switch game into a native executable.')
    ap.add_argument('input', nargs='?', help='game folder (exefs/ + romfs/) or .nro file')
    ap.add_argument('-o', '--out', help='output name (no extension)')
    ap.add_argument('--outdir', help='output folder')
    ap.add_argument('--cc', help='C compiler (gcc, clang, tcc, x86_64-w64-mingw32-gcc)')
    ap.add_argument('-O', default=DEFAULT_OPT, help='optimization level (0-3)')
    ap.add_argument('--jobs', type=int, default=os.cpu_count() or 4)
    ap.add_argument('--chunk', type=int, default=DEFAULT_CHUNK, help='instructions per C file')
    ap.add_argument('--target', choices=['auto', 'win64', 'linux'], default='auto')
    ap.add_argument('--backend', choices=['auto', 'win32', 'x11', 'headless'], default='auto')
    ap.add_argument('--native', action='store_true', help='optimize for THIS processor (-march=native)')
    ap.add_argument('--no-build', action='store_true', help='only generate the C code and copy the game data')
    ap.add_argument('--keep-c', action='store_true', help=argparse.SUPPRESS)   # the C is always kept, for rebuilds
    ap.add_argument('--interp-only', action='store_true', help='(diagnostics) no recompilation, everything interpreted')
    ap.add_argument('--runtime', help='use an already built runtime (.exe) instead of building it')
    ap.add_argument('--build-runtime', action='store_true', help='build bin/runtime_<target>_<backend> with GCC and exit')
    ap.add_argument('--check-runtime', metavar='FILE', help='check that a prebuilt runtime matches this generator')
    ap.add_argument('--check-module', action='store_true', help='check a standard Orbitals build against the current inputs')
    ap.add_argument('--object-cache', help='folder for reusable compiled objects')
    ap.add_argument('--no-copy-data', action='store_true', help='leave the installation data and INI untouched')
    ap.add_argument('-q', '--quiet', action='store_true')
    a = ap.parse_args()
    say = (lambda m: None) if a.quiet else (lambda m: print(m, flush=True))
    target_win = a.target == 'win64' or (a.target == 'auto' and sys.platform.startswith('win'))
    backend = a.backend if a.backend != 'auto' else ('win32' if target_win else 'x11')
    if a.check_runtime:
        return 0 if module_build.marker_value(a.check_runtime, module_build.RUNTIME_MARKER) == module_build.runtime_contract() else 1
    if a.build_runtime:
        cc = find_cc(a.cc, target_win)
        if not cc: raise SystemExit('C compiler not found: %s' % (a.cc or 'gcc'))
        out = runtime_path(target_win, backend)
        os.makedirs(os.path.dirname(out), exist_ok=True)
        check_writable(out)
        say('Compiling the runtime (%s) with %s...' % (backend, os.path.basename(cc)))
        build_runtime(cc, out, target_win, backend, say, a.O)
        say('Done: %s' % out)
        return
    if not a.input: ap.error('the game folder or .nro file is required')
    # check the compiler first, not after minutes of translation
    cc = None
    if not a.no_build:
        cc = find_cc(a.cc, target_win)
        if not cc: raise SystemExit('C compiler not found: %s' % a.cc if a.cc else 'No C compiler found (gcc, clang or tcc).')
    prebuilt = a.runtime or runtime_path(target_win, backend)
    if not a.no_build and (a.runtime or os.path.isfile(prebuilt)):
        if module_build.marker_value(prebuilt, module_build.RUNTIME_MARKER) != module_build.runtime_contract():
            raise SystemExit('The prebuilt runtime expects different recompiled code. Build the runtime for this kit first.')
    if a.check_module:
        source = Path(a.input)
        outdir = Path(a.outdir or os.getcwd())
        module = outdir / ('Orbitals_code.dll' if target_win else 'Orbitals_code.so')
        saved = module_build.read_manifest(module)
        if not saved:
            return 1
        compiler = compiler_identity(cc)
        flags = extra_cflags(cc, a.native)
        inputs = orbitals_inputs(source / 'exefs', source / 'romfs', read_hints(outdir / 'Orbitals.hints'),
                                 target_win, compiler, flags,
                                 compiler_environment=module_compiler_environment(cc, a.O, target_win, flags, compiler))
        return 0 if saved['inputs'] == inputs and module_build.verified_module(module, saved, inputs['contract']) else 1
    say('SwitchRecomp - use your own copy of the game. No games or keys included.')
    try:
        mods, npdm, romfs = nxloader.load_program(a.input)
    except (ValueError, OSError) as e:
        raise SystemExit('Cannot load the game: %s' % e)
    for m in mods:
        say('  %-8s %010X  code %.1f MB  .eh_frame functions %d' % (m.name, m.base, m.text[1] / 1048576.0, len(m.fde)))
    info = nxloader.parse_npdm(npdm)
    # a folder name is used as is ("Game v1.0" must not lose ".0"), a file loses its extension
    src_name = os.path.basename(os.path.normpath(a.input))
    if os.path.isfile(a.input): src_name = os.path.splitext(src_name)[0]
    title = a.out or (info['name'] if info['name'] not in ('Application', '') else None) or src_name
    title = ''.join(ch for ch in title if ch.isalnum() or ch in '-_ ').strip() or 'Game'
    outdir = os.path.abspath(a.outdir or os.getcwd())
    os.makedirs(outdir, exist_ok=True)
    base = os.path.join(outdir, title)
    exe = base + ('.exe' if target_win else '')
    modout = base + ('_code.dll' if target_win else '_code.so')

    if not a.no_build: check_writable(exe, modout)
    hints = read_hints(base + '.hints')
    if hints:
        say('Previous execution hints: %d' % len(hints))
    inputs = generation_inputs(a.input, title, a.chunk, a.interp_only, hints, romfs)
    prog = codegen.Program(mods, hints)
    if a.interp_only:
        prog.funcs = {}; prog.extra_entries = set()
    else:
        say('Analyzing the code...')
        prog.analyze(say)
    build = base + '_build'
    os.makedirs(build, exist_ok=True)
    say('Translating ARM64 to C...')
    files = gen_module(prog, mods, npdm, build, title, a.chunk, say)
    module_build.write_json(Path(build) / 'generation.json', inputs | {'units': [Path(file).name for file in files]})
    datadir = base + '_data'
    if not a.no_copy_data:
        copy_data(mods, npdm, romfs, a.input, datadir, say)
        if not os.path.exists(base + '.ini'):
            with open(base + '.ini', 'w', encoding='utf-8') as fo: fo.write(INI % {'title': title})
    if a.no_build:
        return
    # The compiler workers only need the generated C files. Release the decoded game first.
    del prog, mods
    say('Compiling with %s (-O%s, %d at a time)...' % (os.path.basename(cc), a.O, a.jobs))
    extra = extra_cflags(cc, a.native)
    compiler = compiler_identity(cc)
    inputs.update(options=module_options(cc, a.O, target_win, extra), compiler=compiler,
                  compiler_environment=module_compiler_environment(cc, a.O, target_win, extra, compiler))
    files.append(module_identity_file(build, inputs))
    objs = compile_all(files, cc, a.O, build, target_win, a.jobs, say, extra,
                       object_cache=a.object_cache, compiler=compiler)
    say('Linking %s ...' % os.path.basename(modout))
    with tempfile.TemporaryDirectory(dir=outdir, prefix='.recompile-') as work:
        pending_module = Path(work) / Path(modout).name
        pending_exe = Path(work) / Path(exe).name
        link_module(objs, cc, str(pending_module), target_win, say)
        if os.path.isfile(prebuilt):
            shutil.copyfile(prebuilt, pending_exe)
        else:
            say('Compiling the runtime (%s)...' % backend)
            build_runtime(cc, str(pending_exe), target_win, backend, say)
        if not target_win:
            pending_exe.chmod(0o755)
        manifest = {'schema': 1, 'fingerprint': module_build.digest(inputs), 'inputs': inputs,
                    'module_sha256': module_build.file_hash(pending_module)}
        if not module_build.verified_module(pending_module, manifest, inputs['contract']):
            raise SystemExit('The new module is missing its build identity.')
        replace_retry(pending_module, modout)
        replace_retry(pending_exe, exe)
        module_build.write_json(module_build.manifest_path(modout), manifest)
    say('Done: %s' % exe)


if __name__ == '__main__':
    sys.exit(main())
