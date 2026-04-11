$ErrorActionPreference = "Stop"

$projectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $projectRoot

$workPath = Join-Path $projectRoot "build\pyinstaller_work"
$specPath = Join-Path $projectRoot "build\pyinstaller_spec"
$dashboardHtml = Join-Path $projectRoot "web_dashboard.html"
$workerScript = Join-Path $projectRoot "melotts_windows_worker.py"
New-Item -ItemType Directory -Force -Path $workPath | Out-Null
New-Item -ItemType Directory -Force -Path $specPath | Out-Null

if (-not (Test-Path ".\.venv310\Scripts\python.exe")) {
    throw ".venv310\Scripts\python.exe 를 찾을 수 없습니다."
}

$python = Resolve-Path ".\.venv310\Scripts\python.exe"

& $python -m pip install --upgrade pip pyinstaller
& $python -m PyInstaller `
    --noconfirm `
    --clean `
    --windowed `
    --onedir `
    --name tts_viewer `
    --workpath $workPath `
    --specpath $specPath `
    --add-data "${dashboardHtml};." `
    --add-data "${workerScript};." `
    desktop_tts_viewer.py

Write-Host ""
Write-Host "빌드 완료:"
Write-Host "  $projectRoot\dist\tts_viewer\tts_viewer.exe"
Write-Host ""
Write-Host "배포 권장 파일:"
Write-Host "  1. dist\tts_viewer\ 전체 폴더"
Write-Host "  2. install_melotts_runtime.bat"
