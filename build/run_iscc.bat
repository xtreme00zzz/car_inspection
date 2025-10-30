@echo off
setlocal enabledelayedexpansion
set "REPO=%~dp0.."
pushd "%REPO%"

REM Resolve version from app_version.py
set "APPVER=0.1.0"
for /f "usebackq tokens=2 delims== " %%v in (`findstr /B /C:"APP_VERSION" app_version.py`) do set "APPVER=%%v"
set "APPVER=!APPVER:\"=!"
set "APPVER=!APPVER: =!"

REM Locate ISCC.exe (try PATH, then common install locations)
set "ISCCEXE="
for /f "delims=" %%X in ('where iscc.exe 2^>nul') do if not defined ISCCEXE set "ISCCEXE=%%~X"
if not defined ISCCEXE if exist "C:\Program Files\Inno Setup 6\ISCC.exe" set "ISCCEXE=C:\Program Files\Inno Setup 6\ISCC.exe"
if not defined ISCCEXE if exist "C:\Program Files (x86)\Inno Setup 6\ISCC.exe" set "ISCCEXE=C:\Program Files (x86)\Inno Setup 6\ISCC.exe"

if not defined ISCCEXE (
  echo INFO: Inno Setup (ISCC.exe) not found. Skipping installer build.
  popd
  exit /b 0
)

echo Building installer with Inno Setup...
"%ISCCEXE%" "build\installer.iss" /DAppVersion=!APPVER! /DDistRoot="%REPO%\dist" /DPayloadRoot="%REPO%\dist\release_payload" /DOutputDir="%REPO%\dist"
if errorlevel 1 (
  echo Inno Setup build failed.
  popd
  exit /b 1
)

echo Installer created in dist\
popd
exit /b 0
