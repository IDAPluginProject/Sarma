param(
    [string] $InstallDir = "$env:ProgramFiles\Sarma",
    [string] $BuildRoot = "",
    [string] $SarmaBin = "",
    [switch] $NoPath
)

$ErrorActionPreference = "Stop"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$RootDir = Resolve-Path (Join-Path $ScriptDir "..")

if (-not $BuildRoot) {
    $BuildRoot = Join-Path $RootDir "dist\nuitka"
}

function Test-Admin {
    $identity = [Security.Principal.WindowsIdentity]::GetCurrent()
    $principal = [Security.Principal.WindowsPrincipal]::new($identity)
    return $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
}

if (-not $SarmaBin) {
    $candidate = Get-ChildItem -Path $BuildRoot -Recurse -File -Filter "sarma.exe" -ErrorAction SilentlyContinue |
        Sort-Object LastWriteTime |
        Select-Object -Last 1
    if ($candidate) {
        $SarmaBin = $candidate.FullName
    }
}

if (-not $SarmaBin -or -not (Test-Path -LiteralPath $SarmaBin)) {
    Write-Error "No sarma.exe found under $BuildRoot. Build first: scripts\build_nuitka.ps1"
}

if (-not (Test-Admin)) {
    Write-Error "System install requires an elevated PowerShell session. Re-run as Administrator."
}

New-Item -ItemType Directory -Force -Path $InstallDir | Out-Null
Copy-Item -LiteralPath $SarmaBin -Destination (Join-Path $InstallDir "sarma.exe") -Force

if (-not $NoPath) {
    $machinePath = [Environment]::GetEnvironmentVariable("Path", "Machine")
    $parts = $machinePath -split ";" | Where-Object { $_ }
    if ($parts -notcontains $InstallDir) {
        [Environment]::SetEnvironmentVariable(
            "Path",
            ($parts + $InstallDir) -join ";",
            "Machine"
        )
    }
}

Write-Host "Installed $(Join-Path $InstallDir 'sarma.exe')"
