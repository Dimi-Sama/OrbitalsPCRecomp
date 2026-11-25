#!/usr/bin/env python3
# SwitchRecomp - Copyright 2026 MZ Labs
# Licensed under the GNU Affero General Public License v3.0, see LICENSE.txt and NOTICE.txt.
# Forks and derived works have to keep the credit to SwitchRecomp by MZ Labs and the startup screen.
"""nxs_live: shaders translated while the game runs (renderer=vulkan), with no build step before.

The runtime starts this once. The NVN layer (gfx/nxs_rt.c) writes each shader it has no translation for into the dump
folder (<key>.ctl, <key>.code) and looks for <key> in the cache twice a second. This loop picks up new dumps, translates
every one found in a batch with one run of nxnative's translator (dmsh_xlate: Ryujinx's shader translator, which reads
Switch 2 Ampere code itself), applies the same edits and reflection as nxshader.py and publishes into the cache. Vulkan
can wait for the requested shaders before drawing, up to NXRT_SHADER_WAIT_MS.

  nxs_live.py --dump DIR --cache DIR [--xlate DIR] [--dotnet dotnet] [--facts shader_facts.tsv] [--parent PID | --offline]
  --offline validates and prewarms captured NVN2 shaders before a session, emitting JSON progress on stdout.
  Repeat --dump offline to combine captures from multiple sessions."""
import argparse, hashlib, json, os, re, shutil, struct, subprocess, sys, tempfile, time, traceback
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager

# The launcher exposes nxshader through a junction in each session. Resolve it before
# importing modules that locate the runtime headers relative to the source tree.
HERE = os.path.dirname(os.path.realpath(__file__))
sys.path.insert(0, HERE)
import nxs_front as F, nxs_cache as C, nxshader as N

SPH_STAGE = {1: 'vs', 2: 'hs', 3: 'ds', 4: 'gs', 5: 'ps'}
DUMP_NAME = re.compile(r'([0-9a-f]{16})\.(ctl|code)')


def stage_of(ctl, code):
    """nxnative shader_split.py nvn2_stage / sph_stage (MIT): compute, task and mesh by the control's stage byte (+0x56),
    else the graphics SPH word 0 of the code area"""
    if F.dmsh_ampere.is_nvn2(ctl) and len(ctl) > 0x56 and ctl[0x56] in (5, 6, 7): return {5: 'cs', 6: 'ts', 7: 'ms'}[ctl[0x56]]
    if len(code) < 4: return None
    w = struct.unpack_from('<I', code, 0)[0] if F.dmsh_ampere.is_nvn2(ctl) else (struct.unpack_from('<I', code, 0x30)[0] if len(code) >= 0x34 else 0)
    if (w >> 10) & 0xf == 0 and w & 0x1f == 1: return 'vs'
    return SPH_STAGE.get((w >> 10) & 0xf) or ('cs' if not F.dmsh_ampere.is_nvn2(ctl) and code[:4] == bytes.fromhex('79563412') else None)


def verify_nvn2_dump(key, ctl, code):
    if len(ctl) not in (0xe0, 0x880) or not F.dmsh_ampere.is_nvn2(ctl):
        raise ValueError('expected an NVN2 control block')
    inst_len, padded_len, code_len = struct.unpack_from('<I4xII', ctl, 0x38)
    if not 0 < inst_len <= padded_len <= code_len == len(code) < (1 << 24):
        raise ValueError('invalid NVN2 code lengths')
    # Match the runtime's default NVN2 key in keys_hash, with the control size field zeroed.
    digest = hashlib.sha256(ctl[:0x30] + bytes(4) + ctl[0x34:0x48])
    digest.update(code)
    if digest.hexdigest()[:16] != key:
        raise ValueError('file name does not match the NVN2 shader key')


class DumpCorpus:
    """nxs_front.Corpus over the runtime's dumps: a record is 0x38 header bytes, the code area, the control section"""
    def __init__(self, dump, facts_path=None, *, verify_keys=False, paired_folders=None):
        self.dump = dump
        self.verify_keys = verify_keys
        self.paired_folders = paired_folders
        self.facts_raw, self.facts, self.source = {}, {}, {}
        if facts_path and os.path.isfile(facts_path):
            with open(facts_path, encoding='utf-8') as stream:
                for line in stream:
                    if line.strip() and not line.startswith('#'):
                        k, v = line.rstrip('\r\n').split('\t', 1)
                        self.facts_raw[k] = v; self.facts[k] = json.loads(v)
        self.stage = {}

    def read_pair(self, folder, key):
        ctl = C.read_shared_file(os.path.join(folder, key + '.ctl'), limit=0x881 if self.verify_keys else -1)
        code = C.read_shared_file(os.path.join(folder, key + '.code'), limit=1 << 24 if self.verify_keys else -1)
        if self.verify_keys:
            verify_nvn2_dump(key, ctl, code)
        if F.dmsh_ampere.is_nvn2(ctl): ctl = ctl[:0xe0]
        return ctl, code

    def record(self, key):
        primary, *duplicates = self.paired_folders[key] if self.paired_folders is not None else (self.dump,)
        ctl, code = self.read_pair(primary, key)
        for folder in duplicates:
            other_ctl, other_code = self.read_pair(folder, key)
            if other_code != code or other_ctl[:0x30] != ctl[:0x30] or other_ctl[0x34:] != ctl[0x34:]:
                raise ValueError('conflicting completed capture pairs for this shader key')
        st = stage_of(ctl, code)
        if not st: raise ValueError('a shader of no known stage')
        self.stage[key] = st
        return st + '_live.bin', bytes(0x38) + code + ctl


@contextmanager
def watch_parent(pid):
    if not pid:
        yield lambda: True
        return
    if os.name != 'nt':
        def alive():
            try:
                os.kill(pid, 0)
            except ProcessLookupError:
                return False
            except PermissionError:
                pass
            return True
        yield alive
        return

    import ctypes
    from ctypes import wintypes
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.OpenProcess.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
    kernel.OpenProcess.restype = wintypes.HANDLE
    kernel.WaitForSingleObject.argtypes = (wintypes.HANDLE, wintypes.DWORD)
    kernel.WaitForSingleObject.restype = wintypes.DWORD
    kernel.CloseHandle.argtypes = (wintypes.HANDLE,)
    handle = kernel.OpenProcess(0x00100000, False, pid)  # SYNCHRONIZE
    if not handle:
        raise ctypes.WinError(ctypes.get_last_error())

    def alive():
        result = kernel.WaitForSingleObject(handle, 0)
        if result == 0xFFFFFFFF:  # WAIT_FAILED
            raise ctypes.WinError(ctypes.get_last_error())
        return result == 0x102  # WAIT_TIMEOUT

    try:
        yield alive
    finally:
        kernel.CloseHandle(handle)


def prewarm(a):
    started = time.monotonic()

    def progress(phase, **fields):
        print(json.dumps({'phase': phase, **fields}), flush=True)

    counts = {'discovered': 0, 'paired': 0, 'prepared': 0, 'reused': 0, 'failed': 0}
    progress('analysis')
    try:
        discovered, paired_folders = set(), {}
        for folder in dict.fromkeys(os.path.realpath(path) for path in a.dump):
            files = {}
            for name in os.listdir(folder):
                match = DUMP_NAME.fullmatch(name)
                if match:
                    key, ext = match.groups()
                    files.setdefault(key, set()).add(ext)
            discovered.update(files)
            for key, extensions in files.items():
                if len(extensions) == 2:
                    paired_folders.setdefault(key, []).append(folder)
        keys = sorted(paired_folders)
        counts.update(discovered=len(discovered), paired=len(keys), failed=len(discovered) - len(keys))
        progress('analysis', **counts)
        for key in sorted(discovered - paired_folders.keys()):
            progress('shader_error', key=key, status='incomplete capture')
        if keys:
            if a.facts and not os.path.isfile(a.facts):
                raise FileNotFoundError(a.facts)
            corpus = DumpCorpus(None, a.facts, verify_keys=True, paired_folders=paired_folders)
            for name in ('spirv-val', 'spirv-opt'):
                if not N.vk_tool(name):
                    raise RuntimeError(f'{name} is required (set NXSHADER_TOOLS)')
            xl = F.Translator(a.xlate, a.dotnet)
            with (C.prewarm_lock(a.cache), tempfile.TemporaryDirectory(prefix='nxs_prewarm_') as work,
                  ThreadPoolExecutor(a.jobs) as pool):
                cache = C.Cache(a.cache)
                builder = N.Builder(corpus, cache, xl, work, require_valid=True)
                chain_file = os.path.join(a.cache, 'vk', 'CHAIN')
                try:
                    chain = C.read_shared_file(chain_file, 'ascii').strip()
                except FileNotFoundError:
                    cache.set_chain(builder.chain)
                else:
                    if chain != builder.chain:
                        raise RuntimeError('cache belongs to another shader chain; select a fresh cache directory')
                progress('cache', chain=builder.chain)
                for start in range(0, len(keys), a.batch):
                    batch = keys[start:start + a.batch]
                    results = builder.make(batch, pool if a.jobs > 1 else None)
                    for key in batch:
                        result = results[key]
                        status = result['status']
                        if status == 'ok':
                            counts['prepared'] += 1
                        elif status == 'reused':
                            counts['reused'] += 1
                        else:
                            counts['failed'] += 1
                            progress('shader_error', key=key, status=status, error=result.get('error'))
                    progress('translation', **counts)
    except KeyboardInterrupt:
        progress('interrupted', **counts)
        return 130
    except (OSError, RuntimeError, ValueError, subprocess.SubprocessError) as error:
        progress('error', error=str(error), **counts)
        return 1
    progress('finished', elapsed_seconds=round(time.monotonic() - started, 3), **counts)
    return 2 if counts['failed'] else 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--dump', required=True, action='append'); ap.add_argument('--cache', required=True)
    ap.add_argument('--xlate', default=os.path.join(HERE, 'xlate_bin')); ap.add_argument('--dotnet', default='dotnet')
    ap.add_argument('--facts'); ap.add_argument('--parent', type=int, default=0); ap.add_argument('--batch', type=int, default=48)
    ap.add_argument('--offline', action='store_true', help='prewarm a cache from completed NVN2 captures and exit')
    ap.add_argument('--since', type=int, default=0, help='ignore dumps older than this Unix timestamp')
    ap.add_argument('--jobs', type=int, default=min(3, os.cpu_count() or 1), choices=range(1, 5))
    a = ap.parse_args()
    if a.batch < 1:
        ap.error('--batch must be positive')
    if a.offline:
        if a.parent or a.since:
            ap.error('--offline cannot be used with --parent or --since')
        return prewarm(a)
    if len(a.dump) != 1:
        ap.error('multiple --dump folders require --offline')
    a.dump = a.dump[0]
    os.makedirs(a.dump, exist_ok=True); os.makedirs(os.path.join(a.cache, 'vk'), exist_ok=True)
    log = open(os.path.join(a.cache, 'nxs_live.log'), 'a', buffering=1)
    say = lambda s: log.write(time.strftime('%H:%M:%S ') + s + '\n')
    try: xl = F.Translator(a.xlate, a.dotnet)
    except Exception as e: say('no translator: %s (.NET 10 runtime installed?)' % e); return 1
    cache = C.Cache(a.cache)
    w = tempfile.mkdtemp(prefix='nxs_live_')
    b = N.Builder(DumpCorpus(a.dump, a.facts), cache, xl, w, validate=False)
    vk = os.path.join(a.cache, 'vk')
    try:
        with open(os.path.join(vk, 'CHAIN'), encoding='ascii') as f:
            same_chain = f.read().strip() == b.chain
    except (OSError, UnicodeError):
        same_chain = False
    if not same_chain:
        cache.set_chain(b.chain)
    say('ready: translator %s, chain %s, dumps %s' % (xl.id, b.chain, a.dump))
    done = set()
    for name in os.listdir(vk) if same_chain else ():
        if not name.endswith('.json') or len(name) != 21:
            continue
        key = name[:-5]
        try:
            if cache.lookup(key, b.chain): done.add(key)
        except (OSError, ValueError):
            pass   # An interrupted publish can be replaced from its dump.
    failed, retry = {}, {}
    last_write = None
    rescan_at = 0.0
    try:
        with watch_parent(a.parent) as parent_alive, ThreadPoolExecutor(a.jobs) as pool:
            while parent_alive():
                now = time.monotonic()
                updated = os.stat(a.dump).st_mtime_ns
                if updated == last_write and now < rescan_at:
                    time.sleep(0.05)
                    continue
                # The runtime publishes new dump files by rename. Also rescan older filesystems with coarse timestamps.
                last_write, rescan_at = updated, now + 0.5
                pending = {}
                for name in os.listdir(a.dump):
                    if not name.endswith('.ctl') or len(name) != 20 or name[:-4] in done:
                        continue
                    key = name[:-4]
                    try:
                        stamp = os.stat(os.path.join(a.dump, name)).st_mtime_ns
                    except FileNotFoundError:
                        continue
                    # The live renderer republishes the dump for every cache miss it needs this session.
                    if stamp // 1_000_000_000 >= a.since and failed.get(key) != stamp and os.path.isfile(os.path.join(a.dump, key + '.code')):
                        retry_stamp, _, retry_at = retry.get(key, (0, 0, 0))
                        if retry_stamp == stamp and now < retry_at:
                            rescan_at = min(rescan_at, retry_at)
                            continue
                        pending[key] = stamp
                if not pending: time.sleep(0.05); continue
                # New requests from the renderer take precedence over a backlog after a cache change.
                # Rescan after each batch so a request never waits for the entire backlog to finish.
                part = sorted(pending, key=lambda key: (-pending[key], key))[:a.batch]
                rescan_at = 0.0
                t0 = time.monotonic()
                try: out = b.make(part, pool if a.jobs > 1 else None)
                except Exception: say(traceback.format_exc()); out = {k: {'status': 'failed'} for k in part}
                ok = [k for k, r in out.items() if r.get('status') == 'ok']
                deferred = 0
                for k, r in out.items():
                    if r.get('status') == 'ok':
                        done.add(k)
                    elif r.get('status') == 'file busy':
                        old_stamp, count, _ = retry.get(k, (0, 0, 0))
                        count = count if old_stamp == pending[k] else 0
                        if count < 8:
                            retry[k] = (pending[k], count + 1, time.monotonic() + min(0.1 * (2 ** count), 0.8))
                            if not count:
                                say('%s: cache file temporarily busy; retrying' % k)
                            deferred += 1
                            continue
                        failed[k] = pending[k]
                        say('%s: %s %s' % (k, r['status'], r.get('error', '')))
                    else:
                        failed[k] = pending[k]
                        say('%s: %s %s' % (k, r.get('status'), r.get('error', '')))
                    retry.pop(k, None)
                say('%d translated in %.2f s (%d failed, %d deferred)' %
                    (len(ok), time.monotonic() - t0, len(part) - len(ok) - deferred, deferred))
    except OSError as e:
        say('live translator stopped: %s' % e)
        return 1
    finally: shutil.rmtree(w, ignore_errors=True)
    return 0


if __name__ == '__main__':
    sys.exit(main())
