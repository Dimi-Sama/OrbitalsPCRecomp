# Orbitals PC Recomp, a work based on SwitchRecomp by MZ Labs. GNU AGPL v3.0 with the additional terms of NOTICE.txt (LICENSE.txt).
"""What must never reach the public repository or a release archive.

Shared by make_public_tree.py (the git tree) and package.py (the archives). Every rule names its reason, so a report says why a path was refused.
"""
import fnmatch, re

# Game files, console dumps, keys, saves, caches derived from the game, logs
FORBIDDEN_NAMES = [
    ('*.nca', 'console content archive'), ('*.nsp', 'console package'), ('*.xci', 'cartridge image'), ('*.nup', 'console update package'),
    ('*.nso', 'console executable'), ('*.nro', 'console executable'), ('*.npdm', 'console executable metadata'), ('main', 'console executable (ExeFS main)'),
    ('*.utoc', 'Unreal IoStore table (game data)'), ('*.ucas', 'Unreal IoStore container (game data)'), ('*.pak', 'Unreal package (game data)'),
    ('*.bk2', 'Bink video (game data)'), ('*.bnk', 'Wwise bank (game data)'), ('*.wem', 'Wwise audio (game data)'),
    ('prod.keys', 'console keys'), ('title.keys', 'console keys'), ('*.keys', 'console keys'),
    ('*.sav', 'save data'), ('*.gvas', 'save data'), ('*.spv', 'SPIR-V (a shader cache derived from the game)'),
    ('*.nxs', 'shader binary (derived from the game)'), ('*.hints', 'recompiler hints generated from the game code'),
    ('*_code.dll', 'recompiled game code'), ('*_code.so', 'recompiled game code'), ('Orbitals_code*', 'recompiled game code'),
    ('*.log', 'log (may hold local paths)'), ('frames.csv', 'run output'), ('telemetry.csv', 'run output'), ('*.dmp', 'crash dump'),
    ('pipelines-*.bin', 'driver pipeline cache'), ('*.pem', 'private key / certificate'), ('id_ed25519*', 'SSH key'), ('id_rsa*', 'SSH key'),
    ('*_ed25519', 'SSH key'), ('*.ppk', 'SSH key'), ('.env', 'environment secrets'),
]
FORBIDDEN_DIRS = [
    ('*/romfs/*', 'RomFS (game data)'), ('romfs/*', 'RomFS (game data)'), ('*/exefs/*', 'ExeFS (game code)'), ('exefs/*', 'ExeFS (game code)'),
    ('*_data/save/*', 'save data'), ('*/save/*', 'save data'), ('*_nvn/*', 'shader / pipeline cache derived from the game'),
    ('*/runs/*', 'test run output'), ('build/*', 'build output'), ('*/Orbitals_build/*', 'generated game code'), ('*/generated/*', 'generated code'),
]
# Text patterns: personal data of the development machines and secrets
FORBIDDEN_TEXT = [
    (re.compile(rb'[A-Za-z]:\\Users\\[^\\\s]+'), 'a Windows user profile path'),
    (re.compile(rb'(?i)[A-Za-z]:[\\/]Recomp[\\/]'), 'a development machine path'),
    (re.compile(rb'/home/(?!deck/)[a-z_][a-z0-9_-]*/'), 'a Linux home path'),   # 'deck' is every Steam Deck's own user
    (re.compile(rb'\b192\.168\.\d{1,3}\.\d{1,3}\b'), 'a local network address'),
    (re.compile(rb'(?i)\b[a-z0-9._%+-]+@(gmail|outlook|hotmail|yahoo|proton)\.[a-z]+\b'), 'a personal e-mail address'),
    (re.compile(rb'-----BEGIN [A-Z ]*PRIVATE KEY-----'), 'a private key'),
    (re.compile(rb'\bgh[pousr]_[A-Za-z0-9]{30,}\b'), 'a GitHub token'),
    (re.compile(rb'\bsk-[A-Za-z0-9_-]{20,}\b'), 'an API key'),
    (re.compile(rb'DESKTOP-[A-Z0-9]{7}'), 'a machine name'),
]
# Third-party files with an author's address in their own header: kept as their licenses require
TEXT_ALLOW = ['runtime/edenvk/*', 'tool/audio_decode/*', 'runtime/oh264/*', 'runtime/opus/*', 'runtime/spvc/*', 'runtime/vp9/*', 'runtime/bcn/*']
MAX_FILE = 16 << 20   # bigger files are listed for a human decision


def name_reason(path):
    base = path.rsplit('/', 1)[-1]
    if re.fullmatch(r'[0-9a-f]{16}\.(?:ctl|code)', base, re.IGNORECASE):
        return 'NVN2 shader capture'
    for pat, why in FORBIDDEN_NAMES:
        if fnmatch.fnmatch(base, pat): return why
    for pat, why in FORBIDDEN_DIRS:
        if fnmatch.fnmatch(path, pat): return why
    return None


def text_reasons(path, data):
    if any(fnmatch.fnmatch(path, p) for p in TEXT_ALLOW): return []
    if b'\0' in data[:8192]: return []   # binary
    out = []
    for rx, why in FORBIDDEN_TEXT:
        m = rx.search(data)
        if m:
            line = data.count(b'\n', 0, m.start()) + 1
            out.append(f'{why} (line {line}: {m.group(0)[:60].decode("utf-8", "replace")})')
    return out
