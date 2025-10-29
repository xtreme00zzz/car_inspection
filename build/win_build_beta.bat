@echo off
setlocal enabledelayedexpansion

REM Windows beta build script (one-dir, one-file, payload, installer)
REM Derives repo root from this script's location
set "REPO=%~dp0.."
set "APP_NAME=eF Drift Car Scrutineer Beta"
pushd "%REPO%"

echo [1/6] Cleaning previous beta build artifacts...
if exist "build\pyinstaller-build-beta" rmdir /s /q "build\pyinstaller-build-beta"
if exist "build\pyinstaller-build-beta-onefile" rmdir /s /q "build\pyinstaller-build-beta-onefile"
if exist "dist\%APP_NAME%" rmdir /s /q "dist\%APP_NAME%"
if exist "dist\%APP_NAME%.exe" del /f /q "dist\%APP_NAME%.exe"
if exist "dist\beta_payload" rmdir /s /q "dist\beta_payload"
if exist "build\reference_cars_beta" rmdir /s /q "build\reference_cars_beta"
if not exist "dist" mkdir "dist"

echo [2/6] Preparing trimmed reference assets...
call "%REPO%\.venv-alpha-win\Scripts\python.exe" "%REPO%\build\prepare_alpha_reference.py" --src "%REPO%\reference_cars" --dest "%REPO%\build\reference_cars_beta"
if errorlevel 1 goto :error

echo [3/6] Building beta onedir distribution...
set "TRIM=%REPO%\build\reference_cars_beta"
set "OD1=--add-data" & set "OD2=%TRIM%;reference_cars"
set "OD3=--add-data" & set "OD4=%REPO%\icon.ico;."
set "OD5=--add-data" & set "OD6=%REPO%\README.md;."
set "OD7=--add-data" & set "OD8=%REPO%\PACKAGING_BETA.md;docs"
set "OD9=--add-data" & set "OD10=%REPO%\build\beta_release_notes.txt;docs"
call "%REPO%\.venv-alpha-win\Scripts\python.exe" -m PyInstaller --noconfirm --clean --log-level=WARN --onedir --windowed ^
  --icon "%REPO%\icon.ico" --name "%APP_NAME%" ^
  --distpath "%REPO%\dist" --workpath "%REPO%\build\pyinstaller-build-beta" --specpath "%REPO%\build" ^
  %OD1% "%OD2%" %OD3% "%OD4%" %OD5% "%OD6%" %OD7% "%OD8%" %OD9% "%OD10%" ^
  "%REPO%\ui_app.py"
if errorlevel 1 goto :error

echo [4/6] Building beta onefile executable...
set "TRIM=%REPO%\build\reference_cars_beta"
set "AA1=--add-data" & set "AA2=%TRIM%;reference_cars"
set "AA3=--add-data" & set "AA4=%REPO%\icon.ico;."
set "AA5=--add-data" & set "AA6=%REPO%\README.md;."
set "AA7=--add-data" & set "AA8=%REPO%\PACKAGING_BETA.md;docs"
set "AA9=--add-data" & set "AA10=%REPO%\build\beta_release_notes.txt;docs"
call "%REPO%\.venv-alpha-win\Scripts\python.exe" -m PyInstaller --noconfirm --clean --log-level=WARN --onefile --windowed ^
  --icon "%REPO%\icon.ico" --name "%APP_NAME%" ^
  --distpath "%REPO%\dist" --workpath "%REPO%\build\pyinstaller-build-beta-onefile" --specpath "%REPO%\build" ^
  %AA1% "%AA2%" %AA3% "%AA4%" %AA5% "%AA6%" %AA7% "%AA8%" %AA9% "%AA10%" ^
  "%REPO%\ui_app.py"
if errorlevel 1 goto :error

if not exist "%REPO%\dist\%APP_NAME%" (
  echo Onedir beta build missing at "dist\%APP_NAME%"
  goto :error
)
if not exist "%REPO%\dist\%APP_NAME%.exe" (
  echo Onefile beta build missing at "dist\%APP_NAME%.exe"
  goto :error
)

echo [5/6] Preparing beta installer payload...
mkdir "%REPO%\dist\beta_payload" 2>nul
mkdir "%REPO%\dist\beta_payload\docs" 2>nul
xcopy /E /I /Y "%REPO%\dist\%APP_NAME%" "%REPO%\dist\beta_payload\app" >nul
copy /Y "%REPO%\dist\%APP_NAME%.exe" "%REPO%\dist\beta_payload\%APP_NAME%.exe" >nul
copy /Y "%REPO%\build\beta_release_notes.txt" "%REPO%\dist\beta_payload\docs\beta_release_notes.txt" >nul
copy /Y "%REPO%\README.md" "%REPO%\dist\beta_payload\docs\README.md" >nul
rem Resolve app version from app_version.py
set "APPVER="
for /f "usebackq delims=" %%v in (`"%REPO%\.venv-alpha-win\Scripts\python.exe" -c "import app_version; print(app_version.APP_VERSION)"`) do set "APPVER=%%v"
if not defined APPVER (
  set "APPVER=BETA-0.1.0"
)
echo eF Drift Car Scrutineer %APPVER%>"%REPO%\dist\beta_payload\VERSION.txt"

echo [6/6] Generating installer branding assets...
call "%REPO%\.venv-alpha-win\Scripts\python.exe" "%REPO%\build\generate_branding_assets.py"
if errorlevel 1 goto :error

echo Build complete.
echo   Onedir dist : dist\%APP_NAME%
echo   Onefile exe : dist\%APP_NAME%.exe
echo   Payload root: dist\beta_payload
popd
exit /b 0

:error
echo Beta build failed with errorlevel %errorlevel%.
popd
exit /b %errorlevel%
