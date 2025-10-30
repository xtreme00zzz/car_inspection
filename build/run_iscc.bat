@echo off
setlocal enableextensions

REM Derive repo root from this script location (works even if double-clicked)
set "SCRIPT_DIR=%~dp0"
set "REPO=%SCRIPT_DIR%.."

REM Normalize directories we pass to ISCC
set "DIST=%REPO%\dist"
set "PAYLOAD=%REPO%\dist\release_payload"
set "OUT=%REPO%\dist"
REM To avoid collisions with a locked installer in dist, write to a subfolder
set "OUT_ACTUAL=%OUT%\_installer"

REM Detect ISCC.exe in common install locations
set "ISCC_PATH="
if exist "C:\Program Files (x86)\Inno Setup 6\ISCC.exe" set "ISCC_PATH=C:\Program Files (x86)\Inno Setup 6\ISCC.exe"
if not defined ISCC_PATH if exist "C:\Program Files\Inno Setup 6\ISCC.exe" set "ISCC_PATH=C:\Program Files\Inno Setup 6\ISCC.exe"
if not defined ISCC_PATH if exist "%LOCALAPPDATA%\Programs\Inno Setup 6\ISCC.exe" set "ISCC_PATH=%LOCALAPPDATA%\Programs\Inno Setup 6\ISCC.exe"

if not defined ISCC_PATH (
  echo ISCC.exe not found. Please install Inno Setup 6 or adjust this script.
  exit /b 1
)

echo Using ISCC at: "%ISCC_PATH%"
REM If a preferred installer icon exists on this machine, pass it to the compiler
set "INSTALLER_ICON=C:\Users\alexa\Videos\Stream Assets\next participants\icon.ico"
set ICON_DEFINE=
if exist "%INSTALLER_ICON%" (
  echo Using installer icon: "%INSTALLER_ICON%"
  set ICON_DEFINE=/DInstallerIcon="%INSTALLER_ICON%"
)
pushd "%REPO%" >nul
"%ISCC_PATH%" build\installer.iss ^
  /DAppVersion=0.1.0 ^
  /DDistRoot="%DIST%" ^
  /DPayloadRoot="%PAYLOAD%" ^
  /DOutputDir="%OUT_ACTUAL%" %ICON_DEFINE%
set "ERR=%ERRORLEVEL%"
popd >nul

exit /b %ERR%
