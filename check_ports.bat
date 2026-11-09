@echo off
setlocal enabledelayedexpansion
chcp 65001 >nul
echo ================================================================================
echo  POSCO AI 시스템 포트 점유 상태 점검 (check_ports)
echo ================================================================================

set PORT_CONFLICT=0

echo.
echo [1] FastAPI API 서버 포트 점검 (기본: 8000)...
netstat -ano | findstr /R /C:":8000 " > nul
if errorlevel 1 goto PORT_8000_OK
echo [경고] 8000번 포트가 이미 사용 중입니다.
for /f "tokens=5" %%a in ('netstat -ano ^| findstr /R /C:":8000 "') do (
    echo    - 점유 PID: %%a
    echo    - 수동 종료 명령: taskkill /PID %%a /F
)
set PORT_CONFLICT=1
goto CHECK_8501

:PORT_8000_OK
echo [OK] 8000번 포트 가용 상태입니다.

:CHECK_8501
echo.
echo [2] Streamlit 대시보드 포트 점검 (기본: 8501)...
netstat -ano | findstr /R /C:":8501 " > nul
if errorlevel 1 goto PORT_8501_OK
echo [경고] 8501번 포트가 이미 사용 중입니다.
for /f "tokens=5" %%a in ('netstat -ano ^| findstr /R /C:":8501 "') do (
    echo    - 점유 PID: %%a
    echo    - 수동 종료 명령: taskkill /PID %%a /F
)
set PORT_CONFLICT=1
goto FINISH

:PORT_8501_OK
echo [OK] 8501번 포트 가용 상태입니다.

:FINISH
echo.
echo ================================================================================
if "%PORT_CONFLICT%"=="1" (
    echo [경고] 포트 충돌이 감지되었습니다.
    echo 안전 정책에 따라 프로세스를 자동으로 강제 종료하지 않습니다.
    echo 1. 위 안내된 taskkill 명령어로 프로세스를 수동 종료하거나,
    echo 2. .env 파일에서 API_PORT 또는 STREAMLIT_PORT 번호를 변경해 주십시오.
    echo ================================================================================
    exit /b 1
)
echo [성공] 모든 포트(8000, 8501)가 정상적으로 가용 상태입니다.
echo ================================================================================
exit /b 0
