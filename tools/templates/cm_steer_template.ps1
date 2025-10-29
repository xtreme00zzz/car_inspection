Param(
  [Parameter(Mandatory=$true)][string]$Car,
  [Parameter(Mandatory=$true)][string]$Out
)
# Example PowerShell template to integrate with Content Manager or a custom tool.
# Replace the following command with your tool that measures max wheel angle at 0 toe
# and outputs a JSON with key "max_wheel_angle_deg".

# Example: & "C:\\Tools\\CMTool.exe" --measure-steer --car "$Car" --out "$Out"

# For now, write a placeholder structure if no tool is wired:
$result = @{ max_wheel_angle_deg = 70.0; source = 'template' }
$json = $result | ConvertTo-Json
New-Item -ItemType Directory -Force -Path (Split-Path $Out) | Out-Null
Set-Content -Path $Out -Value $json -Encoding UTF8
Write-Host "Wrote $Out"

