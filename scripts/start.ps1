[CmdletBinding()]
param(
    [ValidateSet("desktop", "browser", "none")]
    [string]$Frontend = "desktop",

    [ValidateRange(1, 65535)]
    [int]$Port = 8765,

    [switch]$Install,
    [switch]$Build
)

$ErrorActionPreference = "Stop"
$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$venvRoot = Join-Path $repoRoot ".venv"
$python = Join-Path $venvRoot "Scripts\python.exe"
$frontendRoot = Join-Path $repoRoot "src\aura\workspace\web\frontend"
$frontendIndex = Join-Path $repoRoot "src\aura\workspace\web\representation\index.html"
$healthUrl = "http://127.0.0.1:$Port/health/live"
$appUrl = "http://127.0.0.1:$Port/"

function Invoke-Checked {
    param(
        [scriptblock]$Command,
        [string]$FailureMessage
    )

    & $Command
    if ($LASTEXITCODE -ne 0) {
        throw $FailureMessage
    }
}

function Test-NativeCommand {
    param(
        [string]$FilePath,
        [string[]]$ArgumentList
    )

    $previousErrorPreference = $ErrorActionPreference
    try {
        $ErrorActionPreference = "Continue"
        & $FilePath @ArgumentList *> $null
        return $LASTEXITCODE -eq 0
    } finally {
        $ErrorActionPreference = $previousErrorPreference
    }
}

function New-AuraVirtualEnvironment {
    $candidates = @(
        @{ Command = "py"; Prefix = @("-3.11") },
        @{ Command = "py"; Prefix = @("-3.10") },
        @{ Command = "py"; Prefix = @("-3.9") },
        @{ Command = "python"; Prefix = @() }
    )

    foreach ($candidate in $candidates) {
        if (-not (Get-Command $candidate.Command -ErrorAction SilentlyContinue)) {
            continue
        }

        $versionArguments = @($candidate.Prefix) + @(
            "-c",
            "import sys; raise SystemExit(0 if sys.version_info >= (3, 9) else 1)"
        )
        if (-not (Test-NativeCommand -FilePath $candidate.Command -ArgumentList $versionArguments)) {
            continue
        }

        Write-Host "Creating AURA virtual environment in .venv ..."
        $venvArguments = @($candidate.Prefix) + @("-m", "venv", $venvRoot)
        Invoke-Checked { & $candidate.Command @venvArguments } "Could not create the AURA virtual environment."
        return
    }

    throw "Python 3.9 or newer was not found. Install Python 3.11, then run this script again."
}

function Test-AuraBackend {
    try {
        $health = Invoke-RestMethod -Uri $healthUrl -Method Get -TimeoutSec 2
        return $health.status -eq "ok" -and $null -ne $health.version
    } catch {
        return $false
    }
}

Push-Location $repoRoot
try {
    if (-not (Test-Path -LiteralPath $python -PathType Leaf)) {
        New-AuraVirtualEnvironment
    }

    if (-not (Test-Path -LiteralPath $python -PathType Leaf)) {
        throw "The virtual environment is incomplete: $python is missing."
    }

    $backendDependenciesReady = Test-NativeCommand -FilePath $python -ArgumentList @(
        "-c",
        "import aura, fastapi, google.auth, uvicorn"
    )
    if ($Install -or -not $backendDependenciesReady) {
        Write-Host "Installing AURA backend dependencies ..."
        Invoke-Checked { & $python -m pip install -e ".[server,vertex]" } "Backend dependency installation failed."
    }

    if (-not (Test-Path -LiteralPath (Join-Path $repoRoot ".env")) -and
        (Test-Path -LiteralPath (Join-Path $repoRoot ".env.example"))) {
        Copy-Item -LiteralPath (Join-Path $repoRoot ".env.example") -Destination (Join-Path $repoRoot ".env")
        Write-Host "Created .env from .env.example. Configure cloud credentials there when live AI planning is required."
    }

    if ($Frontend -ne "none" -or $Build) {
        $npmCommand = Get-Command "npm.cmd" -ErrorAction SilentlyContinue
        if (-not $npmCommand) {
            throw "Node.js and npm were not found. Install the current Node.js LTS release, then run this script again."
        }

        if ($Install -or -not (Test-Path -LiteralPath (Join-Path $frontendRoot "node_modules"))) {
            Write-Host "Installing frontend dependencies ..."
            Push-Location $frontendRoot
            try {
                Invoke-Checked { & $npmCommand.Source ci } "Frontend dependency installation failed."
            } finally {
                Pop-Location
            }
        }

        if ($Build -or -not (Test-Path -LiteralPath $frontendIndex -PathType Leaf)) {
            Write-Host "Building the frontend ..."
            Push-Location $frontendRoot
            try {
                Invoke-Checked { & $npmCommand.Source run build } "Frontend build failed."
            } finally {
                Pop-Location
            }
        }
    }

    $backendProcess = $null
    if (Test-AuraBackend) {
        Write-Host "AURA backend is already healthy at $appUrl"
    } else {
        Write-Host "Starting AURA backend at $appUrl ..."
        $backendProcess = Start-Process -FilePath $python `
            -ArgumentList @("-m", "aura.workspace.server", "--host", "127.0.0.1", "--port", "$Port") `
            -WorkingDirectory $repoRoot -WindowStyle Hidden -PassThru

        $deadline = (Get-Date).AddSeconds(30)
        while ((Get-Date) -lt $deadline -and -not (Test-AuraBackend)) {
            if ($backendProcess.HasExited) {
                throw "The AURA backend exited before becoming healthy."
            }
            Start-Sleep -Milliseconds 500
        }

        if (-not (Test-AuraBackend)) {
            if (-not $backendProcess.HasExited) {
                Stop-Process -Id $backendProcess.Id -Force
            }
            throw "The AURA backend did not become healthy within 30 seconds. Check whether port $Port is already in use."
        }
        Write-Host "AURA backend ready."
    }

    if ($Frontend -eq "desktop") {
        $previousApiUrl = $env:AURA_API_URL
        $previousWsUrl = $env:AURA_WS_URL
        try {
            $env:AURA_API_URL = $appUrl.TrimEnd("/")
            $env:AURA_WS_URL = "ws://127.0.0.1:$Port"
            $desktopProcess = Start-Process -FilePath $npmCommand.Source `
                -ArgumentList @("run", "electron:dev") -WorkingDirectory $frontendRoot `
                -WindowStyle Hidden -PassThru
            Write-Host "AURA desktop launching (PID $($desktopProcess.Id))."
        } finally {
            if ($null -eq $previousApiUrl) { Remove-Item Env:AURA_API_URL -ErrorAction SilentlyContinue } else { $env:AURA_API_URL = $previousApiUrl }
            if ($null -eq $previousWsUrl) { Remove-Item Env:AURA_WS_URL -ErrorAction SilentlyContinue } else { $env:AURA_WS_URL = $previousWsUrl }
        }
    } elseif ($Frontend -eq "browser") {
        Start-Process $appUrl
        Write-Host "AURA opened in the default browser."
    } else {
        Write-Host "Backend-only startup complete."
    }
} finally {
    Pop-Location
}
