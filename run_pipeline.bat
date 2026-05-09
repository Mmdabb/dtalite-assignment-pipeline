@echo off
setlocal

cd /d "%~dp0"

set "SETUP_DIR=setup"
set "ENV_NAME=dtalite_pipeline"
set "LOG_DIR=logs"
set "CONFIG_FILE=%~1"

if "%CONFIG_FILE%"=="" (
    for /f "delims=" %%I in ('powershell -NoProfile -ExecutionPolicy Bypass -File "%SETUP_DIR%\select_config.ps1"') do set "CONFIG_FILE=%%I"
)

if "%CONFIG_FILE%"=="" (
    echo No config file selected. Exiting.
    pause
    exit /b 1
)

if not exist "%LOG_DIR%" mkdir "%LOG_DIR%"

set "LOG_FILE=%LOG_DIR%\run_pipeline_log.txt"

echo ========================================== > "%LOG_FILE%"
echo DTALite Pipeline Run Log >> "%LOG_FILE%"
echo Started at: %date% %time% >> "%LOG_FILE%"
echo Project folder: %cd% >> "%LOG_FILE%"
echo Selected config: %CONFIG_FILE% >> "%LOG_FILE%"
echo ========================================== >> "%LOG_FILE%"
echo. >> "%LOG_FILE%"

echo ==========================================
echo DTALite Pipeline Run
echo Selected config: %CONFIG_FILE%
echo Log file: %LOG_FILE%
echo ==========================================

if not exist "%CONFIG_FILE%" (
    echo [ERROR] Config file does not exist: %CONFIG_FILE%
    echo [ERROR] Config file does not exist: %CONFIG_FILE% >> "%LOG_FILE%"
    pause
    exit /b 1
)

set "CONDA_DIR="

if exist "%USERPROFILE%\Miniconda3\Scripts\activate.bat" (
    set "CONDA_DIR=%USERPROFILE%\Miniconda3"
) else if exist "%USERPROFILE%\anaconda3\Scripts\activate.bat" (
    set "CONDA_DIR=%USERPROFILE%\anaconda3"
) else if exist "%LOCALAPPDATA%\Miniconda3\Scripts\activate.bat" (
    set "CONDA_DIR=%LOCALAPPDATA%\Miniconda3"
) else if exist "%LOCALAPPDATA%\anaconda3\Scripts\activate.bat" (
    set "CONDA_DIR=%LOCALAPPDATA%\anaconda3"
)

if defined CONDA_DIR (
    call "%CONDA_DIR%\Scripts\activate.bat" >> "%LOG_FILE%" 2>&1
) else (
    call conda activate >> "%LOG_FILE%" 2>&1
)

if %errorlevel% neq 0 (
    echo [ERROR] Conda was not found. Please run setup_environment.bat first.
    echo [ERROR] Conda was not found. >> "%LOG_FILE%"
    pause
    exit /b 1
)

call conda activate "%ENV_NAME%" >> "%LOG_FILE%" 2>&1

if %errorlevel% neq 0 (
    echo [ERROR] Environment was not found. Please run setup_environment.bat first.
    echo [ERROR] Environment was not found. >> "%LOG_FILE%"
    pause
    exit /b 1
)

echo [INFO] Checking setup...
echo [INFO] Checking setup with %CONFIG_FILE%... >> "%LOG_FILE%"
python "%SETUP_DIR%\check_setup.py" "%CONFIG_FILE%" >> "%LOG_FILE%" 2>&1

if %errorlevel% neq 0 (
    echo [ERROR] Setup check failed. Please review %LOG_FILE%.
    pause
    exit /b 1
)

echo [INFO] Running pipeline with %CONFIG_FILE%...
echo [INFO] Running pipeline with %CONFIG_FILE%... >> "%LOG_FILE%"
python main.py --config "%CONFIG_FILE%" >> "%LOG_FILE%" 2>&1

if %errorlevel% neq 0 (
    echo [ERROR] Pipeline failed. Please review %LOG_FILE%.
    pause
    exit /b 1
)

echo [OK] Pipeline completed successfully.
echo [OK] Pipeline completed successfully. >> "%LOG_FILE%"
pause
