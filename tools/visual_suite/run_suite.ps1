# Orbitals PC Recomp, a work based on SwitchRecomp by MZ Labs. GNU AGPL v3.0 with the additional terms of NOTICE.txt (LICENSE.txt).
# Visual suite runs: the scripted co-op path with a capture every few seconds, for each variant given, one after the other (one instance at a time).
#   & tools\visual_suite\run_suite.ps1 -From <reference run dir> -Variants 'tag|runtime exe|K=V;K=V|ini k=v;k=v' [...] [-Every 5000] [-Window 5-330]
# A variant is "tag|runtime|env|ini" (empty fields keep the reference run's). Then compare with vsuite.py compare <run A> <run B>.
param(
  [Parameter(Mandatory)][string]$From,
  [Parameter(Mandatory)][string[]]$Variants,
  [int]$Every = 5000, [string]$Window = '5-330',
  [string[]]$DropEnv = @('SWR_PROF_CALLERS', 'SWR_PROF_WINDOWS'), [string[]]$DropIni = @('profile')
)
$ErrorActionPreference = 'Stop'
$rerun = Join-Path $PSScriptRoot '..\claude_laptop\rerun.ps1'
foreach ($v in $Variants) {
  $tag, $rt, $envs, $inis = ($v -split '\|') + @('', '', '', '')
  $p = @{ From = $From; Tag = $tag; ShotWindow = @("$Window/$Every"); ShotWindowEveryMs = 0; DropEnv = $DropEnv; DropIni = $DropIni }
  if ($rt) { $p.Runtime = $rt }
  if ($envs) { $p.Env = @($envs -split ';' | Where-Object { $_ }) }
  if ($inis) { $p.Ini = @($inis -split ';' | Where-Object { $_ }) }
  Write-Host "== $tag"
  & $rerun @p | Select-Object -Last 3
}
