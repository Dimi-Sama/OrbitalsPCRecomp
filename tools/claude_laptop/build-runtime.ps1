# Build the NVN layer (build\nvn\libnvn.a) and the Win32 runtime (bin\runtime_win64_win32.exe) of this worktree.
# Portable: every path is relative to the worktree; the toolchain of the main checkout is used read only
#   <worktree>\..\Switch2Recomp-0.4.1-windows-x64\Switch2Recomp\{python,gcc}   python 3.14, conda-forge GCC 16.2
#   <worktree>\..\Switch2RECOMP\build\orbitals-debug\toolchain                 cc1plus.exe, external\, vulkan-bin\
#   <worktree>\..\Switch2RECOMP\build\orbitals-debug\build_runtime_objects.py  cached runtime objects (copied here once)
# Runs the compilers at below-normal priority with few jobs (laptop). No -march=native: the NVN layer keeps its
# own -mavx2 -mfma (x86-64-v3, supported by both the Ryzen 7 7800X3D and the Core i7-14650HX).
param([switch]$SkipNvn, [int]$Jobs = 3)
$ErrorActionPreference = 'Stop'
$wt   = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
$root = Split-Path -Parent $wt
$rel  = Join-Path $root 'Switch2Recomp-0.4.1-windows-x64\Switch2Recomp'
$py   = Join-Path $rel 'python\python.exe'
$gbin = Join-Path $rel 'gcc\Library\bin'
$cc   = Join-Path $gbin 'x86_64-w64-mingw32-gcc.exe'
$mainDiag = Join-Path $root 'Switch2RECOMP\build\orbitals-debug'
$tc   = Join-Path $mainDiag 'toolchain'
$bro  = Join-Path $wt 'build\orbitals-debug\build_runtime_objects.py'
foreach ($p in $py, $cc, "$tc\cc1plus.exe", "$tc\external") { if (-not (Test-Path -LiteralPath $p)) { throw "missing: $p" } }
if (-not (Test-Path -LiteralPath $bro)) { Copy-Item -LiteralPath (Join-Path $mainDiag 'build_runtime_objects.py') -Destination $bro }
Set-Location -LiteralPath $wt
$env:COMPILER_PATH = $tc
$env:S2R_EXTERNAL  = Join-Path $tc 'external'
$env:Path = "$gbin;$tc\vulkan-bin;$env:Path"
$env:SWR_NVNCXX = $cc
[System.Diagnostics.Process]::GetCurrentProcess().PriorityClass = 'BelowNormal'   # inherited by the compilers
if (-not $SkipNvn) {
  & $py -B -c "import os,sys; sys.path.insert(0,'tools'); import build_nvn; build_nvn.CXX=os.environ['SWR_NVNCXX']; build_nvn.main()" --jobs $Jobs
  if ($LASTEXITCODE) { throw "build_nvn failed ($LASTEXITCODE)" }
}
& $py -B $bro win32 $cc 2
if ($LASTEXITCODE) { throw "runtime build failed ($LASTEXITCODE)" }
Get-Item (Join-Path $wt 'bin\runtime_win64_win32.exe') | Select-Object FullName, Length, LastWriteTime
