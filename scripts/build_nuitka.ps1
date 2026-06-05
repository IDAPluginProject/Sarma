param(
    [switch] $Mingw,
    [switch] $Msvc,
    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]] $NuitkaArgs
)

$ErrorActionPreference = "Stop"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$RootDir = Resolve-Path (Join-Path $ScriptDir "..")

if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
    Write-Error "Missing required command: uv. Install uv first: https://docs.astral.sh/uv/getting-started/installation/"
}

Set-Location $RootDir
$NuitkaArgs = @($NuitkaArgs | Where-Object { $_ -and $_.Trim().Length -gt 0 })

$PythonVersionText = (& uv run --group build python -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')").Trim()
$PythonVersion = [version] $PythonVersionText

if ($Mingw -and $Msvc) {
    Write-Error "Choose only one compiler mode: -Mingw or -Msvc."
}

if ($Mingw -and $PythonVersion -ge [version] "3.13") {
    Write-Error "Nuitka cannot use --mingw64 with Python $PythonVersionText. Use Python 3.12 directly, for example: uv run --python 3.12 --group build python scripts/build_nuitka.py --mingw64"
}

if ($Mingw -and -not $Msvc -and $NuitkaArgs -notcontains "--mingw64") {
    $NuitkaArgs = @("--mingw64") + $NuitkaArgs
}

uv run --group build python scripts/build_nuitka.py @NuitkaArgs
exit $LASTEXITCODE
