[CmdletBinding(SupportsShouldProcess)]
param(
    [switch]$StopBackend
)

$ErrorActionPreference = "Stop"
$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path.TrimEnd(
    [IO.Path]::DirectorySeparatorChar
)
$rootPrefix = $repoRoot + [IO.Path]::DirectorySeparatorChar

function Assert-SafeCleanupPath {
    param([string]$Path)

    $resolved = [IO.Path]::GetFullPath($Path)
    if ($resolved -eq $repoRoot -or
        -not $resolved.StartsWith($rootPrefix, [StringComparison]::OrdinalIgnoreCase)) {
        throw "Refusing unsafe cleanup target: $resolved"
    }
    return $resolved
}

if ($StopBackend) {
    $connection = Get-NetTCPConnection -LocalPort 8765 -State Listen -ErrorAction SilentlyContinue |
        Select-Object -First 1
    if ($connection) {
        $server = Get-CimInstance Win32_Process -Filter "ProcessId=$($connection.OwningProcess)"
        if ($server.CommandLine -notmatch "aura\.workspace\.server") {
            throw "Port 8765 is not owned by an AURA backend; refusing to stop it."
        }
        if ($PSCmdlet.ShouldProcess("AURA backend PID $($server.ProcessId)", "Stop")) {
            Stop-Process -Id $server.ProcessId
        }
    }
}

$relativeTargets = @(
    ".pytest_cache",
    "test-results",
    "workspace",
    "src/aura/workspace/web/frontend/out",
    "src/aura/workspace/web/frontend/out-stale-goal11",
    "src/aura/workspace/web/frontend/test-results",
    "src/aura/workspace/web/frontend/workspace",
    "src/aura_agent.egg-info"
)

$targets = [System.Collections.Generic.List[string]]::new()
foreach ($relative in $relativeTargets) {
    $candidate = Assert-SafeCleanupPath (Join-Path $repoRoot $relative)
    if (Test-Path -LiteralPath $candidate) {
        $item = Get-Item -LiteralPath $candidate -Force
        if ($item.LinkType) {
            throw "Refusing linked cleanup target: $candidate"
        }
        if ($item.PSIsContainer -and
            -not (Get-ChildItem -LiteralPath $candidate -Force | Select-Object -First 1)) {
            continue
        }
        $targets.Add($candidate)
    }
}

$pythonRoots = @(
    (Join-Path $repoRoot "src"),
    (Join-Path $repoRoot "tests")
)
$pythonCaches = Get-ChildItem -LiteralPath $pythonRoots -Directory `
    -Filter "__pycache__" -Recurse -Force -ErrorAction SilentlyContinue |
    Where-Object { $_.FullName -notlike "*\node_modules\*" }
foreach ($cache in $pythonCaches) {
    $candidate = Assert-SafeCleanupPath $cache.FullName
    if ($cache.LinkType) {
        throw "Refusing linked Python cache target: $candidate"
    }
    $targets.Add($candidate)
}

foreach ($target in ($targets | Sort-Object Length -Descending -Unique)) {
    if ($PSCmdlet.ShouldProcess($target, "Delete generated artifact")) {
        Remove-Item -LiteralPath $target -Recurse -Force
    }
}

Write-Host "AURA cleanup completed for $($targets.Count) generated path(s)."
Write-Host "Preserved .env, .venv, node_modules, Terraform state, and deployment caches."
