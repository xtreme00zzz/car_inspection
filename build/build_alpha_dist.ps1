param(
    [string]$AlphaVersion = "ALPHA-0.1.0"
)

$ErrorActionPreference = "Stop"

function Invoke-PyInstaller {
    param(
        [string[]]$Arguments
    )

    Write-Host "python -m PyInstaller $($Arguments -join ' ')" -ForegroundColor DarkGray
    & python -m PyInstaller @Arguments
}

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$distDir = Join-Path $repoRoot "dist"
$specPath = Join-Path $repoRoot "build"
$uiScript = Join-Path $repoRoot "ui_app.py"
$workDirOnedir = Join-Path $repoRoot "build\pyinstaller-build"
$workDirOnefile = Join-Path $repoRoot "build\pyinstaller-build-onefile"
$appName = "eF Drift Car Scrutineer Alpha"
$onedirOutput = Join-Path $distDir $appName
$onefileOutput = Join-Path $distDir ("$appName.exe")
$payloadRoot = Join-Path $distDir "alpha_payload"
$trimmedReferenceRoot = Join-Path $repoRoot "build\reference_cars_alpha"

Write-Host "[1/6] Cleaning previous build artifacts..." -ForegroundColor Cyan
Remove-Item -Recurse -Force $workDirOnedir -ErrorAction Ignore
Remove-Item -Recurse -Force $workDirOnefile -ErrorAction Ignore
Remove-Item -Recurse -Force $onedirOutput -ErrorAction Ignore
Remove-Item -Force $onefileOutput -ErrorAction Ignore
Remove-Item -Recurse -Force $payloadRoot -ErrorAction Ignore
Remove-Item -Recurse -Force $trimmedReferenceRoot -ErrorAction Ignore

New-Item -ItemType Directory -Path $distDir -ErrorAction Ignore | Out-Null

Write-Host "[2/6] Preparing trimmed reference assets..." -ForegroundColor Cyan
& python (Join-Path $repoRoot "build\prepare_alpha_reference.py") "--src" "$(Join-Path $repoRoot 'reference_cars')" "--dest" "$trimmedReferenceRoot"

try {
    Set-Item -Path Env:ALPHA_REFERENCE_ROOT -Value $trimmedReferenceRoot

    Write-Host "[3/6] Building onedir distribution via spec..." -ForegroundColor Cyan
    Invoke-PyInstaller -Arguments @(
        "--noconfirm",
        "--clean",
        "--log-level=WARN",
        "--distpath", $distDir,
        "--workpath", $workDirOnedir,
        (Join-Path $specPath "car_inspection_alpha.spec")
    )

    Write-Host "[4/6] Building onefile bootstrap executable..." -ForegroundColor Cyan
    $dataMappings = @(
        $trimmedReferenceRoot + ";reference_cars",
        (Join-Path $repoRoot "icon.ico") + ";.",
        (Join-Path $repoRoot "README.md") + ";.",
        (Join-Path $repoRoot "PACKAGING_ALPHA.md") + ";docs",
        (Join-Path $repoRoot "build\alpha_release_notes.txt") + ";docs"
    )
    $addDataArgs = @()
    foreach ($mapping in $dataMappings) {
        if (Test-Path ($mapping.Split(";")[0])) {
            $addDataArgs += "--add-data"
            $addDataArgs += $mapping
        }
    }
    Invoke-PyInstaller -Arguments (@(
            "--noconfirm",
            "--clean",
            "--log-level=WARN",
            "--onefile",
            "--windowed",
            "--icon", (Join-Path $repoRoot "icon.ico"),
            "--name", $appName,
            "--distpath", $distDir,
            "--workpath", $workDirOnefile,
            "--specpath", $specPath
        ) + $addDataArgs + @($uiScript))
}
finally {
    Remove-Item Env:ALPHA_REFERENCE_ROOT -ErrorAction Ignore
}

if (!(Test-Path $onedirOutput)) {
    throw "Onedir build missing at $onedirOutput"
}
if (!(Test-Path $onefileOutput)) {
    throw "Onefile build missing at $onefileOutput"
}

Write-Host "[5/6] Preparing installer payload..." -ForegroundColor Cyan
New-Item -ItemType Directory -Path $payloadRoot | Out-Null
Copy-Item -Recurse -Force -Path $onedirOutput -Destination (Join-Path $payloadRoot "app")
Copy-Item -Force -Path $onefileOutput -Destination (Join-Path $payloadRoot ("$appName.exe"))
New-Item -ItemType Directory -Path (Join-Path $payloadRoot "docs") -ErrorAction Ignore | Out-Null
Copy-Item -Force -Path (Join-Path $repoRoot "build\alpha_release_notes.txt") -Destination (Join-Path $payloadRoot "docs\alpha_release_notes.txt")
Copy-Item -Force -Path (Join-Path $repoRoot "README.md") -Destination (Join-Path $payloadRoot "docs\README.md")

$versionStampPath = Join-Path $payloadRoot "VERSION.txt"
"eF Drift Car Scrutineer $AlphaVersion" | Out-File -FilePath $versionStampPath -Encoding utf8 -Force

Write-Host "[6/6] Build complete."
Write-Host "  Onedir dist : $onedirOutput"
Write-Host "  Onefile exe : $onefileOutput"
Write-Host "  Payload root : $payloadRoot"
Write-Host ""
Write-Host "Next steps:"
Write-Host "  iscc.exe build\installer_alpha.iss" -ForegroundColor Yellow

# Build updater stub (Windows)
try {
    Write-Host "[Extra] Building updater stub..." -ForegroundColor Cyan
    & python -m PyInstaller --noconfirm --clean --log-level=WARN --onefile --console `
        --name "eF Drift Car Scrutineer Updater" `
        --distpath $distDir --workpath (Join-Path $repoRoot "build\pyinstaller-build-updater-alpha") --specpath $specPath `
        (Join-Path $repoRoot "tools\windows_updater_stub.py")
    # Put updater next to onedir app and into payload
    Copy-Item -Force -Path (Join-Path $distDir "eF Drift Car Scrutineer Updater.exe") -Destination (Join-Path $onedirOutput "eF Drift Car Scrutineer Updater.exe") -ErrorAction Ignore
    Copy-Item -Force -Path (Join-Path $distDir "eF Drift Car Scrutineer Updater.exe") -Destination (Join-Path $payloadRoot "eF Drift Car Scrutineer Updater.exe") -ErrorAction Ignore
} catch {
    Write-Warning "Updater stub build failed: $_"
}
