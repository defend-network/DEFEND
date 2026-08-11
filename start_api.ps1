$repo = Split-Path -Parent $MyInvocation.MyCommand.Path
& (Join-Path $repo "Start-DEFEND.cmd") @args
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
