# SwitchRecomp - Copyright 2026 MZ Labs. GNU AGPL v3 with NOTICE.txt terms.
param(
    [string]$Destination = (Join-Path $PSScriptRoot '..\python'),
    [string]$Package
)
$ErrorActionPreference = 'Stop'
$url = 'https://api.nuget.org/v3-flatcontainer/python/3.14.9/python.3.14.9.nupkg'
$sha = '7cd9d07aec975212344dc6f7e45019378cf6775dd564181e269010a1eddaaec7'
$stage = $null

try {
    $Destination = [IO.Path]::GetFullPath($Destination)
    $parent = Split-Path -Parent $Destination
    if (Test-Path -LiteralPath $Destination) {
        $entry = Get-Item -LiteralPath $Destination -Force
        if (!$entry.PSIsContainer -or ($entry.Attributes -band [IO.FileAttributes]::ReparsePoint) -or
                (Get-ChildItem -LiteralPath $Destination -Force | Select-Object -First 1)) {
            throw 'The local Python directory is occupied. Choose a fresh Liftoff folder or move the existing python directory before retrying.'
        }
    }
    $stage = Join-Path $parent ('.liftoff-python-' + [Guid]::NewGuid().ToString('N'))
    [void][IO.Directory]::CreateDirectory($stage)
    if (!$Package) {
        $curl = Join-Path $env:SystemRoot 'System32\curl.exe'
        if (!(Test-Path -LiteralPath $curl -PathType Leaf)) {
            throw 'Windows curl.exe is missing. Update Windows and retry Python setup.'
        }
        $Package = Join-Path $stage 'python.nupkg.part'
        & $curl --location --fail --retry 3 --connect-timeout 30 --max-time 300 --progress-bar --output $Package $url
        if ($LASTEXITCODE -ne 0) { throw "The Python download did not complete (curl exit code $LASTEXITCODE). Check your connection and retry." }
    }
    $stream = [IO.File]::OpenRead($Package)
    $digest = [Security.Cryptography.SHA256]::Create()
    try { $actual = [BitConverter]::ToString($digest.ComputeHash($stream)).Replace('-', '') }
    finally { $digest.Dispose(); $stream.Dispose() }
    if ($actual -ne $sha) {
        throw 'The Python package failed its SHA-256 integrity check. Retry the download.'
    }

    [void][Reflection.Assembly]::Load('System.IO.Compression.FileSystem, Version=4.0.0.0, Culture=neutral, PublicKeyToken=b77a5c561934e089')
    $unpacked = Join-Path $stage 'unpacked'
    try { [IO.Compression.ZipFile]::ExtractToDirectory($Package, $unpacked) }
    catch { throw "Could not extract the verified Python ZIP package. Check free disk space and folder permissions. $($_.Exception.Message)" }
    $runtime = Join-Path $unpacked 'tools'
    $python = Join-Path $runtime 'python.exe'
    if (!(Test-Path -LiteralPath $python -PathType Leaf)) { throw 'The verified Python package is missing tools\python.exe.' }
    & $python -I -S -c 'import sys; sys.exit(sys.version_info[:3] != (3, 14, 9))'
    if ($LASTEXITCODE -ne 0) { throw 'The extracted Python 3.14.9 runtime could not start.' }

    if ([IO.Directory]::Exists($Destination)) { [IO.Directory]::Delete($Destination, $false) }
    [IO.Directory]::Move($runtime, $Destination)
} catch {
    [Console]::Error.WriteLine($_.Exception.Message)
    exit 1
} finally {
    if ($stage -and [IO.Directory]::Exists($stage)) {
        $staged = Get-Item -LiteralPath $stage -Force
        if ($staged.Parent.FullName -eq $parent -and $staged.Name -like '.liftoff-python-*' -and
                !($staged.Attributes -band [IO.FileAttributes]::ReparsePoint)) {
            try { [IO.Directory]::Delete($staged.FullName, $true) }
            catch { [Console]::Error.WriteLine("Could not clean the Python staging directory. $($_.Exception.Message)") }
        }
    }
}
