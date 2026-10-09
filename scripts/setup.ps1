<#
.SYNOPSIS
  One-command setup for Live Captions on Windows.

.DESCRIPTION
  Creates .venv in the repo, installs pinned dependencies plus the package
  (with benchmark and test extras), copies .env.example to .env if missing,
  and runs the test suite. Models download on first use.

.EXAMPLE
  powershell -ExecutionPolicy Bypass -File scripts\setup.ps1
  powershell -ExecutionPolicy Bypass -File scripts\setup.ps1 -Run
#>
param(
    [switch]$Run,          # launch the app when setup finishes
    [switch]$SkipTests
)
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

$py = $null
foreach ($cand in @("py -3.12", "py -3", "python")) {
    try {
        $exe, $rest = $cand.Split(" ", 2)
        $ver = & $exe @($rest | Where-Object { $_ }) -c "import sys; print('%d.%d' % sys.version_info[:2])" 2>$null
        if ($LASTEXITCODE -eq 0 -and [version]$ver -ge [version]"3.10") { $py = $cand; break }
    } catch { }
}
if (-not $py) { throw "Python 3.10+ not found. Install Python 3.12 from https://www.python.org/downloads/ and re-run." }
Write-Host "Using $py"

if (-not (Test-Path ".venv\Scripts\python.exe")) {
    $exe, $rest = $py.Split(" ", 2)
    & $exe @($rest | Where-Object { $_ }) -m venv .venv
}
$vpy = Join-Path $root ".venv\Scripts\python.exe"
& $vpy -m pip install --upgrade pip --quiet
& $vpy -m pip install -r requirements.txt --quiet
& $vpy -m pip install -e ".[bench,dev]" --quiet
if ($LASTEXITCODE -ne 0) { throw "pip install failed" }

if (-not (Test-Path ".env")) { Copy-Item ".env.example" ".env"; Write-Host "Created .env from .env.example" }

if (-not $SkipTests) {
    & $vpy -m pytest -q
    if ($LASTEXITCODE -ne 0) { throw "Tests failed" }
}

Write-Host ""
Write-Host "Setup complete."
Write-Host "  Start the app:      .venv\Scripts\livecaptions.exe"
Write-Host "  Run the benchmark:  .venv\Scripts\livecaptions-bench.exe --download"
if ($Run) { Start-Process (Join-Path $root ".venv\Scripts\livecaptions.exe") }
