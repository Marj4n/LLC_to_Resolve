@echo off
setlocal
cd /d "%~dp0"
echo ==============================================
echo   Marj4n - LosslessCut to DaVinci Resolve
echo ==============================================
where py >nul 2>&1
if not errorlevel 1 (
    if "%~1"=="" (py -3 "%~dp0main.py") else (py -3 "%~dp0main.py" --llc "%~1")
) else (
    where python >nul 2>&1
    if errorlevel 1 (
        echo [ERROR] Python is not installed or not on PATH.
        echo Install Python 3.11+ and retry.
    ) else (
        if "%~1"=="" (python "%~dp0main.py") else (python "%~dp0main.py" --llc "%~1")
    )
)
echo.
pause
