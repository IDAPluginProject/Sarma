param(
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
uv run --group build python scripts/build_nuitka.py @NuitkaArgs
exit $LASTEXITCODE
