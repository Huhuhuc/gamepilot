param(
    [ValidateSet('Play','Rule','PPO','Verify')][string]$Mode = 'Rule',
    [string]$Godot = '',
    [string]$Model = 'runs/original-seed0-100k/best.zip'
)
$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
if ($Godot) { $env:GODOT_BIN = $Godot }
if (-not $env:GODOT_BIN) {
    $taskGodotCandidates = @(
        'D:\godot v4.6.1\Godot_v4.6.1-stable_win64.exe',
        (Get-Command godot -ErrorAction SilentlyContinue | Select-Object -ExpandProperty Source)
    )
    $env:GODOT_BIN = $taskGodotCandidates | Where-Object { $_ -and (Test-Path -LiteralPath $_) } | Select-Object -First 1
}
if (-not $env:GODOT_BIN) { throw 'Set GODOT_BIN or pass -Godot with your Godot 4.6.1 executable path.' }
if (-not (Test-Path -LiteralPath '.venv\Scripts\python.exe')) {
    if (Get-Command uv -ErrorAction SilentlyContinue) {
        uv venv .venv --python 3.12
        if ($LASTEXITCODE -ne 0) { throw 'Virtual environment creation failed' }
        uv pip install --python .venv/Scripts/python.exe -r requirements.lock.txt
    } else {
        py -3.12 -m venv .venv
        if ($LASTEXITCODE -ne 0) { throw 'Install Python 3.12 or uv first' }
        & '.venv\Scripts\python.exe' -m pip install -r requirements.lock.txt
    }
    if ($LASTEXITCODE -ne 0) { throw 'Dependency installation failed' }
}
$env:PYTHONUTF8 = '1'
& $env:GODOT_BIN --headless --path game --editor --import --quit
if ($LASTEXITCODE -ne 0) { throw 'Godot import failed' }
switch ($Mode) {
    'Play' { & $env:GODOT_BIN --path game }
    'Verify' {
        & '.venv\Scripts\python.exe' -m pytest -q
        if ($LASTEXITCODE -ne 0) { throw 'Tests failed' }
        & '.venv\Scripts\python.exe' -m gamepilot.smoke
    }
    default {
        $taskOutput = 'runs/demo-' + (Get-Date -Format 'yyyyMMdd-HHmmss') + '-' + [guid]::NewGuid().ToString('N').Substring(0,6)
        $taskArguments = @('-u','-m','gamepilot.experiment','evaluate','--episodes','1','--start-seed','2000','--visible','--output',$taskOutput)
        if ($Mode -eq 'PPO') {
            if (-not (Test-Path -LiteralPath $Model)) { throw 'Model missing. Train a model first or pass -Model.' }
            $taskArguments += @('--policy','ppo','--model',$Model)
        } else { $taskArguments += @('--policy','rule') }
        & '.venv\Scripts\python.exe' @taskArguments
    }
}
if ($LASTEXITCODE -ne 0) { throw 'GamePilot command failed' }
