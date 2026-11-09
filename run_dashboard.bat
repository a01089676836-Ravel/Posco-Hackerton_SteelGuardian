@echo off
chcp 65001 >nul
title POSCO Smart Factory AI Dashboard Launcher
cd /d "%~dp0"

echo ========================================================
echo   POSCO Smart Factory AI Dashboard Starting...
echo ========================================================

set "STREAMLIT_HOST=127.0.0.1"
set "STREAMLIT_PORT=8501"

:: API_BASE_URL 등도 대시보드에 전달되도록 전체 항목을 읽는다.
if exist ".env" (
    for /f "usebackq eol=# tokens=1,* delims==" %%a in (".env") do set "%%a=%%b"
)

if exist ".venv\Scripts\streamlit.exe" (
    ".venv\Scripts\streamlit.exe" run app.py --server.address %STREAMLIT_HOST% --server.port %STREAMLIT_PORT% --browser.gatherUsageStats false
) else (
    py -3.12 -m streamlit run app.py --server.address %STREAMLIT_HOST% --server.port %STREAMLIT_PORT% --browser.gatherUsageStats false
)
pause
