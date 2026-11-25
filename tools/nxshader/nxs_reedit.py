#!/usr/bin/env python3
"""nxs_reedit: apply the current Vulkan edits (nxs_spv.py DEFAULT_PASSES) again to every published shader of a cache, from the
translator output the cache already holds (xlate/<d1>), without translating anything again. For a fix in an edit pass: the
published modules were made by its older version.

  nxs_reedit.py --cache <game>_nvn/cache [--keys K ...] [--dry-run] [--no-validate] [--workers N]

A shader is redone only when the chain of pass versions that applies to it differs from what made it (its d2); the rest of
its metadata (c1, made_from, cache.d1) is kept, cache.d2 and edits are updated, the result goes through spirv-val like
nxshader.py finish(). Shaders whose translator output is not in the cache are reported and left as they are.

A new edit version changes the cache's chain id (nxshader.chain_id), and the runtime ignores every entry of another chain: unless --keep-chain,
each entry made by the current translator (cache.translator) and front (cache.front) is published under the current chain, the redone ones and
the unchanged ones alike, and vk/CHAIN is written. Entries of another translator or front (or from before cache.front was recorded) keep their
chain: nxs_live.py --offline translates them again from their captures. Before, the unchanged entries kept the old chain while the next live
translator start wrote the new CHAIN: 389 of 1024 entries of a test cache were ignored, translated again live on Windows (stalls) and missing on
the Steam Deck, which has no translator (draws and dispatches skipped; the GPU then ran garbage indirect work until a ring reset)."""
import argparse, concurrent.futures as cf, json, os, sys, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import nxs_spv as S, nxs_refl as R, nxs_cache as C
import nxshader as N


def work(cache_root, extra_roots, keys, chain, tid, validate, dry_run):
    """the entries of keys, as main() describes; → (redone, unchanged, missing, failed, relabeled). One call per worker process: the
    entries are independent, writes are atomic and the inner stages content-addressed"""
    cache = C.Cache(cache_root)
    extra = [C.Cache(x) for x in extra_roots]
    vk = os.path.join(cache_root, 'vk')
    w = tempfile.mkdtemp(prefix='nxs_reedit_')
    redone, same, missing, failed, relabeled = [], 0, [], [], 0
    for k in keys:
        mp = os.path.join(vk, k + '.json')
        try: meta = json.load(open(mp, encoding='utf-8'))
        except Exception: continue
        cinfo = meta.get('cache') or {}
        d1 = cinfo.get('d1'); stage = meta.get('stage')
        if not d1 or meta.get('mesh'): continue
        got = cache.xlate_get(d1, count=False)
        if not got:
            for e in extra:
                got = e.xlate_get(d1, count=False)
                if got:
                    if not dry_run: cache.xlate_put(d1, got[0], got[1])
                    break
        if not got: missing.append(k); continue
        spv, res = got
        m = S.Module(spv)
        m.fetch1d_vars = R.fetch1d_vars(m, stage, res)
        passes = [p for p in S.DEFAULT_PASSES if p.applies(m, stage)]
        d2 = C.sha('final', d1, *[p.ident() for p in passes], 'reflect', C.REFLECT_VERSION, 'validate', validate)
        current = chain is not None and cinfo.get('translator') == tid and cinfo.get('front') == N.FRONT_VERSION   # made by the current translator and front
        if d2 == cinfo.get('d2'):
            same += 1
            if current and cinfo.get('chain') != chain:
                meta['cache'] = dict(cinfo, chain=chain); relabeled += 1
                if not dry_run: C.atomic_write(mp, json.dumps(meta, indent=1))
            continue
        try:
            hit = cache.final_get(d2)
            if hit: fspv, fmeta = hit
            else:
                applied = [p.ident() for p in passes if p.run(m, stage)]
                fspv = m.bytes()
                fmeta = R.reflect(k, stage, S.Module(fspv), res)
                fmeta['edits'] = applied
                if getattr(m, 'first_stores', None):
                    by = {b['binding']: b for b in fmeta['bindings']}
                    bindof = lambda v: m.deco(v, S.DecBinding)[0]
                    fmeta['first_store'] = [{'reg': by[bindof(f['var'])]['nvn']['reg'], 'word': f['word'], 'value': f['value']} for f in m.first_stores]
                if validate:
                    vp = os.path.join(w, k + '.final.spv'); open(vp, 'wb').write(fspv)
                    fmeta['spirv_val'] = N.spirv_val(vp)
                if not dry_run: cache.final_put(d2, fspv, fmeta)
            old = open(os.path.join(vk, k + '.spv'), 'rb').read() if os.path.exists(os.path.join(vk, k + '.spv')) else b''
            if fspv == old:   # the edits give the same module: leave the published one as it is (its chain follows the current tools)
                same += 1
                if current and cinfo.get('chain') != chain:
                    meta['cache'] = dict(cinfo, chain=chain, d2=d2); relabeled += 1
                    if not dry_run: C.atomic_write(mp, json.dumps(meta, indent=1))
                continue
            out = dict(fmeta)
            for x in ('c1', 'made_from'):
                if x in meta: out[x] = meta[x]
            out['cache'] = dict(cinfo, d2=d2, **({'chain': chain} if current else {}))
            if not dry_run: cache.publish(k, fspv, out)
            redone.append((k, out.get('edits'), out.get('spirv_val')))
        except Exception as e:
            failed.append((k, str(e)[:200]))
    return redone, same, missing, failed, relabeled


def main():
    ap = argparse.ArgumentParser(); ap.add_argument('--cache', required=True); ap.add_argument('--keys', nargs='*')
    ap.add_argument('--dry-run', action='store_true'); ap.add_argument('--no-validate', action='store_true')
    ap.add_argument('--extra-xlate', nargs='*', default=[], help='other caches (read only) to take a missing translator output from; it is copied into --cache')
    ap.add_argument('--xlate', default=os.path.join(HERE, 'xlate_bin')); ap.add_argument('--dotnet', default='dotnet')
    ap.add_argument('--keep-chain', action='store_true', help='leave every chain id as it is (the former behaviour)')
    ap.add_argument('--workers', type=int, default=max(1, min(8, (os.cpu_count() or 2) // 2)), help='processes (the entries are split between them)')
    a = ap.parse_args()
    chain = tid = None
    if not a.keep_chain:
        xl = N.F.Translator(a.xlate, a.dotnet); chain, tid = N.chain_id(xl), xl.id
    C.Cache(a.cache)
    vk = os.path.join(a.cache, 'vk')
    keys = a.keys or sorted(f[:-5] for f in os.listdir(vk) if f.endswith('.json') and len(f) == 21)
    n = max(1, min(a.workers, len(keys) // 64 or 1))
    args = [(a.cache, a.extra_xlate, keys[i::n], chain, tid, not a.no_validate, a.dry_run) for i in range(n)]
    if n == 1:
        parts = [work(*args[0])]
    else:
        with cf.ProcessPoolExecutor(n) as pool: parts = list(pool.map(work, *zip(*args)))
    redone = [r for p in parts for r in p[0]]; same = sum(p[1] for p in parts); missing = [x for p in parts for x in p[2]]
    failed = [x for p in parts for x in p[3]]; relabeled = sum(p[4] for p in parts)
    if chain and not a.dry_run and not failed: C.Cache(a.cache).set_chain(chain)
    print('published %d, redone %d, unchanged %d, no translator output %d, failed %d; %d put under chain %s (%d processes)' % (len(keys), len(redone), same, len(missing), len(failed), relabeled, chain, n))
    for r in redone[:40]: print('  redone', r)
    for f in failed[:20]: print('  FAILED', f)

if __name__ == '__main__':
    main()
