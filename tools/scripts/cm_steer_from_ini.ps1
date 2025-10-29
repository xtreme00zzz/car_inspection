Param(
  [Parameter(Mandatory=$true)][string]$Car,
  [Parameter(Mandatory=$true)][string]$Out
)
  # Derive front wheel max angle (approx) from car.ini: STEER_LOCK / STEER_RATIO
# Writes JSON: { "max_wheel_angle_deg": <number>, "source": "ini_derived" }

try {
  $carIniPath = Join-Path $Car 'data\car.ini'
  if (!(Test-Path $carIniPath)) {
    throw "car.ini not found: $carIniPath"
  }
  $ini = Get-Content $carIniPath -Raw -ErrorAction Stop
  $mLock = [regex]::Match($ini,'(?mi)^\s*STEER_LOCK\s*=\s*([0-9.,+-]+)')
  $mRatio = [regex]::Match($ini,'(?mi)^\s*STEER_RATIO\s*=\s*([0-9.,+-]+)')
  $lock = 0.0
  $ratio = 0.0
  if ($mLock.Success) { $lock = [double]::Parse($mLock.Groups[1].Value.Replace(',', '.'), [System.Globalization.CultureInfo]::InvariantCulture) }
  if ($mRatio.Success) { $ratio = [double]::Parse($mRatio.Groups[1].Value.Replace(',', '.'), [System.Globalization.CultureInfo]::InvariantCulture) }
  $derived = 0.0
  if ($ratio -ne 0) { $derived = [Math]::Round($lock / $ratio, 2) }
  New-Item -ItemType Directory -Force -Path (Split-Path $Out) | Out-Null
  $obj = @{ max_wheel_angle_deg = $derived; source = 'ini_derived'; note = 'STEER_LOCK/STEER_RATIO'; steer_lock = $lock; steer_ratio = $ratio }
  $json = $obj | ConvertTo-Json
  Set-Content -Path $Out -Value $json -Encoding UTF8
  Write-Host "Wrote $Out"
  exit 0
} catch {
  $err = $_.Exception.Message
  $obj = @{ max_wheel_angle_deg = $null; error = $err }
  $json = $obj | ConvertTo-Json
  New-Item -ItemType Directory -Force -Path (Split-Path $Out) | Out-Null
  Set-Content -Path $Out -Value $json -Encoding UTF8
  Write-Host "Failed: $err"
  exit 1
}
