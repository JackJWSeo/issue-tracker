@echo off
setlocal

set "PROJECT_DIR=%~dp0"
set "MELO_REPO=%PROJECT_DIR%MeloTTS-Windows"
set "ENV_NAME=melotts-win"

where conda >nul 2>nul
if errorlevel 1 (
    echo [ERROR] conda 를 찾을 수 없습니다.
    echo Anaconda 또는 Miniconda 를 먼저 설치한 뒤 다시 실행하세요.
    pause
    exit /b 1
)

if not exist "%MELO_REPO%\setup.py" (
    echo [ERROR] MeloTTS-Windows 폴더를 찾을 수 없습니다.
    echo expected: "%MELO_REPO%"
    pause
    exit /b 1
)

echo [1/4] conda 환경 확인 중...
call conda env list | findstr /R /C:"^%ENV_NAME% " >nul
if errorlevel 1 (
    echo [2/4] Python 3.10 환경 생성 중...
    call conda create -y -n %ENV_NAME% python=3.10
    if errorlevel 1 (
        echo [ERROR] conda 환경 생성에 실패했습니다.
        pause
        exit /b 1
    )
) else (
    echo [2/4] 기존 환경을 재사용합니다.
)

echo [3/4] pip/패키지 설치 중...
call conda run --no-capture-output -n %ENV_NAME% python -m pip install --upgrade pip
if errorlevel 1 (
    echo [ERROR] pip 업그레이드에 실패했습니다.
    pause
    exit /b 1
)

call conda run --no-capture-output -n %ENV_NAME% python -m pip install -r "%MELO_REPO%\requirements.txt"
if errorlevel 1 (
    echo [ERROR] MeloTTS requirements 설치에 실패했습니다.
    pause
    exit /b 1
)

call conda run --no-capture-output -n %ENV_NAME% python -m pip install -e "%MELO_REPO%"
if errorlevel 1 (
    echo [ERROR] MeloTTS editable 설치에 실패했습니다.
    pause
    exit /b 1
)

echo [4/4] 설치 확인 중...
call conda run --no-capture-output -n %ENV_NAME% python -c "from melo.api import TTS; print('MELOTTS_OK')"
if errorlevel 1 (
    echo [ERROR] MeloTTS import 확인에 실패했습니다.
    pause
    exit /b 1
)

echo.
echo 설치가 완료되었습니다.
echo 이제 dist\tts_viewer\tts_viewer.exe 또는 추후 배포된 viewer.exe 를 실행하면 됩니다.
pause
