@echo off
chcp 65001 >nul
title POSCO Smart Factory AI - One-Click Setup and Launcher
cd /d "%~dp0"

:: 주의: 이 파일은 CRLF로 저장한다. if 블록 안의 echo에는 괄호를 쓰지 않는다. 블록이 일찍 닫혀 실행이 중단된다.

echo ======================================================================
echo   [SteelGuardian] POSCO Smart Factory AI One-Click Setup and Launcher
echo ======================================================================

:: 1. 환경변수 기본값 설정 및 .env 로드 - 기본값은 127.0.0.1 로컬 보안 격리
set "API_HOST=127.0.0.1"
set "API_PORT=8000"
set "STREAMLIT_HOST=127.0.0.1"
set "STREAMLIT_PORT=8501"

:: 보안 설정 ALLOW_REMOTE_ACTIVATION, ADMIN_API_KEY 등도 서버에 전달되도록 전체 항목을 읽는다.
if exist ".env" (
    for /f "usebackq eol=# tokens=1,* delims==" %%a in (".env") do set "%%a=%%b"
)

:: 2. Python 인터프리터 감지 - 권장은 Python 3.12 64-bit, 다른 버전은 경고 후 계속 시도
set "PY_CMD="
py -3.12 --version >nul 2>&1 && set "PY_CMD=py -3.12"
if not defined PY_CMD py -3.11 --version >nul 2>&1 && set "PY_CMD=py -3.11"
if not defined PY_CMD py -3.13 --version >nul 2>&1 && set "PY_CMD=py -3.13"
if not defined PY_CMD python --version >nul 2>&1 && set "PY_CMD=python"

if not defined PY_CMD (
    echo [ERROR] Python 3.12 not found.
    echo Install Python 3.12 64-bit from:
    echo https://www.python.org/downloads/release/python-31210/
    echo 상세 안내: docs\SETUP_WINDOWS.md
    pause
    exit /b 1
)
if not "%PY_CMD%"=="py -3.12" (
    echo [WARN] Python 3.12가 감지되지 않아 %PY_CMD% 로 계속 시도합니다.
    echo [WARN] 오프라인 wheels 폴더는 cp312-win_amd64 기준이므로 오프라인 설치 시 실패할 수 있습니다.
)

echo [0/4] 선택된 Python 인터프리터 확인: %PY_CMD%
%PY_CMD% --version

:: 3. 가상환경 생성
if not exist ".venv\Scripts\python.exe" (
    echo [1/4] Python 가상환경 .venv 생성 중...
    %PY_CMD% -m venv .venv
    if errorlevel 1 (
        echo [ERROR] 가상환경 .venv 생성에 실패했습니다. Python 3.12 64-bit 설치 상태를 확인하세요.
        echo 상세 안내: docs\SETUP_WINDOWS.md
        pause
        exit /b 1
    )
)

:: 4. 오프라인 wheels 우선 설치 또는 온라인 PyPI 폴백
if not exist "wheels" (
    echo [INFO] Local wheels folder not found.
    echo Use code.zip or Downloads\posco_hackathon for fully offline setup,
    echo or run setup on an internet-connected PC first.
    echo [2/4] PyPI 온라인 설치를 진행합니다: requirements.txt
    ".venv\Scripts\python.exe" -m pip install -r requirements.txt
) else (
    echo [2/4] 오프라인 wheels 폴더 감지: 로컬 wheel 설치를 진행합니다. 인터넷 불필요
    ".venv\Scripts\python.exe" -m pip install --no-index --find-links=wheels -r requirements.lock.txt
)
if errorlevel 1 (
    echo [ERROR] 핵심 패키지 torch, numpy, scipy 등의 설치에 실패했습니다.
    echo 오프라인 wheelhouse는 Python 3.12 64-bit, cp312-win_amd64를 기준으로 구성되어 있습니다.
    echo Install Python 3.12 64-bit from: https://www.python.org/downloads/release/python-31210/
    echo 상세 안내: docs\SETUP_WINDOWS.md
    pause
    exit /b 1
)

:: 4-1. PyTorch / TorchVision 런타임 DLL 로드 사전 확인
".venv\Scripts\python.exe" -c "import torch; import torchvision; print(f'[Runtime OK] torch={torch.__version__}, torchvision={torchvision.__version__}')"
if errorlevel 1 (
    echo [ERROR] PyTorch/TorchVision DLL 로드에 실패했습니다: ImportError DLL load failed
    echo 클린 Windows 환경이라면 Microsoft Visual C++ 2015-2022 Redistributable x64 설치가 필요할 수 있습니다.
    echo 상세 안내: docs\SETUP_WINDOWS.md
    pause
    exit /b 1
)

:: 5. 무결성·보안 및 자동화 시나리오 검증 - AUDIT_LOG_DIR=logs/test 로 운영 로그 오염 방지
echo [3/4] 무결성·보안 및 자동화 시나리오 검증 테스트 실행 중...
set "AUDIT_LOG_DIR=%~dp0logs\test"
".venv\Scripts\python.exe" tests\test_server.py
if errorlevel 1 (
    echo [WARN] 자동화 검증이 실패했습니다. 위 로그를 확인하십시오. 시연은 계속 진행합니다.
    echo [WARN] tests\scenarios.json 또는 datasets 내 scratch 이미지가 없어도 이 경고가 표시됩니다.
)
set "AUDIT_LOG_DIR="

:: 6. 서버 및 대시보드 기동 - 오프라인 망분리 환경 호환, 외부 텔레메트리 전송 차단
echo [4/4] FastAPI 추론 서버 %API_HOST%:%API_PORT% 및 Streamlit 대시보드 %STREAMLIT_HOST%:%STREAMLIT_PORT% 기동 중...
start "POSCO FastAPI Server" ".venv\Scripts\uvicorn.exe" server:app --host %API_HOST% --port %API_PORT%
timeout /t 2 >nul
".venv\Scripts\streamlit.exe" run app.py --server.address %STREAMLIT_HOST% --server.port %STREAMLIT_PORT% --browser.gatherUsageStats false
pause
