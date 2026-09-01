[CmdletBinding()]
param(
    [ValidateSet("3d", "verification", "ui", "all")]
    [string]$Module = "all"
)

$ErrorActionPreference = "Stop"
$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$frontend = Join-Path $repoRoot "src/aura/workspace/web/frontend"
$venvPython = Join-Path $repoRoot ".venv/Scripts/python.exe"
$python = if (Test-Path -LiteralPath $venvPython -PathType Leaf) { $venvPython } else { "python" }

function Invoke-Checked {
    param([scriptblock]$Command, [string]$FailureMessage)
    & $Command
    if ($LASTEXITCODE -ne 0) { throw $FailureMessage }
}

Push-Location $repoRoot
try {
    if ($Module -in @("3d", "verification", "all")) {
        $pythonTests = if ($Module -eq "3d") {
            @(
                "tests/test_representations.py",
                "tests/test_physical_assembly.py",
                "tests/test_connected_physical_assembly.py",
                "tests/test_generic_interface_compilers.py",
                "tests/test_cold_project_compilation.py"
            )
        } elseif ($Module -eq "verification") {
            @("tests/test_goal8_verification.py")
        } else {
            @("tests")
        }
        $previousErrorPreference = $ErrorActionPreference
        try {
            $ErrorActionPreference = "Continue"
            & $python -c "import pytest" *> $null
            $pytestProbeExitCode = $LASTEXITCODE
        } finally {
            $ErrorActionPreference = $previousErrorPreference
        }
        if ($pytestProbeExitCode -ne 0) {
            throw "Pytest is absent from the selected environment. Run '$python -m pip install -e `".[server,vertex,dev]`"' first."
        }
        Invoke-Checked { & $python -m pytest -q $pythonTests -m "not live" } "Python tests failed."
    }

    if ($Module -in @("ui", "all")) {
        if (-not (Test-Path (Join-Path $frontend "node_modules"))) {
            throw "Frontend dependencies are absent. Run 'npm ci' in $frontend first."
        }
        Push-Location $frontend
        try {
            Invoke-Checked { npm test } "Frontend tests failed."
            Invoke-Checked { npm run build } "Frontend build failed."
        } finally {
            Pop-Location
        }
    }

    if ($Module -eq "all") {
        Invoke-Checked { & $python -m compileall -q src tests } "Python compile check failed."
    }
} finally {
    Pop-Location
}
