"""setup-windows.ps1 -ShaderCaptures: the prewarm targets the cache and translator options the runtime uses (text checks, nothing is run)."""
import re
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SETUP = (REPO / 'tools' / 'release' / 'setup-windows.ps1').read_text(encoding='utf-8')
HOOK = (REPO / 'runtime' / 'nvn_hook.c').read_text(encoding='utf-8', errors='replace')


def offline_call():
    return next(line for line in SETUP.splitlines() if line.lstrip().startswith('& $py ') and '--offline' in line)


class SetupPrewarmTests(unittest.TestCase):
    def test_captures_are_optional_and_gate_the_step(self):
        params = re.search(r'(?ms)^param\((.*?)^\)', SETUP).group(1)
        declaration = next(line for line in params.splitlines() if '$ShaderCaptures' in line)
        self.assertNotIn('Mandatory', declaration)
        gate = SETUP.index('if ($ShaderCaptures) {\n  Step 6')
        self.assertLess(gate, SETUP.index(offline_call()))

    def test_cache_is_the_runtime_default(self):
        self.assertIn('"NXRT_SHADER_CACHE=%s%s_nvn" SWR_SEP "cache",g_exedir,g_exename', HOOK)
        self.assertIn("-Destination (Join-Path $game 'Orbitals.exe')", SETUP)
        self.assertIn("$shaderCache = Join-Path $game 'Orbitals_nvn\\cache'", SETUP)
        self.assertIn('--cache $shaderCache', offline_call())

    def test_translator_options_match_the_live_translator(self):
        live = re.search(r'snprintf\(cmd,sizeof cmd,"([^;]*--parent[^;]*)"', HOOK).group(1)
        call = offline_call()
        for option in ('--facts', '--xlate'):
            self.assertNotIn(option, live)
            self.assertNotIn(option, call)
        self.assertIn("$captureArgs += '--dump', (Resolve-Path -LiteralPath $folder).ProviderPath", SETUP)
        self.assertIn('--offline @captureArgs', call)

    def test_incomplete_prewarm_is_not_reported_as_complete(self):
        self.assertIn("$code -eq 0 -and $finished -and $last.paired -gt 0 -and $last.failed -eq 0", SETUP)
        self.assertRegex(SETUP, r'if \(-not \$prewarmed\) \{[^}]*exit 3')


if __name__ == '__main__':
    unittest.main()
