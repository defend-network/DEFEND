param([switch]$Repair)

$ErrorActionPreference = "Stop"
$repo = Split-Path -Parent $MyInvocation.MyCommand.Path
$venvPython = Join-Path $repo ".venv\Scripts\python.exe"

if (-not (Test-Path -LiteralPath $venvPython)) {
    py -3.14 -m venv (Join-Path $repo ".venv")
    if ($LASTEXITCODE -ne 0) { throw "Python virtual environment creation failed" }
}

& $venvPython -m pip install --requirement (Join-Path $repo "requirements-dev.txt")
if ($LASTEXITCODE -ne 0) { throw "Python dependency installation failed" }

& npm.cmd ci --prefix (Join-Path $repo "defend-ui-v2")
if ($LASTEXITCODE -ne 0) { throw "Frontend dependency installation failed" }

& npm.cmd run build --prefix (Join-Path $repo "defend-ui-v2")
if ($LASTEXITCODE -ne 0) { throw "Frontend production build failed" }

$desktop = [Environment]::GetFolderPath("Desktop")
$shell = New-Object -ComObject WScript.Shell
$shortcut = $shell.CreateShortcut((Join-Path $desktop "Start DEFEND.lnk"))
$shortcut.TargetPath = Join-Path $repo "Start-DEFEND.cmd"
$shortcut.WorkingDirectory = $repo
$shortcut.Save()
