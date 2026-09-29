@echo off
cd /d "%~dp0"
if exist "%~dp0dist\Sparky-0.6.exe" (
  start "" "%~dp0dist\Sparky-0.6.exe"
  exit /b 0
)
if exist "%~dp0dist\Sparky-0.5.exe" (
  start "" "%~dp0dist\Sparky-0.5.exe"
  exit /b 0
)
if exist "%~dp0dist\Sparky-0.4.exe" (
  start "" "%~dp0dist\Sparky-0.4.exe"
  exit /b 0
)
if exist "%~dp0dist\Sparky-0.3.exe" (
  start "" "%~dp0dist\Sparky-0.3.exe"
  exit /b 0
)
if exist "%~dp0dist\Sparky-0.2.exe" (
  start "" "%~dp0dist\Sparky-0.2.exe"
  exit /b 0
)
if exist "%~dp0dist\Sparky.exe" (
  start "" "%~dp0dist\Sparky.exe"
  exit /b 0
)
where py >nul 2>nul
if not errorlevel 1 (
  py -m sparky.gui
  goto :done
)
where python >nul 2>nul
if not errorlevel 1 (
  python -m sparky.gui
  goto :done
)
set "SPARKY_PY=%USERPROFILE%\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe"
if exist "%SPARKY_PY%" (
  "%SPARKY_PY%" -m sparky.gui
  goto :done
)
echo Sparky could not find Python 3.10 or newer.
:done
if errorlevel 1 pause
