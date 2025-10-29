@echo off
setlocal enabledelayedexpansion
REM Locate ISCC.exe and compile installer_alpha.iss

set "REPO=%~dp0.."
set "ISS=%REPO%\build\installer_alpha.iss"

if not exist "%ISS%" (
  echo ISS file not found: %ISS%
  exit /b 1
)

set "ISCC_PATH="
for /f "delims=" %%F in ('where /R C:\ ISCC.exe 2^>nul') do (
  set "ISCC_PATH=%%F"
  goto :found
)

echo ISCC.exe not found on this system.
exit /b 2

:found
echo Using ISCC: "%ISCC_PATH%"
"%ISCC_PATH%" "%ISS%"
exit /b %errorlevel%

