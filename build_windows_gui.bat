@echo off
setlocal

cd /d "%~dp0"

echo.
echo ==========================================
echo   Build PGL Sorting Engine Windows App
echo ==========================================
echo.

where py >nul 2>nul
if errorlevel 1 (
    echo Python launcher "py" was not found.
    echo Install Python 3.11 or newer for Windows and try again.
    pause
    exit /b 1
)

if not exist ".venv-gui\Scripts\python.exe" (
    echo Creating Windows build environment...
    py -3.11 -m venv .venv-gui
    if errorlevel 1 (
        py -m venv .venv-gui
    )
)

call ".venv-gui\Scripts\activate.bat"

echo Installing project and GUI build tools...
python -m pip install --upgrade pip
python -m pip install -e ".[gui-build]"

if errorlevel 1 (
    echo.
    echo Installation failed.
    pause
    exit /b 1
)

echo.
echo Building executable...
python -m PyInstaller ^
    --noconfirm ^
    --clean ^
    --onefile ^
    --windowed ^
    --name "PGL_Sorting_Engine" ^
    --paths "src" ^
    --collect-all openpyxl ^
    "src\pgl_sorting_engine\gui.py"

if errorlevel 1 (
    echo.
    echo Build failed.
    pause
    exit /b 1
)

echo.
echo ==========================================
echo Build complete.
echo.
echo Executable:
echo %CD%\dist\PGL_Sorting_Engine.exe
echo ==========================================
echo.

pause
