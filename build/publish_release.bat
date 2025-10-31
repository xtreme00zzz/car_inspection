@echo off
setlocal enableextensions

REM Publishes the latest built installer to Cloudflare R2 and updates GitHub Release with update.json
REM Requirements:
REM   - Inno setup build already completed (dist\_installer\efdrift-scrutineer-setup.exe exists)
REM   - AWS CLI installed and on PATH (for R2 upload) OR manually upload and skip to manifest + GH step
REM   - GitHub token set in EF_SCRUTINEER_GITHUB_TOKEN / GITHUB_TOKEN / GH_TOKEN
REM   - R2 env vars set: R2_ACCOUNT_ID, R2_ACCESS_KEY_ID, R2_SECRET_ACCESS_KEY, R2_BUCKET
REM   - R2_PUBLIC_BASE_URL set to public URL base (e.g., https://updates.example.com) or leave blank to use default endpoint URL

set "REPO=%~dp0.."
set "PY=%REPO%\.venv-alpha-win\Scripts\python.exe"
if not exist "%PY%" set "PY=python"

REM Resolve version and paths
for /f "usebackq delims=" %%v in (`"%PY%" -c "import app_version; print(getattr(app_version,'APP_VERSION','0.0.0'))"`) do set "APPVER=%%v"
set "INSTALLER=%REPO%\dist\_installer\efdrift-scrutineer-setup.exe"
if not exist "%INSTALLER%" set "INSTALLER=%REPO%\dist\efdrift-scrutineer-setup.exe"
set "FILE=%INSTALLER%"
if defined UPLOAD_FILE if exist "%UPLOAD_FILE%" set "FILE=%UPLOAD_FILE%"
if not exist "%FILE%" (
  echo Artifact not found. Build first or set UPLOAD_FILE to the path of the file to publish. & exit /b 1
)

REM Verify R2 variables
set "PUBLIC_URL="
set "MANIFEST_NAME="

if defined GDRIVE_UPLOAD (
  if not defined GDRIVE_CLIENT_ID echo GDRIVE_CLIENT_ID not set & exit /b 2
  if not defined GDRIVE_CLIENT_SECRET echo GDRIVE_CLIENT_SECRET not set & exit /b 2
  if not defined GDRIVE_REFRESH_TOKEN echo GDRIVE_REFRESH_TOKEN not set & exit /b 2
  set "GD_ARGS=--file \"%FILE%\" --client-id \"%GDRIVE_CLIENT_ID%\" --client-secret \"%GDRIVE_CLIENT_SECRET%\" --refresh-token \"%GDRIVE_REFRESH_TOKEN%\""
  if defined GDRIVE_FILE_NAME set "GD_ARGS=%GD_ARGS% --name \"%GDRIVE_FILE_NAME%\""
  if defined GDRIVE_FOLDER_ID set "GD_ARGS=%GD_ARGS% --folder \"%GDRIVE_FOLDER_ID%\""
  echo Uploading to Google Drive...
  for /f "usebackq tokens=1,* delims==" %%A in (`"%PY%" "%REPO%\build\gdrive_upload.py" %GD_ARGS% ^| findstr /R /C:"^[A-Z_][A-Z_]*="`) do set "%%A=%%B"
  if not defined FILE_ID echo Google Drive upload failed & exit /b 3
  set "PUBLIC_URL=https://drive.google.com/uc?export=download&id=%FILE_ID%"
  if defined NAME set "MANIFEST_NAME=%NAME%"
) else if defined GDRIVE_FILE_ID (
  set "PUBLIC_URL=https://drive.google.com/uc?export=download&id=%GDRIVE_FILE_ID%"
  if defined GDRIVE_FILE_NAME set "MANIFEST_NAME=%GDRIVE_FILE_NAME%"
) else (
  if not defined R2_ACCOUNT_ID echo R2_ACCOUNT_ID not set & exit /b 2
  if not defined R2_ACCESS_KEY_ID echo R2_ACCESS_KEY_ID not set & exit /b 2
  if not defined R2_SECRET_ACCESS_KEY echo R2_SECRET_ACCESS_KEY not set & exit /b 2
  if not defined R2_BUCKET echo R2_BUCKET not set & exit /b 2

  REM Figure out public URL base
  set "PUBLIC_BASE=%R2_PUBLIC_BASE_URL%"
  if "%PUBLIC_BASE%"=="" set "PUBLIC_BASE=https://%R2_ACCOUNT_ID%.r2.cloudflarestorage.com/%R2_BUCKET%"
  set "OBJECT_KEY=efdrift-scrutineer-setup.exe"
  if defined REMOTE_OBJECT_KEY set "OBJECT_KEY=%REMOTE_OBJECT_KEY%"
  set "PUBLIC_URL=%PUBLIC_BASE%/%OBJECT_KEY%"

  REM Upload to R2 using AWS CLI if available
  where aws >nul 2>nul
  if %ERRORLEVEL%==0 (
    echo Uploading to R2 via AWS CLI...
    set "AWS_ACCESS_KEY_ID=%R2_ACCESS_KEY_ID%"
    set "AWS_SECRET_ACCESS_KEY=%R2_SECRET_ACCESS_KEY%"
    aws --endpoint-url https://%R2_ACCOUNT_ID%.r2.cloudflarestorage.com s3 cp "%FILE%" "s3://%R2_BUCKET%/%OBJECT_KEY%" --only-show-errors
    if %ERRORLEVEL% NEQ 0 (
      echo AWS CLI upload failed. Please verify credentials and bucket policy.
      exit /b 3
    )
  ) else (
    echo AWS CLI not found on PATH. Please upload "%FILE%" to R2 at s3://%R2_BUCKET%/%OBJECT_KEY% and ensure it is publicly accessible.
    echo Skipping upload step.
  )
)

REM Build manifest JSON with size + sha256
echo Generating manifest...
set "NAME_ARG="
if defined MANIFEST_NAME set "NAME_ARG=--name %MANIFEST_NAME%"
"%PY%" "%REPO%\build\make_manifest.py" --file "%FILE%" --url "%PUBLIC_URL%" --out "%REPO%\dist\update.json" %NAME_ARG%
if %ERRORLEVEL% NEQ 0 exit /b %ERRORLEVEL%

REM Publish GitHub release and upload manifest asset
set "OWNER=" & set "REPO_NAME="
for /f "usebackq delims=" %%v in (`"%PY%" -c "import app_version; print(getattr(app_version,'GITHUB_OWNER',''))"`) do set "OWNER=%%v"
for /f "usebackq delims=" %%v in (`"%PY%" -c "import app_version; print(getattr(app_version,'GITHUB_REPO',''))"`) do set "REPO_NAME=%%v"
if "%OWNER%"=="" echo GITHUB_OWNER missing in app_version.py & exit /b 4
if "%REPO_NAME%"=="" echo GITHUB_REPO missing in app_version.py & exit /b 4

set "TAG=v%APPVER%"
set "TITLE=%APPVER%"
set "BODY=Release %APPVER% (installer hosted on Cloudflare R2)"

where gh >nul 2>nul
if %ERRORLEVEL%==0 (
  echo Using gh CLI to publish release asset...
  gh release view "%TAG%" 1>nul 2>nul || gh release create "%TAG%" "%REPO%\dist\update.json" -t "%TITLE%" -n "%BODY%"
  if %ERRORLEVEL% NEQ 0 (
    echo gh CLI failed to create or upload release asset.
    exit /b 5
  ) else (
    gh release upload "%TAG%" "%REPO%\dist\update.json" --clobber
  )
) else (
  echo Using Python to publish release asset via GitHub API...
  "%PY%" "%REPO%\build\github_release_publish.py" --owner "%OWNER%" --repo "%REPO_NAME%" --tag "%TAG%" --title "%TITLE%" --body "%BODY%" --asset "%REPO%\dist\update.json"
  if %ERRORLEVEL% NEQ 0 exit /b %ERRORLEVEL%
)

echo Publish complete. Release %TAG% now references %PUBLIC_URL%
exit /b 0
