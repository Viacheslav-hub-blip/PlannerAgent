<#
Запускает локальный LangGraph Agent Server и официальный deep-agents-ui.
Backend доступен только на loopback-интерфейсе и завершается вместе с frontend.
#>

param(
    [int]$AgentPort = 2024,
    [int]$UiPort = 3000
)

$ErrorActionPreference = "Stop"

$localUiRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$projectRoot = Split-Path -Parent $localUiRoot
$frontendRoot = Join-Path $localUiRoot ".runtime\deep-agents-ui"
$runtimeLogs = Join-Path $localUiRoot ".runtime\logs"
$langgraph = Join-Path $projectRoot ".venv\Scripts\langgraph.exe"
$configPath = Join-Path $localUiRoot "langgraph.json"
$envPath = Join-Path $localUiRoot ".env"
$backendOut = Join-Path $runtimeLogs "agent-server.out.log"
$backendErr = Join-Path $runtimeLogs "agent-server.err.log"
$frontendEnvPath = Join-Path $frontendRoot ".env.local"

if (-not (Test-Path $frontendRoot)) {
    throw "Frontend не установлен. Сначала выполните local_ui\install.ps1."
}
if (-not (Test-Path $langgraph)) {
    throw "LangGraph CLI не установлен. Сначала выполните local_ui\install.ps1."
}
if (-not (Test-Path $envPath)) {
    throw "Не найден local_ui\.env. Скопируйте local_ui\.env.example и заполните его."
}
$envLines = Get-Content $envPath
$apiKeyLine = $envLines |
    Where-Object { $_ -match "^[ \t]*OPENAI_API_KEY[ \t]*=" } |
    Select-Object -First 1
$apiKeyValue = if ($apiKeyLine) {
    ($apiKeyLine -split "=", 2)[1].Trim().Trim('"').Trim("'")
} else {
    ""
}
if ([string]::IsNullOrWhiteSpace($apiKeyValue)) {
    throw "В local_ui\.env не задан OPENAI_API_KEY."
}
$modelLine = $envLines |
    Where-Object { $_ -match "^[ \t]*DEEP_AGENT_MODEL[ \t]*=" } |
    Select-Object -First 1
$modelValue = if ($modelLine) {
    ($modelLine -split "=", 2)[1].Trim().Trim('"').Trim("'")
} else {
    ""
}
if ([string]::IsNullOrWhiteSpace($modelValue)) {
    throw "В local_ui\.env не задан DEEP_AGENT_MODEL."
}

New-Item -ItemType Directory -Path $runtimeLogs -Force | Out-Null
Remove-Item $backendOut, $backendErr -ErrorAction SilentlyContinue

$backend = Start-Process `
    -FilePath $langgraph `
    -ArgumentList @(
        "dev",
        "--config", $configPath,
        "--host", "127.0.0.1",
        "--port", $AgentPort,
        "--no-browser",
        "--no-reload",
        "--allow-blocking"
    ) `
    -WorkingDirectory $projectRoot `
    -WindowStyle Hidden `
    -RedirectStandardOutput $backendOut `
    -RedirectStandardError $backendErr `
    -PassThru

try {
    $started = $false
    $backendServerPid = $null
    for ($attempt = 0; $attempt -lt 60; $attempt++) {
        $client = [System.Net.Sockets.TcpClient]::new()
        try {
            $connect = $client.ConnectAsync("127.0.0.1", $AgentPort)
            if ($connect.Wait(500) -and $client.Connected) {
                $started = $true
                $connection = Get-NetTCPConnection `
                    -LocalPort $AgentPort `
                    -ErrorAction SilentlyContinue |
                    Select-Object -First 1
                if ($connection) {
                    $backendServerPid = [int]$connection.OwningProcess
                }
                break
            }
        }
        catch {
        }
        finally {
            $client.Dispose()
        }
        Start-Sleep -Milliseconds 500
    }

    if (-not $started) {
        throw "Agent Server не открыл порт $AgentPort за 30 секунд. Логи: $runtimeLogs"
    }

    $env:NEXT_PUBLIC_DEPLOYMENT_URL = "http://127.0.0.1:$AgentPort"
    $env:NEXT_PUBLIC_ASSISTANT_ID = "analytics-agent"
    @(
        "NEXT_PUBLIC_DEPLOYMENT_URL=$env:NEXT_PUBLIC_DEPLOYMENT_URL"
        "NEXT_PUBLIC_ASSISTANT_ID=$env:NEXT_PUBLIC_ASSISTANT_ID"
    ) | Set-Content -Path $frontendEnvPath -Encoding utf8

    Write-Host "Agent Server: $env:NEXT_PUBLIC_DEPLOYMENT_URL"
    Write-Host "Assistant ID: $env:NEXT_PUBLIC_ASSISTANT_ID"
    Write-Host "UI: http://127.0.0.1:$UiPort"
    Write-Host "Остановка обоих процессов: Ctrl+C"

    Push-Location $frontendRoot
    try {
        npx --yes yarn@1.22.22 dev --port $UiPort
    }
    finally {
        Pop-Location
    }
}
finally {
    $backendProcessIds = @(
        Get-NetTCPConnection `
            -LocalPort $AgentPort `
            -ErrorAction SilentlyContinue |
            Select-Object -ExpandProperty OwningProcess -Unique
    )
    if ($backendServerPid) {
        $backendProcessIds += $backendServerPid
    }
    $backendProcessIds |
        Where-Object { $_ } |
        Sort-Object -Unique |
        ForEach-Object {
            Stop-Process -Id $_ -Force -ErrorAction SilentlyContinue
        }
    if (-not $backend.HasExited) {
        Stop-Process -Id $backend.Id -Force -ErrorAction SilentlyContinue
    }
}
