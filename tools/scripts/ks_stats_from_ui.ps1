Param(
  [Parameter(Mandatory=$true)][string]$Car,
  [Parameter(Mandatory=$true)][string]$Out
)
# Estimate KN5 stats from UI cm_lods_generation.json (trianglesCount per stage)
# Writes JSON: { "total_triangles": <number>, "total_objects": null, "source": "ui_lods" }

try {
  $lodsPath = Join-Path $Car 'ui\cm_lods_generation.json'
  $triTotal = 0
  if (Test-Path $lodsPath) {
    $raw = Get-Content $lodsPath -Raw -ErrorAction Stop | ConvertFrom-Json
    if ($raw -and $raw.Stages) {
      foreach ($k in $raw.Stages.PSObject.Properties.Name) {
        $entry = $raw.Stages.$k
        if ($entry -is [string]) {
          try { $entry = $entry | ConvertFrom-Json } catch {}
        }
        if ($entry -and $entry.trianglesCount) {
          $triTotal += [int]$entry.trianglesCount
        }
      }
    }
  }
  New-Item -ItemType Directory -Force -Path (Split-Path $Out) | Out-Null
  $payload = @{ total_triangles = $triTotal; total_objects = $null; source = 'ui_lods' }
  $json = $payload | ConvertTo-Json
  Set-Content -Path $Out -Value $json -Encoding UTF8
  Write-Host "Wrote $Out"
  exit 0
} catch {
  $err = $_.Exception.Message
  $obj = @{ total_triangles = $null; total_objects = $null; error = $err }
  $json = $obj | ConvertTo-Json
  New-Item -ItemType Directory -Force -Path (Split-Path $Out) | Out-Null
  Set-Content -Path $Out -Value $json -Encoding UTF8
  Write-Host "Failed: $err"
  exit 1
}

