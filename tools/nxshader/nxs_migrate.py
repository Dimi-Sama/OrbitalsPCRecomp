#!/usr/bin/env python3
"""nxs_migrate: a new published shader cache from an older published one and a separately prewarmed, validated current one
(nxs_live.py --offline). Only the current cache decides what is published: each vk/<key> in it must carry the current CHAIN,
spirv_val ok and a cache.spv_sha256 its module matches. A module the old cache already publishes byte for byte is taken from
the old cache, every other one from the current cache; the metadata and CHAIN are the current ones.

  nxs_migrate.py --old <published cache> --current <validated cache> --out <new cache>

Both source caches are only read (no LAYOUT, lock or CHAIN is written to them). The new cache is assembled in a temporary
folder beside --out and renamed into place at the end, so --out either holds the whole result or does not exist."""
import argparse, hashlib, json, os, re, shutil, sys, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import nxs_cache as C

ENTRY = re.compile(r'([0-9a-f]{16})\.json')


def current_index(root):
    """Read the layout, chain and complete module names of a validated cache."""
    try:
        layout = C.read_shared_file(os.path.join(root, 'LAYOUT'), 'ascii').strip()
    except FileNotFoundError:
        layout = None
    if layout != C.LAYOUT:
        raise ValueError(f'{root}: cache layout {layout!r}, expected {C.LAYOUT!r}')
    vk = os.path.join(root, 'vk')
    chain = C.read_shared_file(os.path.join(vk, 'CHAIN'), 'ascii').strip()
    if not chain:
        raise ValueError(f'{vk}: empty CHAIN')
    names = set(os.listdir(vk)) - {'CHAIN'}
    keys = sorted(m.group(1) for m in map(ENTRY.fullmatch, names) if m)
    stray = names - {k + ext for k in keys for ext in ('.json', '.spv')}
    if stray:
        raise ValueError(f'{vk}: unexpected {sorted(stray)[0]} (a variant, or an interrupted write)')
    if not keys:
        raise ValueError(f'{vk}: no published shaders')
    return chain, keys


def validated_module(vk, key, chain):
    """Read and verify a single published shader."""
    meta = json.loads(C.read_shared_file(os.path.join(vk, key + '.json'), 'utf-8'))
    spv = C.read_shared_file(os.path.join(vk, key + '.spv'))
    cached = meta.get('cache') if isinstance(meta, dict) else None
    if not isinstance(cached, dict):
        problem = 'no cache metadata'
    elif meta.get('key') != key:
        problem = f'metadata key {meta.get("key")!r} does not match the filename'
    elif cached.get('chain') != chain:
        problem = f'chain {cached.get("chain")!r}, CHAIN is {chain!r}'
    elif meta.get('spirv_val') != 'ok':
        problem = f'spirv_val {meta.get("spirv_val")!r}'
    elif cached.get('spv_sha256') != hashlib.sha256(spv).hexdigest():
        problem = 'module does not match its spv_sha256'
    else:
        return spv, meta
    raise ValueError(f'{vk}: {key}: {problem}')


def old_module(vk, key, digest):
    """the old cache's module for key when its bytes are the validated ones, else None"""
    try:
        spv = C.read_shared_file(os.path.join(vk, key + '.spv'))
    except FileNotFoundError:
        return None
    return spv if hashlib.sha256(spv).hexdigest() == digest else None


def migrate(old, current, out):
    out = os.path.realpath(out)
    for source in (old, current):
        source = os.path.realpath(source)
        if os.path.splitdrive(source)[0].lower() == os.path.splitdrive(out)[0].lower() and os.path.commonpath([source, out]) == source:
            raise ValueError(f'{out} is inside the source cache {source}')
    if os.path.lexists(out):
        raise ValueError(f'{out} exists; choose a new destination')
    old_vk = os.path.join(old, 'vk')
    if not os.path.isdir(old_vk):
        raise ValueError(f'{old_vk}: not a published cache')
    chain, keys = current_index(current)
    current_vk = os.path.join(current, 'vk')
    counts = {'modules': len(keys), 'reused': 0, 'copied': 0}
    stage = tempfile.mkdtemp(prefix=os.path.basename(out) + '.tmp-', dir=os.path.dirname(out))
    try:
        cache = C.Cache(stage)
        for key in keys:
            spv, meta = validated_module(current_vk, key, chain)
            reused = old_module(old_vk, key, meta['cache']['spv_sha256'])
            counts['copied' if reused is None else 'reused'] += 1
            cache.publish(key, spv if reused is None else reused, meta)
        # As in a build, CHAIN is committed after the modules it accepts.
        cache.set_chain(chain)
        C.retry_shared_file(lambda: os.rename(stage, out))
    except BaseException:
        shutil.rmtree(stage, ignore_errors=True)
        raise
    return dict(counts, chain=chain)


def main():
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('--old', required=True, help='the published cache to take unchanged modules from (read only)')
    ap.add_argument('--current', required=True, help='the validated current cache (read only)')
    ap.add_argument('--out', required=True, help='the new cache; must not exist')
    a = ap.parse_args()
    try:
        r = migrate(a.old, a.current, a.out)
    except (OSError, ValueError) as error:
        print(f'[RED] nxs_migrate: {error}', file=sys.stderr)
        return 1
    print(f'{a.out}: chain {r["chain"]}, {r["modules"]} modules: {r["reused"]} reused from {a.old}, {r["copied"]} copied from {a.current}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
