$ErrorActionPreference = "Stop"

function Invoke-Step {
    param(
        [scriptblock]$Action,
        [string]$ErrorMessage
    )

    & $Action
    if ($LASTEXITCODE -ne 0) {
        throw $ErrorMessage
    }
}

$viewerRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$projectRoot = Split-Path -Parent $viewerRoot
Set-Location $projectRoot

$workPath = Join-Path $projectRoot "build\pyinstaller_work"
$specPath = Join-Path $projectRoot "build\pyinstaller_spec"
$dashboardHtml = Join-Path $projectRoot "web_dashboard.html"
$workerScript = Join-Path $viewerRoot "melotts_windows_worker.py"
$iconScript = Join-Path $viewerRoot "generate_tts_viewer_icon.py"
$iconPath = Join-Path $projectRoot ("build\generated\tts_viewer_icon_" + (Get-Date -Format "yyyyMMdd_HHmmss") + ".ico")
New-Item -ItemType Directory -Force -Path $workPath | Out-Null
New-Item -ItemType Directory -Force -Path $specPath | Out-Null

if (-not (Test-Path (Join-Path $projectRoot ".venv310\Scripts\python.exe"))) {
    throw ".venv310\Scripts\python.exe 를 찾을 수 없습니다."
}

$python = Resolve-Path (Join-Path $projectRoot ".venv310\Scripts\python.exe")

Invoke-Step { & $python -m pip install --upgrade pip pyinstaller } "pip/PyInstaller 설치에 실패했습니다."
Invoke-Step { & $python $iconScript $iconPath } "아이콘 파일 생성에 실패했습니다."
if (-not (Test-Path $iconPath)) {
    throw "아이콘 파일이 생성되지 않았습니다: $iconPath"
}
Invoke-Step {
    & $python -m PyInstaller `
        --noconfirm `
        --clean `
        --windowed `
        --onedir `
        --name tts_viewer `
        --workpath $workPath `
        --specpath $specPath `
        --icon $iconPath `
        --add-data "${dashboardHtml};." `
        --add-data "${workerScript};." `
        (Join-Path $viewerRoot "desktop_tts_viewer.py")
} "PyInstaller 빌드에 실패했습니다."

Write-Host ""
Write-Host "빌드 완료:"
Write-Host "  $projectRoot\dist\tts_viewer\tts_viewer.exe"
Write-Host ""
Write-Host "배포 권장 파일:"
Write-Host "  1. dist\tts_viewer\ 전체 폴더"
Write-Host "  2. tts_viewer\install_melotts_runtime.bat"
