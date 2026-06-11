<#
Устаревший wrapper. Предпочтительный запуск: python run_ui.py
#>

param(
    [int]$AgentPort = 2024,
    [int]$UiPort = 3000
)

$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$python = Join-Path $projectRoot ".venv\Scripts\python.exe"
if (-not (Test-Path $python)) {
    $python = "python"
}
& $python (Join-Path $projectRoot "run_ui.py") --agent-port $AgentPort --ui-port $UiPort
exit $LASTEXITCODE
