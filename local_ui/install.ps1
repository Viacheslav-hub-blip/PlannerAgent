<#
Устанавливает Python-зависимости локального Agent Server, клонирует закреплённую
версию deep-agents-ui, применяет небольшой patch автоподключения и ставит Node.js-пакеты.
#>

$ErrorActionPreference = "Stop"

$uiCommit = "f6a4f34565b42688be06498031fc9351c152614e"
$localUiRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$projectRoot = Split-Path -Parent $localUiRoot
$python = Join-Path $projectRoot ".venv\Scripts\python.exe"
$runtimeRoot = Join-Path $localUiRoot ".runtime"
$frontendRoot = Join-Path $runtimeRoot "deep-agents-ui"
$patchPath = Join-Path $localUiRoot "deep-agents-ui.local.patch"
$envPath = Join-Path $localUiRoot ".env"
$envExamplePath = Join-Path $localUiRoot ".env.example"

if (-not (Test-Path $python)) {
    throw "Не найдено виртуальное окружение: $python"
}

& $python -m pip install -e "$projectRoot[models,data,analytics,ui]"
if ($LASTEXITCODE -ne 0) {
    throw "Не удалось установить Python-зависимости."
}

New-Item -ItemType Directory -Path $runtimeRoot -Force | Out-Null
if (-not (Test-Path $frontendRoot)) {
    git clone https://github.com/langchain-ai/deep-agents-ui.git $frontendRoot
    if ($LASTEXITCODE -ne 0) {
        throw "Не удалось клонировать deep-agents-ui."
    }
    git -C $frontendRoot checkout --detach $uiCommit
    if ($LASTEXITCODE -ne 0) {
        throw "Не удалось переключить deep-agents-ui на commit $uiCommit."
    }
}

git -C $frontendRoot apply --check $patchPath 2>$null
if ($LASTEXITCODE -eq 0) {
    git -C $frontendRoot apply $patchPath
} else {
    git -C $frontendRoot apply --reverse --check $patchPath 2>$null
    if ($LASTEXITCODE -ne 0) {
        throw "Локальный patch несовместим с текущим состоянием deep-agents-ui."
    }
}

Push-Location $frontendRoot
try {
    npx --yes yarn@1.22.22 install --frozen-lockfile
    if ($LASTEXITCODE -ne 0) {
        throw "Не удалось установить зависимости deep-agents-ui."
    }
}
finally {
    Pop-Location
}

if (-not (Test-Path $envPath)) {
    Copy-Item $envExamplePath $envPath
}

Write-Host "Установка завершена."
Write-Host "Заполните $envPath и запустите: powershell -ExecutionPolicy Bypass -File local_ui\start.ps1"
