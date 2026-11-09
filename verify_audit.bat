@echo off
chcp 65001 >nul
title POSCO Smart Factory AI - Verify Audit Logger (Task B)
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

echo [Task B] MES 감사 로그(Audit Trail) 검증 실행 중 (%PY_CMD%)...
%PY_CMD% tests\test_audit.py
if %ERRORLEVEL% NEQ 0 (
    echo [실패] 감사 로그 검증 중 오류가 발생했습니다.
    pause
    exit /b %ERRORLEVEL%
)
echo [성공] 과제 B 감사 로그 모든 검증을 통과했습니다.
pause
