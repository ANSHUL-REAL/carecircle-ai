$ErrorActionPreference = "Stop"

$root = Split-Path -Parent $PSScriptRoot
$build = Join-Path $root ".build"
$zip = Join-Path $root "carecircle-automation.zip"

if (Test-Path $build) {
  Remove-Item -LiteralPath $build -Recurse -Force
}
if (Test-Path $zip) {
  Remove-Item -LiteralPath $zip -Force
}

New-Item -ItemType Directory -Path $build | Out-Null
python -m pip install `
  --platform manylinux2014_x86_64 `
  --implementation cp `
  --python-version 3.12 `
  --only-binary=:all: `
  -r (Join-Path $root "requirements.txt") `
  -t $build
Copy-Item -Path (Join-Path $root "app") -Destination (Join-Path $build "app") -Recurse

Compress-Archive -Path (Join-Path $build "*") -DestinationPath $zip -Force
Write-Output "Built $zip"
