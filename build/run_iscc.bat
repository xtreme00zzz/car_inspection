@echo off
setlocal
set "REPO=%~dp0.."
pushd "%REPO%"

REM Resolve version from app_version.py without invoking Python
set "APPVER="
for /f "tokens=2 delims== " %%v in ('findstr /B /C:"APP_VERSION" app_version.py') do set "APPVER=%%v"
if not defined APPVER set "APPVER=0.1.0"
set "APPVER=%APPVER: =%"
set "APPVER=%APPVER:\"=%"

REM Locate ISCC.exe
set "ISCCEXE="
for %%P in ("C:\Program Files (x86)\Inno Setup 6\ISCC.exe" "C:\Program Files\Inno Setup 6\ISCC.exe") do (
  if exist "%%~P" set "ISCCEXE=%%~P"
)
if not defined ISCCEXE (
  where iscc.exe >nul 2>nul && for /f %%X in ('where iscc.exe') do set "ISCCEXE=%%X"
)
if not defined ISCCEXE (
  echo ERROR: ISCC.exe (Inno Setup) not found in PATH or standard locations. Please install Inno Setup 6 and re-run.
  echo Download: https://jrsoftware.org/isdl.php
  popd
  exit /b 1
)

echo Building installer with Inno Setup...
"%ISCCEXE%" "build\installer.iss" ^
  /DAppVersion=%APPVER% ^
  /DDistRoot="%REPO%\dist" ^
  /DPayloadRoot="%REPO%\dist\release_payload" ^
  /DOutputDir="%REPO%\dist"
if errorlevel 1 (
  echo Inno Setup build failed.
  popd
  exit /b 1
)

echo Installer created in dist\
popd
exit /b 0
