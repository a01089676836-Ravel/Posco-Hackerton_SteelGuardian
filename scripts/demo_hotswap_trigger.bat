@echo off
chcp 65001 >nul
echo [SteelGuardian] 무중단 모델 핫스왑 트리거 호출 중...
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0demo_hotswap_trigger.ps1"
echo.
pause
