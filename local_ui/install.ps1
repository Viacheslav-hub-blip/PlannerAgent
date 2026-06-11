<#
Устаревший wrapper. Предпочтительный запуск: python run_ui.py --install-only
#>

$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$python = Join-Path $projectRoot ".venv\Scripts\python.exe"
if (-not (Test-Path $python)) {
    $python = "python"
}
& $python (Join-Path $projectRoot "run_ui.py") --install-only
if ($LASTEXITCODE -ne 0) {
    exit $LASTEXITCODE
}
