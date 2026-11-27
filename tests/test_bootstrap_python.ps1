# Run with Windows PowerShell and the pinned python.3.14.9.nupkg. The kit starts with no local Python.
param([Parameter(Mandatory)][string]$Package)
$ErrorActionPreference = 'Stop'
$Package = (Resolve-Path -LiteralPath $Package).Path
$tmp = (Get-Item -LiteralPath ([IO.Path]::GetTempPath())).FullName
$root = Join-Path $tmp ('Liftoff ZIP test [' + [Guid]::NewGuid().ToString('N') + ']')
[void][IO.Directory]::CreateDirectory($root)
$bootstrap = Join-Path $PSScriptRoot '..\tools\bootstrap-python.ps1'
$powershell = Join-Path $env:SystemRoot 'System32\WindowsPowerShell\v1.0\powershell.exe'
$destination = Join-Path $root 'python'

try {
    $damaged = Join-Path $root 'truncated.nupkg'
    [IO.File]::WriteAllBytes($damaged, [byte[]](0x50, 0x4b, 3, 4))
    $ErrorActionPreference = 'Continue'  # Windows PowerShell wraps expected child stderr in NativeCommandError records.
    try { $output = & $powershell -NoProfile -NonInteractive -ExecutionPolicy Bypass -File $bootstrap -Destination $destination -Package $damaged 2>&1 }
    finally { $ErrorActionPreference = 'Stop' }
    if ($LASTEXITCODE -eq 0 -or ($output | Out-String) -notmatch 'SHA-256' -or (Test-Path -LiteralPath $destination)) {
        throw "The truncated package was not rejected cleanly: $output"
    }

    [void][IO.Directory]::CreateDirectory($destination)  # a failed v0.1.5 run can leave it empty
    & $powershell -NoProfile -NonInteractive -ExecutionPolicy Bypass -File $bootstrap -Destination $destination -Package $Package
    if ($LASTEXITCODE -ne 0) { throw 'Python setup failed in the clean kit' }
    & (Join-Path $destination 'python.exe') -I -S -c 'import ssl,sys,zipfile; assert sys.version_info[:3] == (3,14,9)'
    if ($LASTEXITCODE -ne 0) { throw 'The installed Python could not start or load its standard library' }
    if (Get-ChildItem -LiteralPath $root -Force -Filter '.liftoff-python-*') { throw 'Python staging was left behind' }
    Write-Output 'PASS: SHA-256 rejection, clean installation with no local Python, and staging cleanup.'
} finally {
    $created = Get-Item -LiteralPath $root -Force
    if ($created.Parent.FullName -eq $tmp -and $created.Name -like 'Liftoff ZIP test *' -and
            !($created.Attributes -band [IO.FileAttributes]::ReparsePoint)) {
        [IO.Directory]::Delete($created.FullName, $true)
    }
}
