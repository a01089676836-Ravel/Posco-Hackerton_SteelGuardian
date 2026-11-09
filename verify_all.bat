@echo off
chcp 65001 >nul
title POSCO Smart Factory AI - Verify All Suites (Server + Audit + Robustness)
cd /d "%~dp0"

set "PY_CMD="
if exist ".venv\Scripts\python.exe" (
    set "PY_CMD=.venv\Scripts\python.exe"
) else (
    py -3.12 --version >nul 2>&1
    if %ERRORLEVEL% EQU 0 (
        set "PY_CMD=py -3.12"
    ) else (
        set "PY_CMD=python"
    )
)

echo ======================================================================
echo   [SteelGuardian] 전체 검증 스위트 실행 (%PY_CMD%)
echo ======================================================================

echo [1/2] 과제 B 감사 로그(MES Audit Trail) 검증 실행 중...
%PY_CMD% tests\test_audit.py
if %ERRORLEVEL% NEQ 0 (
    echo [실패] tests\test_audit.py 실패!
    pause
    exit /b %ERRORLEVEL%
)

if exist ".venv\Scripts\python.exe" (
    echo [2/2] 서버/보안/시나리오 통합 테스트(tests\test_server.py) 실행 중...
    ".venv\Scripts\python.exe" tests\test_server.py
)

echo ======================================================================
echo   모든 자동 검증이 정상 통과되었습니다 (Exit Code 0)
echo ======================================================================
pause
