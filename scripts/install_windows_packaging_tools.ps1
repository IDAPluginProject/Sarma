$ErrorActionPreference = "Stop"

function Add-PathForCurrentProcess {
    param([string] $PathToAdd)
    if ((Test-Path -LiteralPath $PathToAdd) -and
        -not (($env:PATH -split ';') -contains $PathToAdd)) {
        $env:PATH = "$PathToAdd;$env:PATH"
    }
}

Add-PathForCurrentProcess "C:\Program Files\dotnet"
Add-PathForCurrentProcess (Join-Path $env:USERPROFILE ".dotnet\tools")

if (-not (Get-Command dotnet -ErrorAction SilentlyContinue)) {
    if (-not (Get-Command winget -ErrorAction SilentlyContinue)) {
        Write-Error "dotnet and winget were not found. Install the .NET SDK manually, then run: dotnet tool install --global wix"
    }

    winget install --id Microsoft.DotNet.SDK.8 --exact --source winget
    Add-PathForCurrentProcess "C:\Program Files\dotnet"
}

if (-not (Get-Command dotnet -ErrorAction SilentlyContinue)) {
    Write-Error "dotnet is still not available in this PowerShell session. Open a new PowerShell window and run this script again."
}

if (Get-Command wix -ErrorAction SilentlyContinue) {
    dotnet tool update --global wix
} else {
    dotnet tool install --global wix
}

Add-PathForCurrentProcess (Join-Path $env:USERPROFILE ".dotnet\tools")

if (-not (Get-Command wix -ErrorAction SilentlyContinue)) {
    Write-Error "wix was installed but is not available in PATH. Open a new PowerShell window or add $env:USERPROFILE\.dotnet\tools to PATH."
}

Write-Host "Windows packaging tools are ready."
