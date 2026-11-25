@echo off
setlocal

set "PROJECT_ROOT=%~dp0.."
set "VENV_PYTHON=%PROJECT_ROOT%\.venv\Scripts\python.exe"

if not exist "%VENV_PYTHON%" (
    echo [ERROR] Virtual environment not found at "%VENV_PYTHON%".
    echo         Please initialize dependencies first by running: uv sync
    exit /b 1
)

cd /d "%PROJECT_ROOT%"
"%VENV_PYTHON%" -m pipeline %*
endlocal
