#!/usr/bin/env python3
# SwitchRecomp - Copyright 2026 MZ Labs
# Licensed under the GNU Affero General Public License v3.0, see LICENSE.txt and NOTICE.txt.
# Forks and derived works have to keep the credit to SwitchRecomp by MZ Labs and the startup screen.
"""nxs_prepare: every shader of the game translated to SPIR-V before the first launch, from the user's own files.

  nxs_prepare.py --romfs ROMFS --cache CACHE --work WORK --decoder LIB [--workers N] [--xlate DIR] [--dotnet EXE]

1. extract  each Unreal IoStore container of ROMFS that holds shader code (nxs_iostore.py extract) into WORK/extract/<name>
2. decode   its shader groups into NVN2 <key>.ctl / <key>.code pairs (nxs_ue_nv2.py with LIB, an OodleLZ_Decompress-compatible
            decoder) into WORK/pairs/<name>; each pair is accepted only when its SHA-256 gives the key the runtime computes
3. translate the pairs no current entry of CACHE covers, in N disjoint shards translated by N nxs_live.py --offline processes at once
            (each validates every module with SPIR-V Tools), into WORK/<chain>/shard-<i>
4. publish  the shards into CACHE (the runtime's NXRT_SHADER_CACHE), under the translator chain id; the entries of another chain are
            dropped first (a new translator, front or edit version), the runtime's own captures (CACHE/dumps) are kept. Orbitals:
            23,144 shaders, ~2.7 GB of modules (vk/) and ~1 GB of translator output (xlate/, for nxs_reedit.py); about 15 min on 8 cores

Progress: one JSON object per line on stdout ({"phase": ...}); the last one is "done" (or "error" / "interrupted"). Counts:
discovered (distinct shader keys in the game files), cached (already current in CACHE), translated, validated (spirv-val ok among
the cache's entries), failed. Each step is resumable: an extraction or decoding whose inputs did not change (sizes, times, decoder
hash) is kept, and shard caches keep what they translated; a rerun after an interruption does the rest only.

This step makes SPIR-V modules, not Vulkan pipelines: the driver still compiles a pipeline the first time a draw needs its state
(shaders, vertex layout, blend, targets). The runtime builds those in its pipeline cache (NXRT_VK_CACHE_DIR) and prewarms the ones its
lists know; a pipeline seen for the first time can still take a few milliseconds to a few hundred in its frame.

Nothing in ROMFS is written. WORK holds decoded game data: it stays on this PC (never shared, never published)."""
import argparse, hashlib, json, os, shutil, subprocess, sys, threading, time
NO_WINDOW = 0x08000000 if os.name == 'nt' else 0   # CREATE_NO_WINDOW: a tool started from the launcher (no console) opens no window

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import nxs_cache as C
import nxshader as N


def emit(phase, **fields):
    print(json.dumps({'phase': phase, **fields}), flush=True)


def file_sha(path):
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for block in iter(lambda: f.read(1 << 20), b''): h.update(block)
    return h.hexdigest()


def stamp_of(*paths, extra=''):
    """what an output depends on: sizes and modification times of its inputs (and an extra string)"""
    parts = [extra]
    for p in paths:
        st = os.stat(p); parts.append(f'{os.path.basename(p)}:{st.st_size}:{st.st_mtime_ns}')
    return hashlib.sha256('\n'.join(parts).encode()).hexdigest()


def kept(out, stamp):
    sp = out + '.stamp'
    return os.path.isdir(out) and os.path.exists(sp) and open(sp).read().strip() == stamp


def run_tool(args, label):
    """a tool of this folder whose stdout is JSON lines: its last line, or an error"""
    r = subprocess.run([sys.executable, '-B', *args], capture_output=True, text=True, creationflags=NO_WINDOW)
    lines = [l for l in r.stdout.splitlines() if l.startswith('{')]
    last = json.loads(lines[-1]) if lines else {}
    if r.returncode not in (0,) or not lines:
        raise RuntimeError(f'{label} failed (exit {r.returncode}): ' + ((r.stderr.strip().splitlines() or [''])[-1] or str(last))[:300])
    return [json.loads(l) for l in lines]


def containers(romfs):
    """the IoStore containers (.utoc with their .ucas) under ROMFS"""
    out = []
    for root, _, files in os.walk(romfs):
        for f in sorted(files):
            if f.endswith('.utoc') and os.path.exists(os.path.join(root, f[:-5] + '.ucas')):
                out.append((f[:-5], os.path.join(root, f), os.path.join(root, f[:-5] + '.ucas')))
    return out


def extract_and_decode(romfs, work, decoder):
    """steps 1 and 2: the folders of NVN2 pairs, one per container with shader code"""
    dec_sha = file_sha(decoder)
    pair_dirs = []
    for name, toc, ucas in containers(romfs):
        ex = os.path.join(work, 'extract', name)
        st = stamp_of(toc, ucas, extra='extract 1')
        if kept(ex, st):
            emit('extract', container=name, status='kept')
        else:
            shutil.rmtree(ex, ignore_errors=True); os.makedirs(os.path.dirname(ex), exist_ok=True)
            res = run_tool([os.path.join(HERE, 'nxs_iostore.py'), 'extract', toc, ucas, ex], f'extracting {name}')
            open(ex + '.stamp', 'w').write(st)
            emit('extract', container=name, status='done', shader_code=res[-1].get('shader_code', 0))
        report = json.load(open(os.path.join(ex, 'report.json'))) if os.path.exists(os.path.join(ex, 'report.json')) else {}
        if not report.get('shader_code') or not report.get('shader_code_library'):
            continue   # no shader code in this container (e.g. global.utoc)
        pd = os.path.join(work, 'pairs', name)
        st2 = hashlib.sha256((st + dec_sha + 'decode 1').encode()).hexdigest()
        if kept(pd, st2):
            emit('decode', container=name, status='kept', pairs=sum(1 for f in os.listdir(pd) if f.endswith('.ctl')))
        else:
            shutil.rmtree(pd, ignore_errors=True); os.makedirs(os.path.dirname(pd), exist_ok=True)
            res = run_tool([os.path.join(HERE, 'nxs_ue_nv2.py'), ex, pd, '--oodle', decoder], f'decoding {name}')
            groups = next((r for r in res if r.get('phase') == 'groups'), {})
            if groups.get('decode_failed') or groups.get('size_mismatch'):
                raise RuntimeError(f'{name}: {groups.get("decode_failed")} shader groups did not decode, {groups.get("size_mismatch")} had the wrong size')
            open(pd + '.stamp', 'w').write(st2)
            emit('decode', container=name, status='done', groups=groups.get('groups'), pairs=res[-1].get('pairs'))
        pair_dirs.append(pd)
    return pair_dirs


def current_keys(cache, chain):
    vk = os.path.join(cache, 'vk')
    try:
        if C.read_shared_file(os.path.join(vk, 'CHAIN'), 'ascii').strip() != chain: return set()
    except FileNotFoundError:
        return set()
    out = set()
    for f in os.listdir(vk):
        if f.endswith('.json') and len(f) == 21:
            try:
                meta = json.load(open(os.path.join(vk, f), encoding='utf-8'))
                if (meta.get('cache') or {}).get('chain') == chain and os.path.exists(os.path.join(vk, f[:16] + '.spv')): out.add(f[:16])
            except (OSError, ValueError):
                pass
    return out


def translate(pair_dirs, cache, work, chain, workers, xlate, dotnet):
    """step 3: shard caches with every pair no current cache entry covers"""
    pairs = {}
    for d in pair_dirs:
        for f in os.listdir(d):
            if f.endswith('.ctl'): pairs.setdefault(f[:16], d)
    cached = current_keys(cache, chain)
    todo = sorted(k for k in pairs if k not in cached)
    counts = {'discovered': len(pairs), 'cached': len(pairs) - len(todo), 'translated': 0, 'failed': 0}
    emit('translate', **counts, todo=len(todo), workers=workers)
    base = os.path.join(work, chain)
    shards = []
    for i in range(workers):
        keys = todo[i::workers]
        sd, sc = os.path.join(base, f'shard-{i}', 'pairs'), os.path.join(base, f'shard-{i}', 'cache')
        shutil.rmtree(sd, ignore_errors=True); os.makedirs(sd)
        for k in keys:
            for ext in ('.ctl', '.code'):
                src, dst = os.path.join(pairs[k], k + ext), os.path.join(sd, k + ext)
                try: os.link(src, dst)
                except OSError: shutil.copyfile(src, dst)
        if keys: shards.append((i, sd, sc, len(keys)))
    done, lock, errors = {}, threading.Lock(), []

    def run(i, sd, sc, n):
        cmd = [sys.executable, '-B', os.path.join(HERE, 'nxs_live.py'), '--offline', '--dump', sd, '--cache', sc, '--jobs', '1', '--xlate', xlate, '--dotnet', dotnet]
        p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                             creationflags=(0x00004000 if os.name == 'nt' else 0) | NO_WINDOW)   # below normal priority: the PC stays usable
        for line in p.stdout:
            if not line.startswith('{'): continue
            ev = json.loads(line)
            if ev.get('phase') in ('translation', 'finished'):
                with lock: done[i] = (ev.get('prepared', 0) + ev.get('reused', 0), ev.get('failed', 0))
            elif ev.get('phase') == 'shader_error':
                emit('shader_error', key=ev.get('key'), status=ev.get('status'), error=ev.get('error'))
            elif ev.get('phase') == 'error':
                errors.append(ev.get('error'))
        err = p.stderr.read(); p.wait()
        if p.returncode not in (0, 2): errors.append(f'shard {i}: exit {p.returncode}: ' + (err.strip().splitlines() or [''])[-1][:300])

    threads = [threading.Thread(target=run, args=s, daemon=True) for s in shards]
    for t in threads: t.start()
    while any(t.is_alive() for t in threads):
        time.sleep(1.0)
        with lock: tr = sum(v[0] for v in done.values()); fl = sum(v[1] for v in done.values())
        emit('translate', **dict(counts, translated=tr, failed=fl), todo=len(todo))
    for t in threads: t.join()
    if errors: raise RuntimeError('; '.join(errors)[:600])
    counts['translated'] = sum(v[0] for v in done.values()); counts['failed'] = sum(v[1] for v in done.values())
    return counts, [sc for _, _, sc, _ in shards]


def publish(cache, chain, shard_caches):
    """step 4: the shards' entries into CACHE under the chain; entries of another chain are dropped first"""
    vk = os.path.join(cache, 'vk')
    try: old = C.read_shared_file(os.path.join(vk, 'CHAIN'), 'ascii').strip()
    except FileNotFoundError: old = None
    if old != chain and os.path.isdir(cache):
        for name in os.listdir(cache):
            if name not in ('dumps', '.prewarm.lock'):
                p = os.path.join(cache, name)
                shutil.rmtree(p, ignore_errors=True) if os.path.isdir(p) else os.remove(p)
        emit('publish', dropped_chain=old)
    os.makedirs(vk, exist_ok=True)
    with C.prewarm_lock(cache):
        for sc in shard_caches:
            for kind in ('xlate', 'final'):
                top = os.path.join(sc, kind)
                for sub in os.listdir(top) if os.path.isdir(top) else []:
                    os.makedirs(os.path.join(cache, kind, sub), exist_ok=True)
                    for f in os.listdir(os.path.join(top, sub)): os.replace(os.path.join(top, sub, f), os.path.join(cache, kind, sub, f))
            svk = os.path.join(sc, 'vk')
            for f in sorted(os.listdir(svk)) if os.path.isdir(svk) else []:
                if f.endswith('.spv'): os.replace(os.path.join(svk, f), os.path.join(vk, f))
            for f in sorted(os.listdir(svk)) if os.path.isdir(svk) else []:   # each reflection after its module: a reader takes an entry by its json
                if f.endswith('.json'): os.replace(os.path.join(svk, f), os.path.join(vk, f))
        C.Cache(cache).set_chain(chain)
    # final/ only remembers edit results (nxs_reedit.py makes them again when they are gone): ~1 GB for the whole game. xlate/ stays, so a new
    # edit version is applied without translating again
    shutil.rmtree(os.path.join(cache, 'final'), ignore_errors=True)


def summary(cache, chain):
    ok = bad = 0; vk = os.path.join(cache, 'vk')
    for f in os.listdir(vk):
        if f.endswith('.json') and len(f) == 21:
            try: meta = json.load(open(os.path.join(vk, f), encoding='utf-8'))
            except (OSError, ValueError): continue
            if (meta.get('cache') or {}).get('chain') != chain: continue
            if meta.get('spirv_val') == 'ok': ok += 1
            else: bad += 1
    return ok, bad


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--romfs', required=True); ap.add_argument('--cache', required=True); ap.add_argument('--work', required=True)
    ap.add_argument('--decoder', required=True, help='an OodleLZ_Decompress-compatible shared library (nxs_kraken.py builds one)')
    ap.add_argument('--workers', type=int, default=max(1, min(8, (os.cpu_count() or 2) // 2)))
    ap.add_argument('--xlate', default=os.path.join(HERE, 'xlate_bin')); ap.add_argument('--dotnet', default='dotnet')
    a = ap.parse_args(argv)
    t0 = time.monotonic()
    try:
        for name in ('spirv-val', 'spirv-opt'):
            if not N.vk_tool(name): raise RuntimeError(f'{name} is required (set NXSHADER_TOOLS)')
        xl = N.F.Translator(a.xlate, a.dotnet); chain = N.chain_id(xl)
        emit('start', chain=chain, translator=xl.id, workers=a.workers)
        os.makedirs(a.work, exist_ok=True)
        pair_dirs = extract_and_decode(a.romfs, a.work, a.decoder)
        if not pair_dirs: raise RuntimeError('no Unreal IoStore container with shader code under ' + a.romfs)
        counts, shard_caches = translate(pair_dirs, a.cache, a.work, chain, a.workers, a.xlate, a.dotnet)
        publish(a.cache, chain, shard_caches)
        shutil.rmtree(os.path.join(a.work, chain), ignore_errors=True)
        for other in os.listdir(a.work):   # shards of an older chain: nothing will finish them
            if len(other) == 16 and other != chain: shutil.rmtree(os.path.join(a.work, other), ignore_errors=True)
        ok, bad = summary(a.cache, chain)
        C.atomic_write(os.path.join(a.cache, 'PREPARED'), json.dumps({'chain': chain, 'translator': xl.id, **counts, 'validated': ok,
                                                                      'invalid': bad, 'seconds': round(time.monotonic() - t0, 1), 'at': time.strftime('%Y-%m-%dT%H:%M:%S')}) + '\n')
        emit('done', **counts, validated=ok, invalid=bad, seconds=round(time.monotonic() - t0, 1))
        return 0 if not counts['failed'] else 2
    except KeyboardInterrupt:
        emit('interrupted', seconds=round(time.monotonic() - t0, 1)); return 130
    except (OSError, RuntimeError, ValueError, subprocess.SubprocessError) as error:
        emit('error', error=str(error)[:600], seconds=round(time.monotonic() - t0, 1)); return 1


if __name__ == '__main__':
    sys.exit(main())
