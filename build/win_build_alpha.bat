@echo off
setlocal enabledelayedexpansion

REM Windows alpha build script (one-dir, one-file, payload, installer)
REM Derives repo root from this script's location
set "REPO=%~dp0.."
set "APP_NAME=eF Drift Car Scrutineer Alpha"
pushd "%REPO%"

echo [1/6] Cleaning previous build artifacts...
if exist "build\pyinstaller-build" rmdir /s /q "build\pyinstaller-build"
if exist "build\pyinstaller-build-onefile" rmdir /s /q "build\pyinstaller-build-onefile"
REM Remove previous Linux onefile artifact that blocks onedir directory creation
if exist "dist\car_inspection_alpha" (
  rmdir /s /q "dist\car_inspection_alpha" 2>nul
  del /f /q "dist\car_inspection_alpha" 2>nul
)
if exist "dist\car_inspection_alpha.exe" del /f /q "dist\car_inspection_alpha.exe"
if exist "dist\alpha_payload" rmdir /s /q "dist\alpha_payload"
if exist "build\reference_cars_alpha" rmdir /s /q "build\reference_cars_alpha"
if not exist "dist" mkdir "dist"

echo [2/6] Preparing trimmed reference assets...
call "%REPO%\.venv-alpha-win\Scripts\python.exe" "%REPO%\build\prepare_alpha_reference.py" --src "%REPO%\reference_cars" --dest "%REPO%\build\reference_cars_alpha"
if errorlevel 1 goto :error

echo [3/6] Building onedir distribution...
set "TRIM=%REPO%\build\reference_cars_alpha"
set "OD1=--add-data" & set "OD2=%TRIM%;reference_cars"
set "OD3=--add-data" & set "OD4=%REPO%\icon.ico;."
set "OD5=--add-data" & set "OD6=%REPO%\README.md;."
set "OD7=--add-data" & set "OD8=%REPO%\PACKAGING_ALPHA.md;docs"
set "OD9=--add-data" & set "OD10=%REPO%\build\alpha_release_notes.txt;docs"
call "%REPO%\.venv-alpha-win\Scripts\python.exe" -m PyInstaller --noconfirm --clean --log-level=WARN --onedir --windowed ^
  --icon "%REPO%\icon.ico" --name "%APP_NAME%" ^
  --distpath "%REPO%\dist" --workpath "%REPO%\build\pyinstaller-build" --specpath "%REPO%\build" ^
  %OD1% "%OD2%" %OD3% "%OD4%" %OD5% "%OD6%" %OD7% "%OD8%" %OD9% "%OD10%" ^
  "%REPO%\ui_app.py"
if errorlevel 1 goto :error

echo [4/6] Building onefile bootstrap executable...
set "TRIM=%REPO%\build\reference_cars_alpha"
set "AA1=--add-data" & set "AA2=%TRIM%;reference_cars"
set "AA3=--add-data" & set "AA4=%REPO%\icon.ico;."
set "AA5=--add-data" & set "AA6=%REPO%\README.md;."
set "AA7=--add-data" & set "AA8=%REPO%\PACKAGING_ALPHA.md;docs"
set "AA9=--add-data" & set "AA10=%REPO%\build\alpha_release_notes.txt;docs"
call "%REPO%\.venv-alpha-win\Scripts\python.exe" -m PyInstaller --noconfirm --clean --log-level=WARN --onefile --windowed ^
  --icon "%REPO%\icon.ico" --name "%APP_NAME%" ^
  --distpath "%REPO%\dist" --workpath "%REPO%\build\pyinstaller-build-onefile" --specpath "%REPO%\build" ^
  %AA1% "%AA2%" %AA3% "%AA4%" %AA5% "%AA6%" %AA7% "%AA8%" %AA9% "%AA10%" ^
  "%REPO%\ui_app.py"
if errorlevel 1 goto :error

if not exist "%REPO%\dist\%APP_NAME%" (
  echo Onedir build missing at "dist\%APP_NAME%"
  goto :error
)
if not exist "%REPO%\dist\%APP_NAME%.exe" (
  echo Onefile build missing at "dist\%APP_NAME%.exe"
  goto :error
)

echo [5/6] Preparing installer payload...
mkdir "%REPO%\dist\alpha_payload" 2>nul
mkdir "%REPO%\dist\alpha_payload\docs" 2>nul
xcopy /E /I /Y "%REPO%\dist\%APP_NAME%" "%REPO%\dist\alpha_payload\app" >nul
copy /Y "%REPO%\dist\%APP_NAME%.exe" "%REPO%\dist\alpha_payload\%APP_NAME%.exe" >nul
copy /Y "%REPO%\build\alpha_release_notes.txt" "%REPO%\dist\alpha_payload\docs\alpha_release_notes.txt" >nul
copy /Y "%REPO%\README.md" "%REPO%\dist\alpha_payload\docs\README.md" >nul
echo eF Drift Car Scrutineer ALPHA-0.1.0>"%REPO%\dist\alpha_payload\VERSION.txt"

echo [6/6] Generating installer branding assets...
call "%REPO%\.venv-alpha-win\Scripts\python.exe" "%REPO%\build\generate_branding_assets.py"
if errorlevel 1 goto :error

echo [7/6] Compiling installer with Inno Setup...
where iscc.exe >nul 2>nul
if errorlevel 1 (
  echo iscc.exe not found on PATH. Skipping installer compilation.
) else (
  iscc.exe "%REPO%\build\installer_alpha.iss"
  if errorlevel 1 goto :error
)

echo Build complete.
echo   Onedir dist : dist\%APP_NAME%
echo   Onefile exe : dist\%APP_NAME%.exe
echo   Payload root: dist\alpha_payload
popd
exit /b 0

:error
echo Build failed with errorlevel %errorlevel%.
popd
exit /b %errorlevel%
