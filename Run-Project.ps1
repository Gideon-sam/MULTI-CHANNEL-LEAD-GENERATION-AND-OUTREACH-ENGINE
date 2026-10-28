param(
    [ValidateSet('setup', 'run', 'review', 'import', 'dashboard', 'verify', 'package')]
    [string]$Action = 'dashboard',
    [string]$Workbook = 'output/Human_Review.xlsx',
    [switch]$Refresh,
    [switch]$ReviewedOnly
)
$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
$projectPython = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
function Invoke-CheckedPython {
    param([string[]]$Arguments, [int[]]$AllowedCodes = @(0))
    & $projectPython @Arguments
    if ($LASTEXITCODE -notin $AllowedCodes) {
        throw "Python command failed with exit code $LASTEXITCODE. See the message above."
    }
}
if ($Action -eq 'setup') {
    if (-not (Test-Path -LiteralPath $projectPython)) {
        & python -m venv .venv
        if ($LASTEXITCODE -ne 0) { throw 'Could not create the environment. Install Python 3.12 or newer.' }
    }
    Invoke-CheckedPython -Arguments @('-m', 'pip', 'install', '-r', 'requirements.lock')
    Invoke-CheckedPython -Arguments @('-m', 'pip', 'install', '--no-deps', '-e', '.')
    Invoke-CheckedPython -Arguments @('-m', 'pip', 'check')
    Write-Host 'Setup complete. Run .\Run-Project.ps1 -Action verify'
    exit 0
}
if (-not (Test-Path -LiteralPath $projectPython)) { throw 'Run .\Run-Project.ps1 -Action setup first.' }
switch ($Action) {
    'run' {
        $runArguments = @('-m', 'incubrix_engine', 'run', '--config', 'config/production.json', '--input', 'inputs/cached_discovery_expanded.csv')
        if ($Refresh) { $runArguments += '--refresh' }
        if ($ReviewedOnly) { $runArguments += '--reviewed-only' }
        Invoke-CheckedPython -Arguments $runArguments -AllowedCodes @(0, 2)
        if ($LASTEXITCODE -eq 2) { Write-Host 'Results exported. Qualification gates still need evidence; see output/validation_report.json.' }
    }
    'review' {
        Invoke-CheckedPython -Arguments @('-m', 'incubrix_engine', 'review', 'export', '--workbook', $Workbook)
        Write-Host "Open $Workbook and follow START_HERE. Existing review files are never overwritten."
    }
    'import' {
        Invoke-CheckedPython -Arguments @('-m', 'incubrix_engine', 'review', 'import', '--workbook', $Workbook)
        Write-Host 'Now run .\Run-Project.ps1 -Action run -ReviewedOnly to verify sources and export approved leads.'
    }
    'dashboard' {
        if (-not (Test-Path -LiteralPath 'output/audit_dashboard.html')) { throw 'No dashboard yet; run the research first.' }
        Write-Host 'Open http://127.0.0.1:8080/audit_dashboard.html. Press Ctrl+C to stop.'
        Invoke-CheckedPython -Arguments @('-m', 'incubrix_engine', 'serve', '--port', '8080')
    }
    'verify' {
        Invoke-CheckedPython -Arguments @('-m', 'pip', 'check')
        Invoke-CheckedPython -Arguments @('-m', 'pytest', '--junitxml=verification/tests.xml')
        Invoke-CheckedPython -Arguments @('-m', 'ruff', 'check', 'src', 'tests', 'scripts')
    }
    'package' { Invoke-CheckedPython -Arguments @('scripts/package_project.py') }
}
