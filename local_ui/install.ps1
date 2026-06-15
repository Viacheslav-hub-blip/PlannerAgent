<#
Устанавливает подготовленный Linux frontend Deep Agents UI из локального архива.

Скрипт не использует сеть. Полный архив может находиться в корне проекта либо быть
разбит на части с суффиксами .part001, .part002 и далее.
#>

param(
    [string]$ArchivePath,
    [string]$DestinationPath,
    [switch]$Force
)

$ErrorActionPreference = "Stop"

$projectRoot = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$archiveName = "deep-agents-ui-node20-linux-x86_64.tar.gz"
$defaultArchivePath = Join-Path $projectRoot $archiveName
$checksumPath = Join-Path $projectRoot "SHA256SUMS"
$runtimeRoot = Join-Path $projectRoot "local_ui\.runtime"
$defaultDestinationPath = Join-Path $runtimeRoot "deep-agents-ui"

if (-not $ArchivePath) {
    $ArchivePath = $defaultArchivePath
}
if (-not $DestinationPath) {
    $DestinationPath = $defaultDestinationPath
}

$ArchivePath = [System.IO.Path]::GetFullPath($ArchivePath)
$DestinationPath = [System.IO.Path]::GetFullPath($DestinationPath)
$runtimeRoot = [System.IO.Path]::GetFullPath($runtimeRoot)

if (-not $DestinationPath.StartsWith($runtimeRoot, [System.StringComparison]::OrdinalIgnoreCase)) {
    throw "DestinationPath must be inside $runtimeRoot"
}

function Get-ExpectedArchiveHash {
    <#
    Возвращает ожидаемый SHA256 архива из SHA256SUMS.

    Returns:
        Строка SHA256 в верхнем регистре.
    #>

    if (-not (Test-Path -LiteralPath $checksumPath -PathType Leaf)) {
        throw "Checksum file not found: $checksumPath"
    }

    $line = Get-Content -LiteralPath $checksumPath |
        Where-Object { $_ -match "^\s*([A-Fa-f0-9]{64})\s+\*?$([regex]::Escape($archiveName))\s*$" } |
        Select-Object -First 1

    if (-not $line) {
        throw "SHA256 for $archiveName was not found in $checksumPath"
    }

    return ([regex]::Match($line, "([A-Fa-f0-9]{64})").Groups[1].Value).ToUpperInvariant()
}

function Join-ArchiveParts {
    <#
    Собирает полный архив из последовательных частей.

    Args:
        TargetPath: Путь создаваемого полного архива.

    Returns:
        None.
    #>

    param([string]$TargetPath)

    $parts = Get-ChildItem -LiteralPath (Split-Path -Parent $TargetPath) |
        Where-Object { $_.Name -match "^$([regex]::Escape($archiveName))\.part\d{3}$" } |
        Sort-Object Name

    if (-not $parts) {
        throw "Archive $TargetPath and parts .part001, .part002, ... were not found"
    }

    $expectedPart = 1
    foreach ($part in $parts) {
        $expectedName = "$archiveName.part$($expectedPart.ToString('000'))"
        if ($part.Name -ne $expectedName) {
            throw "Invalid part sequence: expected $expectedName, found $($part.Name)"
        }
        $expectedPart += 1
    }

    $output = [System.IO.File]::Open(
        $TargetPath,
        [System.IO.FileMode]::Create,
        [System.IO.FileAccess]::Write,
        [System.IO.FileShare]::None
    )
    try {
        foreach ($part in $parts) {
            $input = [System.IO.File]::OpenRead($part.FullName)
            try {
                $input.CopyTo($output)
            }
            finally {
                $input.Dispose()
            }
        }
    }
    finally {
        $output.Dispose()
    }
}

if (-not (Test-Path -LiteralPath $ArchivePath -PathType Leaf)) {
    Write-Host "Full archive not found. Joining archive parts..."
    Join-ArchiveParts -TargetPath $ArchivePath
}

$expectedHash = Get-ExpectedArchiveHash
$actualHash = (Get-FileHash -LiteralPath $ArchivePath -Algorithm SHA256).Hash.ToUpperInvariant()
if ($actualHash -ne $expectedHash) {
    throw "Archive SHA256 mismatch. Expected $expectedHash, received $actualHash"
}

if ((Test-Path -LiteralPath $DestinationPath) -and -not $Force) {
    throw "Frontend is already installed: $DestinationPath. Use -Force to replace it."
}

New-Item -ItemType Directory -Path $runtimeRoot -Force | Out-Null
$stagingPath = Join-Path $runtimeRoot "deep-agents-ui.installing"
$backupPath = Join-Path $runtimeRoot "deep-agents-ui.backup"

foreach ($path in @($stagingPath, $backupPath)) {
    if (Test-Path -LiteralPath $path) {
        Remove-Item -LiteralPath $path -Recurse -Force
    }
}

New-Item -ItemType Directory -Path $stagingPath | Out-Null
try {
    & tar -xzf $ArchivePath -C $stagingPath
    if ($LASTEXITCODE -ne 0) {
        throw "tar exited with code $LASTEXITCODE"
    }

    foreach ($requiredPath in @(
        (Join-Path $stagingPath "package.json"),
        (Join-Path $stagingPath "node_modules"),
        (Join-Path $stagingPath "node_modules\@langchain\langgraph-sdk\package.json")
    )) {
        if (-not (Test-Path -LiteralPath $requiredPath)) {
            throw "Required archive path is missing: $requiredPath"
        }
    }

    if (Test-Path -LiteralPath $DestinationPath) {
        Move-Item -LiteralPath $DestinationPath -Destination $backupPath
    }
    Move-Item -LiteralPath $stagingPath -Destination $DestinationPath
    if (Test-Path -LiteralPath $backupPath) {
        Remove-Item -LiteralPath $backupPath -Recurse -Force
    }
}
catch {
    if ((Test-Path -LiteralPath $backupPath) -and -not (Test-Path -LiteralPath $DestinationPath)) {
        Move-Item -LiteralPath $backupPath -Destination $DestinationPath
    }
    throw
}
finally {
    if (Test-Path -LiteralPath $stagingPath) {
        Remove-Item -LiteralPath $stagingPath -Recurse -Force
    }
}

Write-Host "Deep Agents UI installed: $DestinationPath"
Write-Host "SHA256: $actualHash"
