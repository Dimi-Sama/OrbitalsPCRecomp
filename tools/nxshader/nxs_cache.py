"""The versioned shader cache (research/01 lesson 2). Content-addressed, in two stages, so a change invalidates exactly what it affects:
  xlate/<d1>.spv.z + .res.json   d1 = sha256(translator identity, the job: code bytes, c1, answer-table facts, translation options)
  final/<d2>.spv.z + .json       d2 = sha256(d1, the name, version and options of every edit that applied to this shader, the reflection's version)
  vk/<key>.spv + <key>.json      what the runtime loads, by shader key; the json carries the chain id, d1, d2 and the inputs it was made from
  vk/CHAIN                       the chain id of the current tools (translator, edits, reflection): an entry whose chain differs is stale
A translator rebuild changes d1 for every shader; a new version of one edit changes d2 only for the shaders it applies to (vertex outputs: vertex and geometry
shaders); new facts for one shader change that shader's d1. The two inner stages are zlib-compressed (the translator's debug-mode SPIR-V shrinks about
fivefold), the runtime's view is plain. Writes go through a temporary file and a rename, so a killed run leaves no half entry; `gc` drops the inner entries
no published shader refers to (older generations)."""
import hashlib, json, os, time, zlib
from contextlib import contextmanager

LAYOUT = 'nxshader-cache 2'   # 2: compressed inner stages
REFLECT_VERSION = 4   # Include image and texel buffer handles kept in a uniform buffer.
SHARING_DELAYS = (0.005, 0.01, 0.02, 0.04, 0.08, 0.15)


def sha(*parts):
    h = hashlib.sha256()
    for p in parts: h.update(p if isinstance(p, (bytes, bytearray)) else str(p).encode()); h.update(b'\0')
    return h.hexdigest()


def sharing_violation(error):
    # CRT open() can report only PermissionError for a Windows sharing violation.
    return os.name == 'nt' and isinstance(error, PermissionError) and getattr(error, 'winerror', None) in (None, 5, 32, 33)


def retry_shared_file(operation):
    for delay in SHARING_DELAYS:
        try:
            return operation()
        except PermissionError as error:
            if not sharing_violation(error):
                raise
            time.sleep(delay)
    return operation()


def read_shared_file(path, encoding=None, *, limit=-1):
    def read():
        with open(path, 'rb' if encoding is None else 'r', encoding=encoding) as stream:
            return stream.read(limit)
    return retry_shared_file(read)


@contextmanager
def prewarm_lock(root):
    """Keep two offline writers from targeting the same cache, including across chain changes."""
    os.makedirs(root, exist_ok=True)
    with open(os.path.join(root, '.prewarm.lock'), 'a+b') as lock:
        lock.seek(0)
        try:
            if os.name == 'nt':
                import msvcrt
                msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as error:
            raise RuntimeError(f'could not lock cache for prewarm: {error}') from error
        yield


def atomic_write(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + '.tmp-%d' % os.getpid()
    try:
        with open(tmp, 'wb') as f: f.write(data if isinstance(data, (bytes, bytearray)) else data.encode('utf-8'))
        # A Windows reader or scanner can briefly deny renaming an existing cache entry.
        retry_shared_file(lambda: os.replace(tmp, path))
    except BaseException:
        try: os.unlink(tmp)
        except OSError: pass
        raise


class Cache:
    def __init__(self, root):
        self.root = root
        os.makedirs(root, exist_ok=True)
        lp = os.path.join(root, 'LAYOUT')
        try:
            layout = read_shared_file(lp, 'ascii').strip()
        except FileNotFoundError:
            atomic_write(lp, LAYOUT + '\n')
        else:
            if layout != LAYOUT:
                raise RuntimeError(f'{root}: cache layout {layout!r}, this nxshader writes {LAYOUT!r} (select another folder)')
        self.stats = {'xlate hit': 0, 'xlate miss': 0, 'final hit': 0, 'final miss': 0}

    def _p(self, kind, d, ext): return os.path.join(self.root, kind, d[:2], d + ext)

    def _get(self, kind, d, side):
        s, j = self._p(kind, d, '.spv.z'), self._p(kind, d, side)
        if not (os.path.exists(s) and os.path.exists(j)): return None
        try:
            spv = zlib.decompress(read_shared_file(s))
            meta = json.loads(read_shared_file(j, 'utf-8'))
        except (FileNotFoundError, ValueError, zlib.error):
            return None
        return (spv, meta) if isinstance(meta, dict) else None

    def _put(self, kind, d, side, spv, meta):
        atomic_write(self._p(kind, d, side), json.dumps(meta, indent=1))
        atomic_write(self._p(kind, d, '.spv.z'), zlib.compress(spv, 6))

    # stage 1: the translator's output
    def xlate_get(self, d1, count=True):
        r = self._get('xlate', d1, '.res.json')
        if count: self.stats['xlate hit' if r else 'xlate miss'] += 1
        return r

    def xlate_put(self, d1, spv, res): self._put('xlate', d1, '.res.json', spv, res)

    # stage 2: after the edits, with the reflection
    def final_get(self, d2):
        r = self._get('final', d2, '.json')
        self.stats['final hit' if r else 'final miss'] += 1
        return r

    def final_put(self, d2, spv, meta): self._put('final', d2, '.json', spv, meta)

    # the runtime's view
    def publish(self, key, spv, meta, variant=''):
        base = os.path.join(self.root, 'vk', key + (('.' + variant) if variant else ''))
        # A reader accepts the entry by its reflection's chain. Commit that after replacing the module.
        atomic_write(base + '.spv', spv)
        atomic_write(base + '.json', json.dumps(meta, indent=1))

    def set_chain(self, chain): atomic_write(os.path.join(self.root, 'vk', 'CHAIN'), chain + '\n')

    def lookup(self, key, chain=None):
        """the runtime's lookup: (spv, meta) when vk/<key> exists and was made by the current chain, else None"""
        base = os.path.join(self.root, 'vk', key)
        if not (os.path.exists(base + '.spv') and os.path.exists(base + '.json')): return None
        meta = json.loads(read_shared_file(base + '.json', 'utf-8'))
        if chain is None:
            cp = os.path.join(self.root, 'vk', 'CHAIN')
            chain = read_shared_file(cp, 'ascii').strip() if os.path.exists(cp) else None
        cached = meta.get('cache') if isinstance(meta, dict) else None
        if not isinstance(cached, dict) or cached.get('chain') != chain: return None
        return read_shared_file(base + '.spv'), meta

    def gc(self):
        """drop the inner entries that no published shader refers to: → (files removed, bytes freed)"""
        keep = set()
        vk = os.path.join(self.root, 'vk')
        for f in os.listdir(vk) if os.path.isdir(vk) else []:
            if f.endswith('.json'):
                c = json.load(open(os.path.join(vk, f), encoding='utf-8')).get('cache', {})
                keep |= {c.get(k) for k in ('d1', 'd1_first', 'd2')}
        n = freed = 0
        for kind in ('xlate', 'final'):
            top = os.path.join(self.root, kind)
            for sub in os.listdir(top) if os.path.isdir(top) else []:
                for f in os.listdir(os.path.join(top, sub)):
                    if f.split('.')[0] not in keep:
                        p = os.path.join(top, sub, f); freed += os.path.getsize(p); os.remove(p); n += 1
        return n, freed
