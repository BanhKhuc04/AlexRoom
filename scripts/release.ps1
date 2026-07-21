param(
  [string]$Version = "0.2.0-hardware-rc"
)

$ErrorActionPreference = "Stop"
$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$releaseRoot = Join-Path $repoRoot "dist-release"
$stageRoot = Join-Path $releaseRoot "AlexRoom-$Version"
$archivePath = Join-Path $releaseRoot "AlexRoom-$Version.zip"

if (-not $stageRoot.StartsWith($releaseRoot, [System.StringComparison]::OrdinalIgnoreCase)) {
  throw "Release staging path escaped dist-release"
}

New-Item -ItemType Directory -Force -Path $releaseRoot | Out-Null
if (Test-Path -LiteralPath $stageRoot) {
  Remove-Item -LiteralPath $stageRoot -Recurse -Force
}
New-Item -ItemType Directory -Force -Path $stageRoot | Out-Null

$directories = @("static", "docs", "deploy", "scripts", "tests", "firmware")
foreach ($directory in $directories) {
  Copy-Item -LiteralPath (Join-Path $repoRoot $directory) -Destination $stageRoot -Recurse
}

$files = @(
  "app.py", "alex_store.py", "alex_hardware.py", "alex_simulator.py",
  "alex_orchestration.py", "alex_brain.py", "package.json", "package-lock.json",
  "requirements.txt", "tsconfig.json", "eslint.config.js", ".env.example",
  "AGENTS.md", "config.example.json"
)
foreach ($file in $files) {
  $source = Join-Path $repoRoot $file
  if (Test-Path -LiteralPath $source) {
    Copy-Item -LiteralPath $source -Destination $stageRoot
  }
}

Get-ChildItem -LiteralPath $stageRoot -Recurse -File |
  Where-Object { $_.Name -match 'secrets\.yaml|\.db(-wal|-shm)?$|\.env$' } |
  ForEach-Object { Remove-Item -LiteralPath $_.FullName -Force }

if (Test-Path -LiteralPath $archivePath) {
  Remove-Item -LiteralPath $archivePath -Force
}
Compress-Archive -LiteralPath $stageRoot -DestinationPath $archivePath -CompressionLevel Optimal
Write-Output "Release ready: $archivePath"
