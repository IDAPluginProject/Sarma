param(
    [ValidateSet("x86_64", "arm64")]
    [string] $Arch = "x86_64",
    [string] $Formats = "msi",
    [int] $Jobs = [Environment]::ProcessorCount,
    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]] $ReleaseArgs
)

$ErrorActionPreference = "Stop"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$RootDir = Resolve-Path (Join-Path $ScriptDir "..")

if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
    Write-Error "Missing required command: uv. Install uv first: https://docs.astral.sh/uv/getting-started/installation/"
}

Set-Location $RootDir
uv run --group dev --group build python scripts/build_native_release.py `
    --platform windows `
    --arch $Arch `
    --formats $Formats `
    --jobs $Jobs `
    @ReleaseArgs
exit $LASTEXITCODE
