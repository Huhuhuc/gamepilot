param(
    [string]$Commit = "1ce73ad946302e61e87060d4a9a3ef44d4af106a"
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
if ($Commit -notmatch "^[0-9a-f]{40}$") {
    throw "Commit must be a full 40-character Git hash."
}

$tempRoot = Join-Path ([System.IO.Path]::GetTempPath()) ("gamepilot-assets-" + [guid]::NewGuid().ToString("N"))
$archive = Join-Path $tempRoot "source.zip"
$extract = Join-Path $tempRoot "source"
New-Item -ItemType Directory -Path $extract -Force | Out-Null

try {
    $url = "https://github.com/Huhuhuc/2dshootgame/archive/$Commit.zip"
    Invoke-WebRequest -Uri $url -OutFile $archive
    Expand-Archive -LiteralPath $archive -DestinationPath $extract -Force
    $source = Get-ChildItem -LiteralPath $extract -Directory | Select-Object -First 1
    if (-not $source) { throw "The source archive was empty." }

    foreach ($name in @("audio", "font", "texture")) {
        $sourceDirectory = Join-Path $source.FullName ("resources\" + $name)
        $targetDirectory = Join-Path $root ("game\resources\" + $name)
        if (-not (Test-Path -LiteralPath $sourceDirectory -PathType Container)) {
            throw "Expected source asset directory is missing: resources/$name"
        }
        New-Item -ItemType Directory -Path $targetDirectory -Force | Out-Null
        Copy-Item -Path (Join-Path $sourceDirectory "*") -Destination $targetDirectory -Recurse -Force
    }

    $sourceGrid = Join-Path $source.FullName "output_pickup_grid.png"
    if (Test-Path -LiteralPath $sourceGrid -PathType Leaf) {
        Copy-Item -LiteralPath $sourceGrid -Destination (Join-Path $root "game\output_pickup_grid.png") -Force
    }
    Write-Host "Game assets restored locally from Huhuhuc/2dshootgame@$Commit. They remain excluded from Git."
}
finally {
    $resolvedTemp = [System.IO.Path]::GetFullPath($tempRoot)
    $expectedPrefix = [System.IO.Path]::GetFullPath([System.IO.Path]::GetTempPath())
    if ($resolvedTemp.StartsWith($expectedPrefix, [System.StringComparison]::OrdinalIgnoreCase) -and
        (Split-Path -Leaf $resolvedTemp).StartsWith("gamepilot-assets-")) {
        Remove-Item -LiteralPath $resolvedTemp -Recurse -Force -ErrorAction SilentlyContinue
    }
}
