# Orbitals PC Recomp, a work based on SwitchRecomp by MZ Labs. GNU AGPL v3.0 with the additional terms of NOTICE.txt (LICENSE.txt).
# Start Orbitals from a folder made by tools\release\setup-windows.ps1 (<InstallDir>\Orbitals, with <InstallDir>\toolchain beside it).
#   powershell -ExecutionPolicy Bypass -File Play-Orbitals.ps1 [-Mode Reference30|Async30|Experimental60] [-InternalResolution 540p|720p|900p|1080p|Portable]
#        [-OutputSize 1920x1080] [-DisplayMode Windowed|Borderless] [-VSync On|Off] [-Upscale Standard|Sharp|FSR1] [-KeyboardPlayer 1|2]
#        [-AudioVolume 0-100] [-MuteAudio] [-Diagnostics]
# -Diagnostics: the runtime also logs the 3D resolution the game draws at (for tools\release\bench_report.py)
# The release layout's launch script (the options of the first PC settings prototype).
param(
    [string]$GameDir = $PSScriptRoot,
    [ValidateSet('Reference30', 'Async30', 'Experimental60')][string]$Mode,
    [ValidateSet('540p', '720p', '900p', '1080p', 'Portable')][string]$InternalResolution,
    [ValidatePattern('^\d{3,4}x\d{3,4}$')][string]$OutputSize,
    [ValidateSet('Windowed', 'Borderless')][string]$DisplayMode,
    [ValidateSet('On', 'Off')][string]$VSync,
    [ValidateSet('Standard', 'Sharp', 'FSR1')][string]$Upscale,
    [ValidateSet(1, 2)][int]$KeyboardPlayer,
    [ValidateRange(0, 100)][int]$AudioVolume,
    [switch]$MuteAudio,
    [switch]$Diagnostics
)
$ErrorActionPreference = 'Stop'
$game = (Resolve-Path -LiteralPath $GameDir).Path
$runtime = Join-Path $game 'Orbitals.exe'
foreach ($need in 'Orbitals.exe', 'Orbitals_code.dll', 'Orbitals_data\exefs', 'Orbitals_data\romfs') {
    if (-not (Test-Path -LiteralPath (Join-Path $game $need))) { throw "$game\$need is missing (tools\release\setup-windows.ps1 makes this folder)" }
}
if (Get-Process -Name Orbitals -ErrorAction SilentlyContinue) { throw 'Orbitals is already running.' }
$root = Split-Path -Parent $game
$toolchain = Join-Path $game 'toolchain'
if (-not (Test-Path -LiteralPath $toolchain -PathType Container)) { $toolchain = Join-Path $root 'toolchain' }
$python = Join-Path $game 'python\python.exe'
if (-not (Test-Path -LiteralPath $python -PathType Leaf)) { $python = Join-Path $root 'python\python.exe' }
$dotnet = Join-Path $toolchain 'dotnet10'
$vulkanTools = Join-Path $toolchain 'vulkan-bin'

if ($Mode) {
    $path = Join-Path $game 'Orbitals.ini'
    $text = if (Test-Path -LiteralPath $path) { [IO.File]::ReadAllText($path) } else { '' }
    $rate = @{ Reference30 = 0; Async30 = 30; Experimental60 = 60 }[$Mode]
    if ($text -match '(?m)^ue_fps=') { $text = [regex]::Replace($text, '(?m)^ue_fps=[^\r\n]*', "ue_fps=$rate") } else { $text = $text.TrimEnd() + "`r`nue_fps=$rate`r`n" }
    [IO.File]::WriteAllText($path, $text)
}
$start = [Diagnostics.ProcessStartInfo]::new()
$start.FileName = $runtime
$start.WorkingDirectory = $game
$gameArgs = @('--renderer=vulkan')
if ($InternalResolution) { $gameArgs += '--docked=' + [int]($InternalResolution -ne 'Portable') }
if ($DisplayMode) { $gameArgs += '--fullscreen=' + [int]($DisplayMode -eq 'Borderless') }
if ($KeyboardPlayer) { $gameArgs += "--keyboard_player=$KeyboardPlayer" }
$start.Arguments = $gameArgs -join ' '
$start.UseShellExecute = $false
$e = $start.EnvironmentVariables
$e['SWR_GPU'] = 'nvn'; $e['NXRT_GFX'] = 'vulkan'
if (-not $e.ContainsKey('NXRT_VK_WB_GPU')) { $e['NXRT_VK_WB_GPU'] = '1' }   # write-backs compared on the GPU (validated: STEAM_DECK_PERFORMANCE.md)
if (-not $e.ContainsKey('NXRT_VK_FLIGHT')) { $e['NXRT_VK_FLIGHT'] = '0' }   # the flight recorder (F5 captures of the last frames) is a development tool: ~440 MB and a frame copy each present
if ($Diagnostics) { $e['NXRT_VK_LOG_RES'] = '1' }   # the 3D resolution the game draws at, every 300 frames (tools\release\bench_report.py)
if (Test-Path -LiteralPath $python -PathType Leaf) { $e['SWR_PYTHON'] = $python }
if (Test-Path -LiteralPath $dotnet -PathType Container) { $e['DOTNET_ROOT'] = $dotnet }
if (Test-Path -LiteralPath $vulkanTools -PathType Container) { $e['NXSHADER_TOOLS'] = $vulkanTools }
$e['PATH'] = "$dotnet;$vulkanTools;$($e['PATH'])"
foreach ($key in 'NXRT_EXIT_AT_PRESENT', 'NXRT_VK_SHOT', 'NXRT_VK_SHOT_DIR', 'NXRT_VK_SHOT_FILE', 'SWR_TRACE_FN', 'SWR_TRACE_FN_WINDOW', 'SWR_TRACE_BK2', 'SWR_AUDIO_DUMP', 'SWR_AUDIO_MUTE') { $e.Remove($key) }
if ($OutputSize) { $e['SWR_WINDOW_SIZE'] = $OutputSize }
if ($VSync) { $e['NXRT_VK_PRESENT'] = if ($VSync -eq 'On') { 'fifo' } else { 'immediate' } }
if ($Upscale) { $e['NXRT_VK_UPSCALE'] = $Upscale.ToLowerInvariant() }
if ($PSBoundParameters.ContainsKey('AudioVolume')) { $e['SWR_AUDIO_VOLUME'] = [string]$AudioVolume }
if ($MuteAudio) { $e['SWR_AUDIO_MUTE'] = '1' }
$sceneScale = @{ '540p' = '50'; '720p' = '66.6667'; '900p' = '83.3333'; '1080p' = '100' }
$overlay = $null
$process = $null
try {
    if ($InternalResolution -and $sceneScale.ContainsKey($InternalResolution)) {
        $relative = 'Orbitals\Saved\Config\Switch2\Engine.ini'
        $text = ''
        foreach ($layer in 'romfs_overlay', 'romfs') {
            $source = Join-Path (Join-Path $game "Orbitals_data\$layer") $relative
            if (Test-Path -LiteralPath $source -PathType Leaf) {
                $text = [IO.File]::ReadAllText($source)
                break
            }
        }
        $text = [regex]::Replace($text, '(?im)^[ \t]*r\.SecondaryScreenPercentage\.GameViewport[ \t]*=.*(?:\r?\n|$)', '')
        $overlay = Join-Path ([IO.Path]::GetTempPath()) "Orbitals-resolution-$([guid]::NewGuid().ToString('N'))"
        $engine = Join-Path $overlay $relative
        [void][IO.Directory]::CreateDirectory((Split-Path -Parent $engine))
        [IO.File]::WriteAllText($engine, $text.TrimEnd() + "`r`n[SystemSettings]`r`nr.SecondaryScreenPercentage.GameViewport=$($sceneScale[$InternalResolution])`r`n")
        $e['SWR_ROMFS_EXTRA_OVERLAY'] = $overlay
    }
    $process = [Diagnostics.Process]::Start($start)
    $process.WaitForExit()
    exit $process.ExitCode
} finally {
    if ($process) { $process.Dispose() }
    if ($overlay) {
        [IO.File]::Delete($engine)
        $directory = Split-Path -Parent $engine
        while ($directory -ne $overlay) {
            if ([IO.Directory]::Exists($directory)) { [IO.Directory]::Delete($directory) }
            $directory = Split-Path -Parent $directory
        }
        if ([IO.Directory]::Exists($overlay)) { [IO.Directory]::Delete($overlay) }
    }
}
