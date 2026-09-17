# Build CW Station for Windows (run on a Windows PC with internet access).
#   powershell -ExecutionPolicy Bypass -File packaging\build_windows.ps1
# Result: dist\CWStation-<version>-win64.zip  (copy to the radio PC, unzip, run CWStation.exe)
param(
    [switch]$SkipTests
)
$ErrorActionPreference = "Stop"
$Root = Split-Path $PSScriptRoot -Parent
Set-Location $Root

$pyExe = "python"; $pyArgs = @()
foreach ($v in @("3.12", "3.13", "3.11")) {
    try {
        & py "-$v" -c "import sys" 2>$null
        if ($LASTEXITCODE -eq 0) { $pyExe = "py"; $pyArgs = @("-$v"); break }
    } catch {}
}

if (-not (Test-Path "third_party\deepcw-engine\model.onnx")) {
    Write-Host "Downloading DeepCW model..."
    New-Item -ItemType Directory -Force "third_party\deepcw-engine" | Out-Null
    foreach ($f in @("model.onnx", "model.onnx.json", "LICENSE")) {
        Invoke-WebRequest "https://raw.githubusercontent.com/e04/deepcw-engine/main/$f" -OutFile "third_party\deepcw-engine\$f"
    }
}

Write-Host "Using Python: $pyExe $pyArgs"
if (-not (Test-Path ".venv-build")) { & $pyExe @pyArgs -m venv .venv-build }
$vpy = Join-Path $Root ".venv-build\Scripts\python.exe"
& $vpy -m pip install --upgrade pip
& $vpy -m pip install -r requirements-dev.txt
if ($LASTEXITCODE -ne 0) { throw "pip install failed" }

if (-not $SkipTests) {
    & $vpy -m pytest -q tests
    if ($LASTEXITCODE -ne 0) { throw "tests failed" }
}

& $vpy -m PyInstaller --noconfirm --clean packaging\cwstation.spec
if ($LASTEXITCODE -ne 0) { throw "PyInstaller failed" }

Write-Host "Self-test of the built program (about 20 s)..."
$p = Start-Process -FilePath "dist\CWStation\CWStation.exe" -ArgumentList "--selftest 15" -Wait -PassThru
Get-Content "$env:APPDATA\CWStation\selftest-result.txt" -ErrorAction SilentlyContinue
if ($p.ExitCode -ne 0) { throw "Self-test FAILED (exit code $($p.ExitCode))" }

$version = (& $vpy -c "import cwstation; print(cwstation.__version__)").Trim()
$zip = "dist\CWStation-$version-win64.zip"
if (Test-Path $zip) { Remove-Item $zip }
Compress-Archive -Path "dist\CWStation" -DestinationPath $zip
Write-Host "OK: $zip"
