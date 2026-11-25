# Orbitals PC Recomp, a work based on SwitchRecomp by MZ Labs. GNU AGPL v3.0 with the additional terms of NOTICE.txt (LICENSE.txt).
# Orbitals PC Recomp: build a playable Windows folder from YOUR OWN copy of the game (BUILDING.md, "Windows: one command").
#
#   powershell -ExecutionPolicy Bypass -File tools\release\setup-windows.ps1 -GameData D:\MyDump\Orbitals [-InstallDir games] [-Jobs 4] [-CopyData]
#        [-ShaderCaptures "D:\My Captures\nvn2"]
#
# -GameData  a folder with exefs\ (main, main.npdm, sdk, ...) and romfs\ extracted from a copy you own. Nothing is read from anywhere else and
#            nothing of the game is downloaded.
# -ShaderCaptures  optional: folders of NVN2 shader captures (<key>.ctl + <key>.code, e.g. earlier sessions' Orbitals_nvn\cache\dumps)
#            translated into the game's shader cache as a last step (docs\SHADER_PREWARM.md). Without it nothing changes.
# Steps, each skipped when its result is already there:
#   1. Python + GCC (C) into this repository          Install.bat (Switch2Recomp's, no admin rights)
#   2. g++, SPIRV-Tools, glslang, .NET 10, SDL3        tools\release\get_orbitals_deps.py -> <InstallDir>\toolchain (pinned SHA-256)
#   3. the Vulkan layer and the Win32 runtime          tools\build_nvn.py, switchrecomp.py --build-runtime   -> bin\runtime_win64_win32.exe
#   4. the game's code recompiled                      switchrecomp.py <GameData> -o Orbitals                 -> <InstallDir>\Orbitals (20-60 min)
#   5. the folder completed                            SDL3.dll, the live shader translator, the launch script
#   6. (-ShaderCaptures only) shader cache prewarm     tools\nxshader\nxs_live.py --offline                   -> <InstallDir>\Orbitals\Orbitals_nvn\cache
#      Always run; existing entries are reused. Exit code 3 when the folder is ready but the prewarm did not complete.
# By default exefs\ and romfs\ are linked (NTFS junctions), not copied (romfs is ~10 GB): keep -GameData where it is, or pass -CopyData.
param(
  [Parameter(Mandatory)][string]$GameData,
  [string]$InstallDir,
  [int]$Jobs = 4,
  [switch]$CopyData,
  [switch]$RebuildRuntime,
  [switch]$RebuildCode,
  [switch]$Rebuild,
  [string[]]$ShaderCaptures
)
$ErrorActionPreference = 'Stop'
$repo = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
if (-not $InstallDir) { $InstallDir = Join-Path $repo 'games' }
$GameData = (Resolve-Path -LiteralPath $GameData).Path
foreach ($need in 'exefs\main', 'exefs\main.npdm', 'romfs') {
  if (-not (Test-Path -LiteralPath (Join-Path $GameData $need))) { throw "$GameData\$need is missing: -GameData must hold exefs\ and romfs\ from your copy of the game" }
}
$steps = 5
$captureArgs = @()
if ($ShaderCaptures) {   # checked before the long steps; a native program gets plain file system paths
  foreach ($folder in $ShaderCaptures) {
    if (-not (Test-Path -LiteralPath $folder -PathType Container)) { throw "-ShaderCaptures $folder is not a folder: pass the folders holding the <key>.ctl and <key>.code captures" }
    $captureArgs += '--dump', (Resolve-Path -LiteralPath $folder).ProviderPath
  }
  $steps = 6
}
New-Item -ItemType Directory -Force -Path $InstallDir | Out-Null
$InstallDir = (Resolve-Path -LiteralPath $InstallDir).Path
$game = Join-Path $InstallDir 'Orbitals'
$tc = Join-Path $InstallDir 'toolchain'
$py = Join-Path $repo 'python\python.exe'
$gbin = Join-Path $repo 'gcc\Library\bin'
function Step($n, $what) { Write-Host ""; Write-Host "[$n/$steps] $what" -ForegroundColor Cyan }
function Check($what) { if ($LASTEXITCODE) { throw "$what failed (exit code $LASTEXITCODE)" } }

Step 1 'Python and GCC'
if (-not (Test-Path -LiteralPath $py) -or -not (Test-Path -LiteralPath (Join-Path $gbin 'x86_64-w64-mingw32-gcc.exe'))) {
  Push-Location $repo; try { & "$env:ComSpec" /d /c "`"$(Join-Path $repo 'Install.bat')`"" } finally { Pop-Location }   # absolute path: the process' working folder is not PowerShell's location
  if (-not (Test-Path -LiteralPath $py)) { throw 'Install.bat did not leave python\python.exe' }
} else { Write-Host '  already there' }

Step 2 'g++, SPIRV-Tools, glslang, .NET 10 runtime, SDL3'
if ($Rebuild -or -not (Test-Path -LiteralPath (Join-Path $tc 'VERSIONS.txt')) -or -not (Test-Path -LiteralPath (Join-Path $gbin 'x86_64-w64-mingw32-g++.exe'))) {
  & $py -B -I (Join-Path $repo 'tools\release\get_orbitals_deps.py') --toolchain $tc; Check 'get_orbitals_deps.py'
} else { Write-Host '  already there' }

Step 3 'Vulkan layer and runtime'
$env:PATH = "$gbin;$tc\vulkan-bin;$env:PATH"
$env:VULKAN_SDK = Join-Path $repo 'runtime\edenvk\deps\vulkan-headers'
$runtime = Join-Path $repo 'bin\runtime_win64_win32.exe'
Push-Location $repo
try {
  if ($Rebuild -or $RebuildRuntime -or -not (Test-Path -LiteralPath $runtime)) {
    & $py -B tools\build_nvn.py --jobs $Jobs; Check 'tools\build_nvn.py'
    & $py -B switchrecomp.py --build-runtime --cc (Join-Path $gbin 'x86_64-w64-mingw32-gcc.exe') --target win64 --backend win32; Check 'switchrecomp.py --build-runtime'
  } else { Write-Host "  already there: $runtime (-RebuildRuntime to make it again)" }

  Step 4 'Recompiling the game code (the longest step: 20-60 minutes, about 0.5 GB of RAM per job)'
  $data = Join-Path $game 'Orbitals_data'
  New-Item -ItemType Directory -Force -Path $data | Out-Null
  foreach ($leaf in 'exefs', 'romfs') {
    $dst = Join-Path $data $leaf
    if (-not (Test-Path -LiteralPath $dst)) {
      if ($CopyData) { Copy-Item -LiteralPath (Join-Path $GameData $leaf) -Destination $dst -Recurse }
      else { New-Item -ItemType Junction -Path $dst -Target (Join-Path $GameData $leaf) | Out-Null }
    }
  }
  if ($Rebuild -or $RebuildCode -or -not (Test-Path -LiteralPath (Join-Path $game 'Orbitals_code.dll'))) {
    & $py -B switchrecomp.py $GameData -o Orbitals --outdir $game --runtime $runtime --cc (Join-Path $gbin 'x86_64-w64-mingw32-gcc.exe') `
      --target win64 --backend win32 -O 2 --jobs $Jobs; Check 'switchrecomp.py (game code)'
  } else { Write-Host '  already there (-RebuildCode to recompile)' }
} finally { Pop-Location }

Step 5 'Completing the game folder'
Copy-Item -LiteralPath $runtime -Destination (Join-Path $game 'Orbitals.exe') -Force
Copy-Item -LiteralPath (Join-Path $tc 'SDL3.dll') -Destination $game -Force
# the runtime looks for nxshader\nxs_live.py and python\python.exe in its folder and up to three folders above it
foreach ($link in @(@('nxshader', 'tools\nxshader'), @('python', 'python'))) {
  $dst = Join-Path $InstallDir $link[0]
  if (-not (Test-Path -LiteralPath $dst)) { New-Item -ItemType Junction -Path $dst -Target (Join-Path $repo $link[1]) | Out-Null }
}
Copy-Item -LiteralPath (Join-Path $repo 'tools\release\Play-Orbitals.ps1') -Destination $game -Force

$prewarmed = $true
if ($ShaderCaptures) {
  Step 6 "Shader cache prewarm from $ShaderCaptures"
  # The runtime's default cache (runtime\nvn_hook.c: <exe folder>\<exe name>_nvn\cache) and the nxs_live.py, translator and options
  # (no --facts) it starts the live translator with: the entries carry the runtime's chain and a miss is still translated in the game.
  # nxs_live.py publishes validated entries and rejects a different chain before writing shader modules.
  $shaderCache = Join-Path $game 'Orbitals_nvn\cache'
  if ($env:NXRT_SHADER_CACHE) { Write-Host "  NXRT_SHADER_CACHE is set: a game started with it uses $env:NXRT_SHADER_CACHE, not $shaderCache" -ForegroundColor Yellow }
  $env:DOTNET_ROOT = Join-Path $tc 'dotnet10'
  $env:NXSHADER_TOOLS = Join-Path $tc 'vulkan-bin'
  $last = $null
  # one JSON object per line, passed on to this script's stdout
  & $py -B -I (Join-Path $repo 'tools\nxshader\nxs_live.py') --offline @captureArgs --cache $shaderCache --dotnet (Join-Path $tc 'dotnet10\dotnet.exe') |
    ForEach-Object { $_; try { $last = $_ | ConvertFrom-Json } catch { } }
  $code = $LASTEXITCODE
  $finished = $last -and $last.phase -eq 'finished'
  if ($code -eq 0 -and $finished -and $last.paired -gt 0 -and $last.failed -eq 0) {
    Write-Host "  prewarmed all $($last.paired) captures: $($last.prepared) translated, $($last.reused) already in the cache"
  } else {
    $prewarmed = $false
    $why = if ($code -eq 0 -and $finished) { "no completed .ctl/.code capture pairs in $ShaderCaptures" }
      elseif ($code -eq 2 -and $finished) { "$($last.failed) of $($last.discovered) captures not prewarmed (the shader_error lines above)" }
      elseif ($code -eq 130) { 'interrupted' }
      elseif ($last -and $last.phase -eq 'error') { "stopped: $($last.error)" }
      else { "nxs_live.py exit code $code" }
    Write-Host "  SHADER PREWARM INCOMPLETE: $why" -ForegroundColor Yellow
    Write-Host '  The installation is ready. The runtime can translate cache misses on demand. See docs\SHADER_PREWARM.md.' -ForegroundColor Yellow
  }
}
Write-Host ""
Write-Host "Done: $game" -ForegroundColor Green
Write-Host "  Play:      powershell -ExecutionPolicy Bypass -File `"$game\Play-Orbitals.ps1`"            (30 FPS reference mode)"
Write-Host "             powershell -ExecutionPolicy Bypass -File `"$game\Play-Orbitals.ps1`" -Mode Experimental60"
Write-Host "  Launcher:  `"$repo\Orbitals-Launcher.bat`"   (needs Python 3.12+ with Tk; the recompiler's Python has no Tk)"
Write-Host "  The first session translates the game's shaders as they are first used: the picture pauses a few seconds at a time,"
Write-Host "  mostly during loading screens (do not close the game then). Later sessions use the shader cache."
if (-not $prewarmed) {
  Write-Host "  The shader prewarm did not complete (above): exit code 3." -ForegroundColor Yellow
  exit 3
}
