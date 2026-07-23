param(
  [string]$Version,
  [string]$SourceRoot
)

$ErrorActionPreference = "Stop"

$defaultRepoRoot = Join-Path $PSScriptRoot ".."

if ([string]::IsNullOrWhiteSpace($SourceRoot)) {
  $SourceRoot = $defaultRepoRoot
}

if (-not (Test-Path -LiteralPath $SourceRoot -PathType Container)) {
  throw "Release source root does not exist: $SourceRoot"
}

$repoRoot = (Resolve-Path -LiteralPath $SourceRoot).Path
$versionFile = Join-Path $repoRoot "VERSION"

if (-not (Test-Path -LiteralPath $versionFile)) {
  throw "Canonical VERSION file is missing"
}

$canonicalVersion = (Get-Content -LiteralPath $versionFile -Raw).Trim()

$semverPattern = "^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)(?:-[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*)?(?:\+[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*)?$"

if ($canonicalVersion -notmatch $semverPattern) {
  throw "Invalid canonical version: $canonicalVersion"
}

if ([string]::IsNullOrWhiteSpace($Version)) {
  $Version = $canonicalVersion
}

if ($Version -ne $canonicalVersion) {
  throw "Requested version $Version does not match canonical version $canonicalVersion"
}

$releaseRoot = Join-Path $repoRoot "dist-release"
$stageRoot = Join-Path $releaseRoot "AlexRoom-$Version"
$archivePath = Join-Path $releaseRoot "AlexRoom-$Version.zip"

$fullReleaseRoot = [System.IO.Path]::GetFullPath($releaseRoot)
$fullStageRoot = [System.IO.Path]::GetFullPath($stageRoot)

if (-not $fullStageRoot.StartsWith(
    $fullReleaseRoot + [System.IO.Path]::DirectorySeparatorChar,
    [System.StringComparison]::OrdinalIgnoreCase
  )) {
  throw "Release staging path escaped dist-release"
}

New-Item -ItemType Directory -Force -Path $releaseRoot | Out-Null

if (Test-Path -LiteralPath $stageRoot) {
  Remove-Item -LiteralPath $stageRoot -Recurse -Force
}

New-Item -ItemType Directory -Force -Path $stageRoot | Out-Null

$directories = @(
  "static",
  "docs",
  "deploy",
  "scripts",
  "tests",
  "firmware",
  "brain_service"
)

foreach ($directory in $directories) {
  $source = Join-Path $repoRoot $directory

  if (Test-Path -LiteralPath $source) {
    Copy-Item `
      -LiteralPath $source `
      -Destination $stageRoot `
      -Recurse
  }
}

$pythonFiles = Get-ChildItem `
  -LiteralPath $repoRoot `
  -File `
  -Filter "*.py" |
  Select-Object -ExpandProperty Name

$files = @(
  "VERSION",
  "package.json",
  "package-lock.json",
  "requirements.txt",
  "requirements-orangepi.txt",
  "tsconfig.json",
  "eslint.config.js",
  ".env.example",
  "AGENTS.md",
  "config.example.json",
  "CHANGELOG.md"
) + $pythonFiles

foreach ($file in ($files | Sort-Object -Unique)) {
  $source = Join-Path $repoRoot $file

  if (Test-Path -LiteralPath $source) {
    Copy-Item -LiteralPath $source -Destination $stageRoot
  }
}

Get-ChildItem -LiteralPath $stageRoot -Recurse -Directory |
  Where-Object {
    $_.Name -in @("__pycache__", ".pio-venv", ".pio")
  } |
  Sort-Object FullName -Descending |
  Remove-Item -Recurse -Force

Get-ChildItem -LiteralPath $stageRoot -Recurse -File |
  Where-Object {
    $_.Name -match 'secrets\.yaml|\.db(-wal|-shm)?$|\.env$|\.pyc$'
  } |
  Remove-Item -Force

if (Test-Path -LiteralPath $archivePath) {
  Remove-Item -LiteralPath $archivePath -Force
}

Compress-Archive `
  -LiteralPath $stageRoot `
  -DestinationPath $archivePath `
  -CompressionLevel Optimal

Write-Output "Release version: $Version"
Write-Output "Release ready: $archivePath"
