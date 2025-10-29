Param(
  [Parameter(Mandatory=$true)][string]$Car,
  [Parameter(Mandatory=$true)][string]$Out
)
# Example PowerShell template to integrate with KS Editor or a custom model stats tool.
# Replace the following command with your tool that outputs a JSON with
# keys: total_triangles, total_objects.

# Example: & "C:\\Tools\\KSStats.exe" --car "$Car" --out "$Out"

# Placeholder output until wired:
$result = @{ total_triangles = 480000; total_objects = 260; source = 'template' }
$json = $result | ConvertTo-Json
New-Item -ItemType Directory -Force -Path (Split-Path $Out) | Out-Null
Set-Content -Path $Out -Value $json -Encoding UTF8
Write-Host "Wrote $Out"

