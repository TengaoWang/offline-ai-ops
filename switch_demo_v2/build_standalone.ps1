param(
    [string]$Python = ''
)

$ErrorActionPreference = 'Stop'
$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$outputRoot = Join-Path $projectRoot 'dist\standalone'
$workRoot = Join-Path $projectRoot 'dist\pyinstaller-work'
$specRoot = Join-Path $projectRoot 'dist\pyinstaller-spec'

if (-not $Python) {
    $launcher = Get-Command py -ErrorAction SilentlyContinue
    if ($launcher) { $Python = $launcher.Source }
}
if (-not $Python -or (-not (Test-Path -LiteralPath $Python -PathType Leaf))) {
    throw 'Python with PyInstaller was not found. Install it with: py -m pip install pyinstaller'
}

& $Python -m PyInstaller `
    --noconfirm `
    --clean `
    --onedir `
    --console `
    --contents-directory . `
    --name switch-lab `
    --distpath $outputRoot `
    --workpath $workRoot `
    --specpath $specRoot `
    --add-data "$PSScriptRoot\index.html;." `
    --add-data "$PSScriptRoot\app.js;." `
    --add-data "$PSScriptRoot\style.css;." `
    --add-data "$PSScriptRoot\legacy.css;." `
    --add-data "$PSScriptRoot\assets;assets" `
    (Join-Path $PSScriptRoot 'server.py')

if ($LASTEXITCODE -ne 0) {
    throw "PyInstaller failed with exit code $LASTEXITCODE"
}

$target = Join-Path $outputRoot 'switch-lab'
Copy-Item -LiteralPath (Join-Path $PSScriptRoot 'README.md') -Destination $target -Force
Copy-Item -LiteralPath (Join-Path $PSScriptRoot 'ASSISTANT_API.md') -Destination $target -Force
Copy-Item -LiteralPath (Join-Path $PSScriptRoot '启动独立版.bat') -Destination $target -Force
Write-Host "Standalone package: $target"
