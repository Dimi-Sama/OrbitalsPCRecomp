# Isolated Orbitals test run (claude-audio-perf worktree), portable: no absolute path.
#
# Layout expected (all relative to this worktree):
#   <worktree>\..\Switch2RECOMP                                   main checkout (read only)
#   <worktree>\..\Switch2Recomp-0.4.1-windows-x64\Switch2Recomp\python\python.exe
#   <worktree>\build\orbitals-debug\toolchain                     dotnet10, vulkan-bin, SDL3 (junction to the main one)
#   <Base>                                                        a playable folder: Orbitals.exe, Orbitals_code.dll,
#                                                                 Orbitals.ini, Orbitals.hints, Orbitals_nvn, Orbitals_data\save
#
# Each run gets <worktree>\build\orbitals-debug\runs\<Tag>-<stamp> with:
#   exefs / romfs as NTFS junctions to the test RomFS copy (never copied), a copy of the save,
#   the DLL hard-linked from the base (same volume; never written), the runtime copied,
#   a copy of the Vulkan and shader caches by default, a junction with -SharedCache, or an empty cache with -ColdCache.
# Nothing in the base folder or the main checkout is written, except the cache with -SharedCache.
param(
  [Parameter(Mandatory)][string]$Tag,
  [string]$Base,                                  # default: build\orbitals-debug\playable-claude-timing
  [string]$CodeDll,                               # default: <Base>\Orbitals_code.dll
  [string]$Runtime,                               # default: <Base>\Orbitals.exe
  [string]$ScriptInput = '', [string]$ScriptPad2 = '',
  [string[]]$IniEdits = @(),                      # key=value, replaced in Orbitals.ini (e.g. 'profile=1','ue_fps=0')
  [string[]]$Env = @(),                           # KEY=VALUE, extra environment variables
  [int]$Limit = 0,                                # NXRT_EXIT_AT_PRESENT (0: none)
  [int]$TimeoutSeconds = 600,
  [string]$Shots = '',                            # NXRT_VK_SHOT list of presentations
  [int]$ShotEvery = 0, [int]$ShotFrom = 0, [int]$ShotTo = 0,
  [string[]]$ShotWindow = @(),                    # 'from-to' in seconds since launch (repeatable): one capture per present
                                                  # through NXRT_VK_SHOT_FILE (present numbers differ between runs, times don't)
  [int]$ShotWindowEveryMs = 0,                    # in the windows, at most one capture every N ms (0: every present)
  [switch]$AudioDump,                             # SWR_AUDIO_DUMP=<run>\audio.f32 (float32 stereo 48 kHz)
  [switch]$Unmute,                                # default: SWR_AUDIO_MUTE=1 (silence on the device, mixer keeps running)
  [switch]$NormalWindow,                          # let the game apply fullscreen on the current monitor
  [switch]$SharedCache,
  [switch]$ColdCache,                             # start without any shader or pipeline cache
  [string]$DataRoot,                              # default: main\build\orbitals-debug\win32-vulkan-frame-task-20261118-204116742\Orbitals_data
  [string]$GameArgs = '--renderer=vulkan --fullscreen=0 --docked=1',
  [string]$Overlay                                # a folder copied to Orbitals_data\romfs_overlay (e.g. Orbitals\Saved\Config\Switch2\Engine.ini)
)
$ErrorActionPreference = 'Stop'
if ($SharedCache -and $ColdCache) { throw 'SharedCache and ColdCache are mutually exclusive.' }
$wt    = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
$root  = Split-Path -Parent $wt
$main  = Join-Path $root 'Switch2RECOMP'
$diag  = Join-Path $wt 'build\orbitals-debug'
$tc    = Join-Path $diag 'toolchain'
if (-not (Test-Path -LiteralPath $tc)) { $tc = Join-Path $main 'build\orbitals-debug\toolchain' }
$py    = Join-Path $root 'Switch2Recomp-0.4.1-windows-x64\Switch2Recomp\python\python.exe'
if (-not $Base)     { $Base = Join-Path $diag 'playable-claude-timing' }
if (-not $CodeDll)  { $CodeDll = Join-Path $Base 'Orbitals_code.dll' }
if (-not $Runtime)  { $Runtime = Join-Path $Base 'Orbitals.exe' }
if (-not $DataRoot) { $DataRoot = Join-Path $main 'build\orbitals-debug\win32-vulkan-frame-task-20261118-204116742\Orbitals_data' }
foreach ($p in $Base, $CodeDll, $Runtime, "$DataRoot\exefs", "$DataRoot\romfs", $py, "$tc\dotnet10", "$tc\vulkan-bin") {
  if (-not (Test-Path -LiteralPath $p)) { throw "missing: $p" }
}
if (Get-Process -Name Orbitals -ErrorAction SilentlyContinue) { throw 'An Orbitals instance is already running: one instance at a time.' }

$run  = Join-Path $diag ('runs\' + $Tag + '-' + (Get-Date -Format yyyyMMdd-HHmmss))
$data = Join-Path $run 'Orbitals_data'
New-Item -ItemType Directory -Path $data | Out-Null
New-Item -ItemType Junction -Path (Join-Path $run 'nxshader') -Target (Join-Path $wt 'tools\nxshader') | Out-Null
foreach ($leaf in 'exefs', 'romfs') { New-Item -ItemType Junction -Path (Join-Path $data $leaf) -Target (Join-Path $DataRoot $leaf) | Out-Null }
if ($Overlay) { Copy-Item -LiteralPath (Resolve-Path $Overlay).Path -Destination (Join-Path $data 'romfs_overlay') -Recurse }
$save = Get-Item -LiteralPath (Join-Path $Base 'Orbitals_data\save')
if (($save.Attributes -band [IO.FileAttributes]::ReparsePoint) -or (Get-ChildItem -LiteralPath $save.FullName -Recurse | Where-Object { $_.Attributes -band [IO.FileAttributes]::ReparsePoint })) { throw 'Unexpected reparse point in the save' }
Copy-Item -LiteralPath $save.FullName -Destination (Join-Path $data 'save') -Recurse

# DLL: hard link when on the same volume (373 MB, read only for the game), copy otherwise
$dllDst = Join-Path $run 'Orbitals_code.dll'
if ([IO.Path]::GetPathRoot((Resolve-Path $CodeDll).Path) -eq [IO.Path]::GetPathRoot($run)) {
  New-Item -ItemType HardLink -Path $dllDst -Target (Resolve-Path $CodeDll).Path | Out-Null
} else { Copy-Item -LiteralPath $CodeDll -Destination $dllDst }
Copy-Item -LiteralPath $Runtime -Destination (Join-Path $run 'Orbitals.exe')
foreach ($f in 'Orbitals.hints', 'SDL3.dll') { $s = Join-Path $Base $f; if (Test-Path -LiteralPath $s) { Copy-Item -LiteralPath $s -Destination $run } }
if (-not (Test-Path -LiteralPath (Join-Path $run 'SDL3.dll'))) { Copy-Item -LiteralPath (Join-Path $tc 'SDL3-3.4.16\SDL3.dll') -Destination $run }
$ini = Get-Content -Raw -LiteralPath (Join-Path $Base 'Orbitals.ini')
foreach ($kv in $IniEdits) { $k, $v = $kv -split '=', 2; $ini = $ini -replace "(?m)^$([regex]::Escape($k))=[^\r\n]*", "$k=$v" }
Set-Content -LiteralPath (Join-Path $run 'Orbitals.ini') -Value $ini -NoNewline
if ($SharedCache) { New-Item -ItemType Junction -Path (Join-Path $run 'Orbitals_nvn') -Target (Join-Path $Base 'Orbitals_nvn') | Out-Null }
elseif (!$ColdCache -and (Test-Path -LiteralPath (Join-Path $Base 'Orbitals_nvn'))) { Copy-Item -LiteralPath (Join-Path $Base 'Orbitals_nvn') -Destination (Join-Path $run 'Orbitals_nvn') -Recurse }

$si = New-Object System.Diagnostics.ProcessStartInfo
$si.FileName = Join-Path $run 'Orbitals.exe'; $si.WorkingDirectory = $run
$a = $GameArgs
if ($ScriptInput) { $a += ' --script=' + $ScriptInput }
if ($ScriptPad2)  { $a += ' --script2=' + $ScriptPad2 }
$si.Arguments = $a
$si.UseShellExecute = $false; $si.CreateNoWindow = $true
$si.RedirectStandardError = $true; $si.RedirectStandardOutput = $true
$ce = $si.EnvironmentVariables
$ce['SWR_GPU'] = 'nvn'; $ce['NXRT_GFX'] = 'vulkan'; $ce['SWR_PYTHON'] = $py
if ($NormalWindow) { $ce.Remove('SWR_PORTRAIT_WINDOW') } else { $ce['SWR_PORTRAIT_WINDOW'] = '1' }
$ce['DOTNET_ROOT'] = "$tc\dotnet10"; $ce['NXSHADER_TOOLS'] = "$tc\vulkan-bin"
$ce['PATH'] = "$tc\dotnet10;$tc\vulkan-bin;$($ce['PATH'])"
$scratch = (New-Item -ItemType Directory -Path (Join-Path $run 'tmp')).FullName
$ce['TEMP'] = $scratch; $ce['TMP'] = $scratch
$ce['NXRT_VK_SHOT_DIR'] = Join-Path $run 'frames'
if (-not $Unmute) { $ce['SWR_AUDIO_MUTE'] = '1' }
if ($AudioDump)  { $ce['SWR_AUDIO_DUMP'] = Join-Path $run 'audio.f32' }
if ($Limit)      { $ce['NXRT_EXIT_AT_PRESENT'] = "$Limit" }
if ($Shots)      { $ce['NXRT_VK_SHOT'] = $Shots }
if ($ShotEvery)  { $ce['NXRT_VK_SHOT_EVERY'] = "$ShotEvery" }
if ($ShotFrom)   { $ce['NXRT_VK_SHOT_FROM'] = "$ShotFrom" }
if ($ShotTo)     { $ce['NXRT_VK_SHOT_TO'] = "$ShotTo" }
$ctl = Join-Path $run 'shot-request.txt'
if ($ShotWindow.Count) { $ce['NXRT_VK_SHOT_FILE'] = $ctl }
foreach ($kv in $Env) { $k, $v = $kv -split '=', 2; $ce[$k] = $v }
@{ tag = $Tag; overlay = $Overlay; base = $Base; dll = (Resolve-Path $CodeDll).Path; runtime = (Resolve-Path $Runtime).Path; args = $a; env = $Env; ini = $IniEdits
   normal_window = $NormalWindow.IsPresent; cold_cache = $ColdCache.IsPresent
   shots = @{ list = $Shots; every = $ShotEvery; from = $ShotFrom; to = $ShotTo; window = $ShotWindow; window_every_ms = $ShotWindowEveryMs }; limit = $Limit; started = (Get-Date -Format o)
   machine = $env:COMPUTERNAME } | ConvertTo-Json -Depth 4 | Set-Content -LiteralPath (Join-Path $run 'run.json')

$t0 = Get-Date
$p = [System.Diagnostics.Process]::Start($si)
$errTask = $p.StandardError.ReadToEndAsync(); $outTask = $p.StandardOutput.ReadToEndAsync()
$status = 'exit'
$exited = $false
if ($ShotWindow.Count) {
  # the runtime takes one shot at the next present when the control file exists, then deletes it: recreate it at once
  # 'from-to' or 'from-to/ms' (a step of its own for this window)
  $win = New-Object System.Collections.Generic.List[double[]]
  foreach ($x in $ShotWindow) { $r, $st = $x -split '/', 2; $a0, $a1 = $r -split '-', 2
    $win.Add([double[]]@([double]$a0, [double]$a1, $(if ($st) { [double]$st } else { [double]$ShotWindowEveryMs }))) }
  $sw = [Diagnostics.Stopwatch]::StartNew(); $last = -1e9
  while (-not $p.HasExited -and $sw.Elapsed.TotalSeconds -lt $TimeoutSeconds) {
    $s = $sw.Elapsed.TotalSeconds
    $w = $null; foreach ($x in $win) { if ($s -ge $x[0] -and $s -le $x[1]) { $w = $x; break } }
    if ($w -and ($s - $last) * 1000 -ge $w[2] -and -not [IO.File]::Exists($ctl)) {
      [IO.File]::WriteAllText($ctl, ''); $last = $s }
    Start-Sleep -Milliseconds 4
  }
  $exited = $p.HasExited
}
if (-not $exited -and -not $p.WaitForExit([math]::Max(1, $TimeoutSeconds * 1000 - $(if ($sw) { [int]$sw.Elapsed.TotalMilliseconds } else { 0 })))) {
  $status = 'timeout'
  if (!$p.CloseMainWindow() -or !$p.WaitForExit(5000)) {
    if (!$p.HasExited) { $p.Kill() }
    if (!$p.WaitForExit(15000)) { throw "The timed out test process $($p.Id) did not exit." }
  }
}
$p.WaitForExit()
Set-Content -LiteralPath (Join-Path $run 'stderr.txt') -Value ($errTask.Result + $outTask.Result) -Encoding utf8
Remove-Item -LiteralPath $dllDst -ErrorAction SilentlyContinue      # the hard link only: the base DLL stays
if ((Resolve-Path -LiteralPath $scratch).Path -eq (Join-Path $run 'tmp')) {
  Remove-Item -LiteralPath $scratch -Recurse -ErrorAction SilentlyContinue
}
"run=$run status=$status exit=$($p.ExitCode) seconds=$([int]((Get-Date) - $t0).TotalSeconds)"
