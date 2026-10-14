@echo off
setlocal
cd /d "%~dp0"
where py >nul 2>&1
if not errorlevel 1 (
    py -3 "%~dp0main.py" --all
) else (
    python "%~dp0main.py" --all
)
echo.
pause
