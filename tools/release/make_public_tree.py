# Orbitals PC Recomp, a work based on SwitchRecomp by MZ Labs. GNU AGPL v3.0 with the additional terms of NOTICE.txt (LICENSE.txt).
"""Build the public tree of a release as one commit on top of the upstream history, and audit it.

  python tools/release/make_public_tree.py [--source release/v0.1] [--base origin/main] [--branch public/v0.1.0] [--dry-run]

The source branch's tree minus tools/release/public_exclude.txt becomes a single commit whose parent is --base (the upstream
Switch2RECOMP history, already public): the development history (machine names, local paths, network experiments) is not
published. Nothing is pushed. The audit refuses game files, keys, saves, caches derived from the game, logs and personal data
(audit_rules.py); a refusal stops the export with the list of paths and reasons.
"""
import argparse, fnmatch, os, subprocess, sys, tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import audit_rules

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))


def git(*a, env=None, data=None):
    r = subprocess.run(['git', *a], cwd=ROOT, env=env, input=data, capture_output=True)
    if r.returncode: raise SystemExit(f'git {" ".join(a)}: {r.stderr.decode(errors="replace").strip()}')
    return r.stdout


def excludes(ref):
    txt = git('show', f'{ref}:tools/release/public_exclude.txt').decode()
    return [l.strip() for l in txt.splitlines() if l.strip() and not l.lstrip().startswith('#')]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--source', default='release/v0.1'); ap.add_argument('--base', default='origin/main')
    ap.add_argument('--branch', default='public/v0.1.0'); ap.add_argument('--message', default=None)
    ap.add_argument('--dry-run', action='store_true')
    a = ap.parse_args()
    pats = excludes(a.source)
    files = [l.split('\t', 1) for l in git('ls-tree', '-r', '-z', '--full-tree', a.source).decode().split('\0') if l]
    keep, dropped, refused, big = [], [], [], []
    for meta, path in files:
        mode, typ, sha = meta.split()
        if typ == 'commit': refused.append((path, 'a submodule (the public tree has none)')); continue
        if any(fnmatch.fnmatch(path, p) for p in pats): dropped.append(path); continue
        why = audit_rules.name_reason(path)
        if why: refused.append((path, why)); continue
        data = git('cat-file', 'blob', sha)
        for r in audit_rules.text_reasons(path, data): refused.append((path, r))
        if len(data) > audit_rules.MAX_FILE: big.append((path, len(data)))
        keep.append((mode, sha, path))
    print(f'{a.source}: {len(files)} files, {len(keep)} kept, {len(dropped)} left out by public_exclude.txt')
    for p in dropped: print(f'  left out: {p}')
    for p, n in big: print(f'  LARGE ({n / 1048576:.1f} MB), check: {p}')
    if refused:
        print(f'REFUSED ({len(refused)}):')
        for p, r in refused: print(f'  {p}: {r}')
        raise SystemExit(1)
    if a.dry_run: return
    with tempfile.TemporaryDirectory() as td:
        env = dict(os.environ, GIT_INDEX_FILE=os.path.join(td, 'index'))
        info = ''.join(f'{m} {s}\t{p}\n' for m, s, p in keep).encode()
        git('update-index', '--index-info', env=env, data=info)
        tree = git('write-tree', env=env).decode().strip()
    src = git('rev-parse', '--short', a.source).decode().strip()
    msg = a.message or (f'Orbitals PC Recomp v0.1.0 (Developer Preview)\n\nPublic tree of {a.source} ({src}) on top of the upstream Switch2RECOMP history.\n'
                        f'Left out: {", ".join(pats)}. Audit: tools/release/make_public_tree.py.\n')
    commit = git('commit-tree', tree, '-p', a.base, data=msg.encode()).decode().strip()
    git('branch', '-f', a.branch, commit)
    print(f'{a.branch} = {commit} (tree {tree}, parent {a.base}); nothing pushed')


if __name__ == '__main__':
    main()
