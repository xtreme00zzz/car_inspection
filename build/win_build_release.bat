@echo off
setlocal enabledelayedexpansion

REM Windows release build script (one-dir, one-file, payload, updater)
REM Derives repo root from this script's location
set "REPO=%~dp0.."
set "APP_NAME=eF Drift Car Scrutineer"
set "PY=%REPO%\.venv-alpha-win\Scripts\python.exe"
if not exist "%PY%" set "PY=python"
pushd "%REPO%"

echo [1/6] Cleaning previous release build artifacts...
if exist "build\pyinstaller-build-release" rmdir /s /q "build\pyinstaller-build-release"
if exist "build\pyinstaller-build-release-onefile" rmdir /s /q "build\pyinstaller-build-release-onefile"
if exist "build\pyinstaller-build-release-updater" rmdir /s /q "build\pyinstaller-build-release-updater"
if exist "dist\%APP_NAME%" rmdir /s /q "dist\%APP_NAME%"
if exist "dist\%APP_NAME%.exe" del /f /q "dist\%APP_NAME%.exe"
if exist "dist\release_payload" rmdir /s /q "dist\release_payload"
if not exist "dist" mkdir "dist"

echo [2/6] Building release onedir distribution...
set "OD1=--add-data" & set "OD2=%REPO%\reference_cars;reference_cars"
set "OD3=--add-data" & set "OD4=%REPO%\icon.ico;."
set "OD5=--add-data" & set "OD6=%REPO%\README.md;."
call "%PY%" -m PyInstaller --noconfirm --clean --log-level=WARN --onedir --windowed ^
  --icon "%REPO%\icon.ico" --name "%APP_NAME%" ^
  --distpath "%REPO%\dist" --workpath "%REPO%\build\pyinstaller-build-release" --specpath "%REPO%\build" ^
  %OD1% "%OD2%" %OD3% "%OD4%" %OD5% "%OD6%" ^
  "%REPO%\ui_app.py"
if errorlevel 1 goto :error

echo [3/6] Building release onefile executable...
set "AA1=--add-data" & set "AA2=%REPO%\reference_cars;reference_cars"
set "AA3=--add-data" & set "AA4=%REPO%\icon.ico;."
set "AA5=--add-data" & set "AA6=%REPO%\README.md;."
call "%PY%" -m PyInstaller --noconfirm --clean --log-level=WARN --onefile --windowed ^
  --icon "%REPO%\icon.ico" --name "%APP_NAME%" ^
  --distpath "%REPO%\dist" --workpath "%REPO%\build\pyinstaller-build-release-onefile" --specpath "%REPO%\build" ^
  %AA1% "%AA2%" %AA3% "%AA4%" %AA5% "%AA6%" ^
  "%REPO%\ui_app.py"
if errorlevel 1 goto :error

if not exist "%REPO%\dist\%APP_NAME%" (
  echo Onedir release build missing at "dist\%APP_NAME%"
  goto :error
)
if not exist "%REPO%\dist\%APP_NAME%.exe" (
  echo Onefile release build missing at "dist\%APP_NAME%.exe"
  goto :error
)

echo [4/6] Preparing release payload...
mkdir "%REPO%\dist\release_payload" 2>nul
mkdir "%REPO%\dist\release_payload\docs" 2>nul
xcopy /E /I /Y "%REPO%\dist\%APP_NAME%" "%REPO%\dist\release_payload\app" >nul
copy /Y "%REPO%\dist\%APP_NAME%.exe" "%REPO%\dist\release_payload\%APP_NAME%.exe" >nul
copy /Y "%REPO%\README.md" "%REPO%\dist\release_payload\docs\README.md" >nul

rem Resolve app version from app_version.py
set "APPVER="
for /f "usebackq delims=" %%v in (`"%PY%" -c "import app_version; print(app_version.APP_VERSION)"`) do set "APPVER=%%v"
if not defined APPVER (
  set "APPVER=0.1.0"
)
echo eF Drift Car Scrutineer %APPVER%>"%REPO%\dist\release_payload\VERSION.txt"

echo [5/6] Building updater stub...
call "%PY%" -m PyInstaller --noconfirm --clean --log-level=WARN --onefile --console ^
  --name "eF Drift Car Scrutineer Updater" ^
  --distpath "%REPO%\dist" --workpath "%REPO%\build\pyinstaller-build-release-updater" --specpath "%REPO%\build" ^
  "%REPO%\tools\windows_updater_stub.py"
if errorlevel 1 goto :error
copy /Y "%REPO%\dist\eF Drift Car Scrutineer Updater.exe" "%REPO%\dist\%APP_NAME%\eF Drift Car Scrutineer Updater.exe" >nul
copy /Y "%REPO%\dist\eF Drift Car Scrutineer Updater.exe" "%REPO%\dist\release_payload\eF Drift Car Scrutineer Updater.exe" >nul

echo [6/6] Build complete.
echo   Onedir dist : dist\%APP_NAME%
echo   Onefile exe : dist\%APP_NAME%.exe
echo   Payload root: dist\release_payload
echo.
REM Optional: Compile installer if ISCC.exe is available
for %%X in (iscc.exe ISCC.exe) do (
  where %%X >nul 2>nul && (
    echo [Extra] Compiling installer with Inno Setup...
    call build\run_iscc.bat
    goto :done_iscc
  )
)
:done_iscc
popd
exit /b 0

:error
echo Release build failed with errorlevel %errorlevel%.
popd
exit /b %errorlevel%
