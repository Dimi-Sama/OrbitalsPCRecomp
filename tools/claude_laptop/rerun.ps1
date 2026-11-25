# Orbitals PC Recomp, a work based on SwitchRecomp by MZ Labs. GNU AGPL v3.0 with the additional terms of NOTICE.txt (LICENSE.txt).
# Re-run a recorded test run (its run.json) with another runtime / environment / ini, same scripted inputs, captures and length.
#   & tools\claude_laptop\rerun.ps1 -From <run dir> -Tag <tag> [-Runtime <exe>] [-Env K=V,...] [-DropEnv K,...] [-Ini k=v,...]
param(
  [Parameter(Mandatory)][string]$From,
  [Parameter(Mandatory)][string]$Tag,
  [string]$Runtime, [string]$CodeDll,
  [string[]]$Env = @(), [string[]]$DropEnv = @(), [string[]]$Ini = @(), [string[]]$DropIni = @(),
  [string[]]$ShotWindow = @(), [int]$ShotWindowEveryMs = -1,   # replace the recorded capture windows ('from-to' seconds, or 'from-to/everyms')
  [string]$Overlay, [int]$Seconds = 0, [string]$Docked = '',   # Docked: 0 / 1 replaces --docked             # a romfs overlay folder; another length (--seconds)
  [int]$TimeoutSeconds = 900
)
$ErrorActionPreference = 'Stop'
$j = Get-Content -Raw -LiteralPath (Join-Path $From 'run.json') | ConvertFrom-Json
$a = $j.args
$si = if ($a -match '--script=(\S+)') { $Matches[1] } else { '' }
$sp = if ($a -match '--script2=(\S+)') { $Matches[1] } else { '' }
$game = (($a -split ' ') | Where-Object { $_ -notmatch '^--(script2?|seconds)=' }) -join ' '
$sec = if ($a -match '--seconds=(\d+)') { [int]$Matches[1] } else { 0 }
if ($Seconds) { $sec = $Seconds }
if ($Docked -ne '') { $game = $game -replace '--docked=\d', "--docked=$Docked" }
if ($sec) { $game += " --seconds=$sec" }
$envs = @($j.env | Where-Object { $k = ($_ -split '=')[0]; $DropEnv -notcontains $k -and -not ($Env | Where-Object { ($_ -split '=')[0] -eq $k }) }) + $Env
$inis = @($j.ini | Where-Object { $k = ($_ -split '=')[0]; $DropIni -notcontains $k -and -not ($Ini | Where-Object { ($_ -split '=')[0] -eq $k }) }) + $Ini
$p = @{ Tag = $Tag; Base = $j.base; ScriptInput = $si; ScriptPad2 = $sp; IniEdits = $inis; Env = $envs; GameArgs = $game; TimeoutSeconds = $TimeoutSeconds }
$p.Runtime = if ($Runtime) { $Runtime } else { $j.runtime }
$p.CodeDll = if ($CodeDll) { $CodeDll } else { $j.dll }
if ($j.limit) { $p.Limit = [int]$j.limit }
if ($j.shots) {
  if ($j.shots.window) { $p.ShotWindow = @($j.shots.window) }
  if ($j.shots.window_every_ms) { $p.ShotWindowEveryMs = [int]$j.shots.window_every_ms }
  if ($j.shots.list) { $p.Shots = $j.shots.list }
  if ($j.shots.every) { $p.ShotEvery = [int]$j.shots.every; $p.ShotFrom = [int]$j.shots.from; $p.ShotTo = [int]$j.shots.to }
}
if ($ShotWindow.Count) { $p.ShotWindow = $ShotWindow; $p.Remove('Shots'); $p.Remove('ShotEvery'); $p.Remove('ShotFrom'); $p.Remove('ShotTo') }
if ($ShotWindowEveryMs -ge 0) { $p.ShotWindowEveryMs = $ShotWindowEveryMs }
if ($j.normal_window) { $p.NormalWindow = $true }
if ($Overlay) { $p.Overlay = $Overlay } elseif ($j.overlay) { $p.Overlay = $j.overlay }
& (Join-Path $PSScriptRoot 'run-orbitals.ps1') @p
