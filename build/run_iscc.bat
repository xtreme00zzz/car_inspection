@echo off
setlocal
set "REPO=%~dp0.."
pushd "%REPO%"

REM Resolve version from app_version.py
set "APPVER="
if exist ".venv-alpha-win\Scripts\python.exe" (
  for /f "usebackq delims=" %%v in (`".venv-alpha-win\Scripts\python.exe" -c "import app_version; print(app_version.APP_VERSION)"`) do set "APPVER=%%v"
)
if not defined APPVER (
  for /f "usebackq delims=" %%v in (`python -c "import app_version; print(app_version.APP_VERSION)"`) do set "APPVER=%%v"
)
if not defined APPVER set "APPVER=0.1.0"

REM Locate ISCC.exe
set "ISCC=iscc"
where %ISCC% >nul 2>nul
if errorlevel 1 (
  if exist "C:\Program Files (x86)\Inno Setup 6\ISCC.exe" set "ISCC=C:\Program Files (x86)\Inno Setup 6\ISCC.exe"
)
if "%ISCC%"=="iscc" (
  where %ISCC% >nul 2>nul
)
if errorlevel 1 (
  if exist "C:\Program Files\Inno Setup 6\ISCC.exe" set "ISCC=C:\Program Files\Inno Setup 6\ISCC.exe"
)
if "%ISCC%"=="iscc" (
  where %ISCC% >nul 2>nul
)
if errorlevel 1 (
  echo ERROR: ISCC.exe (Inno Setup) not found in PATH. Please install Inno Setup 6 and re-run.
  echo Download: https://jrsoftware.org/isdl.php
  popd
  exit /b 1
)

echo Building installer with Inno Setup...
"%ISCC%" "build\installer.iss" ^
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

