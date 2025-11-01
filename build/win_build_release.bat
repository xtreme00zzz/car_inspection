@echo off
setlocal enabledelayedexpansion

REM Windows release build script (one-dir, one-file, payload, updater)
REM Derives repo root from this script's location
set "REPO=%~dp0.."
set "APP_NAME=eF Drift Car Scrutineer"
set "APP_NAME_FILE=efdrift-scrutineer"
set "PY=%REPO%\.venv-alpha-win\Scripts\python.exe"
pushd "%REPO%"

rem Prefer a custom icon if present; fallback to repo icon.ico
set "ICON_PATH=C:\Users\alexa\Videos\Stream Assets\next participants\icon.ico"
if not exist "%ICON_PATH%" set "ICON_PATH=%REPO%\icon.ico"

rem Allow optional exclusion of heavy reference data for smaller onefile build
set "NO_REF_DATA=%NO_REF_DATA%"
set "MAIN=%REPO%\ui_app.py"
set "DOWNLOAD_REF_SCRIPT=%REPO%\build\download_reference_pack.py"
set "FORCE_REF_DOWNLOAD=%FORCE_REF_DOWNLOAD%"
set "PY_DATA_ARGS="

echo [1/6] Cleaning previous release build artifacts...
if exist "build\pyinstaller-build-release" rmdir /s /q "build\pyinstaller-build-release"
if exist "build\pyinstaller-build-release-onefile" rmdir /s /q "build\pyinstaller-build-release-onefile"
if exist "build\pyinstaller-build-release-updater" rmdir /s /q "build\pyinstaller-build-release-updater"
if exist "dist\%APP_NAME%" rmdir /s /q "dist\%APP_NAME%"
if exist "dist\%APP_NAME%.exe" del /f /q "dist\%APP_NAME%.exe"
if exist "dist\release_payload" rmdir /s /q "dist\release_payload"
if not exist "dist" mkdir "dist"

if not exist "%DOWNLOAD_REF_SCRIPT%" goto :after_ref_download
set "NEED_REF_DOWNLOAD="
if /i "%FORCE_REF_DOWNLOAD%"=="true" set "NEED_REF_DOWNLOAD=1"
if /i "%FORCE_REF_DOWNLOAD%"=="1" set "NEED_REF_DOWNLOAD=1"
if not exist "%REPO%\reference_cars" set "NEED_REF_DOWNLOAD=1"
if not defined NEED_REF_DOWNLOAD goto :after_ref_download
echo [Prep] Ensuring reference_cars folder is present (Drive download)...
if not exist "%REPO%\.cache" mkdir "%REPO%\.cache" >nul 2>&1
set "DL_DEST=%REPO%\reference_cars"
set "DL_ARTIFACT=%REPO%\.cache\reference_cars.zip"
if exist "%PY%" (
  if /i "%FORCE_REF_DOWNLOAD%"=="true" (
    call "%PY%" "%DOWNLOAD_REF_SCRIPT%" --dest "%DL_DEST%" --artifact "%DL_ARTIFACT%" --force
  ) else if /i "%FORCE_REF_DOWNLOAD%"=="1" (
    call "%PY%" "%DOWNLOAD_REF_SCRIPT%" --dest "%DL_DEST%" --artifact "%DL_ARTIFACT%" --force
  ) else (
    call "%PY%" "%DOWNLOAD_REF_SCRIPT%" --dest "%DL_DEST%" --artifact "%DL_ARTIFACT%"
  )
) else (
  if /i "%FORCE_REF_DOWNLOAD%"=="true" (
    call python "%DOWNLOAD_REF_SCRIPT%" --dest "%DL_DEST%" --artifact "%DL_ARTIFACT%" --force
  ) else if /i "%FORCE_REF_DOWNLOAD%"=="1" (
    call python "%DOWNLOAD_REF_SCRIPT%" --dest "%DL_DEST%" --artifact "%DL_ARTIFACT%" --force
  ) else (
    call python "%DOWNLOAD_REF_SCRIPT%" --dest "%DL_DEST%" --artifact "%DL_ARTIFACT%"
  )
)
if errorlevel 1 goto :error
:after_ref_download

rem Prepare shared PyInstaller data arguments (reference pack + icon)
set "PY_DATA_ARGS="
if exist "%REPO%\reference_cars" (
  set "PY_DATA_ARGS=--add-data ""%REPO%\reference_cars;reference_cars"""
)
if exist "%ICON_PATH%" (
  if defined PY_DATA_ARGS (
    set "PY_DATA_ARGS=%PY_DATA_ARGS% --add-data ""%ICON_PATH%;icon.ico"""
  ) else (
    set "PY_DATA_ARGS=--add-data ""%ICON_PATH%;icon.ico"""
  )
)

echo [2/6] Building release onedir distribution...
if exist "%PY%" (
  call "%PY%" -m PyInstaller --noconfirm --clean --log-level=WARN --onedir --windowed --icon "%ICON_PATH%" --name "%APP_NAME_FILE%" --distpath "%REPO%\dist" --workpath "%REPO%\build\pyinstaller-build-release" --specpath "%REPO%\build" %PY_DATA_ARGS% ui_app.py
) else (
  call pyinstaller --noconfirm --clean --log-level=WARN --onedir --windowed --icon "%ICON_PATH%" --name "%APP_NAME_FILE%" --distpath "%REPO%\dist" --workpath "%REPO%\build\pyinstaller-build-release" --specpath "%REPO%\build" %PY_DATA_ARGS% ui_app.py
)
if errorlevel 1 goto :error

echo [3/6] Building release onefile executable...
if exist "%PY%" (
  call "%PY%" -m PyInstaller --noconfirm --clean --log-level=WARN --onefile --windowed --icon "%ICON_PATH%" --name "%APP_NAME_FILE%" --distpath "%REPO%\dist" --workpath "%REPO%\build\pyinstaller-build-release-onefile" --specpath "%REPO%\build" %PY_DATA_ARGS% ui_app.py
) else (
  call pyinstaller --noconfirm --clean --log-level=WARN --onefile --windowed --icon "%ICON_PATH%" --name "%APP_NAME_FILE%" --distpath "%REPO%\dist" --workpath "%REPO%\build\pyinstaller-build-release-onefile" --specpath "%REPO%\build" %PY_DATA_ARGS% ui_app.py
)
if errorlevel 1 goto :error

rem Rename artifacts to friendly display names with spaces
if exist "%REPO%\dist\%APP_NAME_FILE%" (
  if exist "%REPO%\dist\%APP_NAME%" rmdir /s /q "%REPO%\dist\%APP_NAME%"
  ren "%REPO%\dist\%APP_NAME_FILE%" "%APP_NAME%"
)
rem Ensure the exe INSIDE the onedir folder matches the friendly name
if exist "%REPO%\dist\%APP_NAME%\%APP_NAME_FILE%.exe" (
  del /f /q "%REPO%\dist\%APP_NAME%\%APP_NAME%.exe" 2>nul
  ren "%REPO%\dist\%APP_NAME%\%APP_NAME_FILE%.exe" "%APP_NAME%.exe"
)
if exist "%REPO%\dist\%APP_NAME_FILE%.exe" (
  del /f /q "%REPO%\dist\%APP_NAME%.exe" 2>nul
  ren "%REPO%\dist\%APP_NAME_FILE%.exe" "%APP_NAME%.exe"
)

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
if exist "%PY%" (
  call "%PY%" -m PyInstaller --noconfirm --clean --log-level=WARN --onefile --console ^
  --icon "%ICON_PATH%" ^
  --name "eF Drift Car Scrutineer Updater" ^
  --distpath "%REPO%\dist" --workpath "%REPO%\build\pyinstaller-build-release-updater" --specpath "%REPO%\build" ^
  "%REPO%\tools\windows_updater_stub.py"
) else (
  call pyinstaller --noconfirm --clean --log-level=WARN --onefile --console ^
  --icon "%ICON_PATH%" ^
  --name "eF Drift Car Scrutineer Updater" ^
  --distpath "%REPO%\dist" --workpath "%REPO%\build\pyinstaller-build-release-updater" --specpath "%REPO%\build" ^
  "%REPO%\tools\windows_updater_stub.py"
)
if errorlevel 1 goto :error
copy /Y "%REPO%\dist\eF Drift Car Scrutineer Updater.exe" "%REPO%\dist\%APP_NAME%\eF Drift Car Scrutineer Updater.exe" >nul
copy /Y "%REPO%\dist\eF Drift Car Scrutineer Updater.exe" "%REPO%\dist\release_payload\eF Drift Car Scrutineer Updater.exe" >nul

echo [6/6] Build complete.
echo   Onedir dist : dist\%APP_NAME%
echo   Onefile exe : dist\%APP_NAME%.exe
echo   Payload root: dist\release_payload
echo.
REM Optional: Compile installer (handled by helper script; it detects ISCC)
if exist "build\run_iscc.bat" (
  echo [Extra] Attempting to compile installer with Inno Setup...
  call build\run_iscc.bat
)
popd
exit /b 0

:error
echo Release build failed with errorlevel %errorlevel%.
popd
exit /b %errorlevel%
