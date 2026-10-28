param(
    [ValidateSet('production', 'smoke', 'assemble', 'support')]
    [string]$Mode = 'production',
    [ValidateSet('auto', 'both', 'apple', 'youtube')]
    [string]$Sources = 'auto'
)
$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
$projectPython = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $projectPython)) {
    & python -m venv .venv
    if ($LASTEXITCODE -ne 0) { throw 'Python 3.12+ must be installed and on PATH.' }
    & $projectPython -m pip install -r requirements.lock
    if ($LASTEXITCODE -ne 0) { throw 'Dependency installation failed.' }
    & $projectPython -m pip install --no-deps -e .
    if ($LASTEXITCODE -ne 0) { throw 'Project installation failed.' }
}
& $projectPython -m pip check
if ($LASTEXITCODE -ne 0) { throw 'Installed dependencies are inconsistent.' }
& $projectPython -m pytest
if ($LASTEXITCODE -ne 0) { throw 'Tests failed. Stopping before any engine run.' }
& $projectPython -m ruff check src tests scripts
if ($LASTEXITCODE -ne 0) { throw 'Lint failed. Stopping before any engine run.' }
if ($Mode -eq 'production' -and $Sources -eq 'auto' -and -not $env:YOUTUBE_API_KEY) {
    Write-Host 'YOUTUBE_API_KEY is not set: running Apple/RSS only. Use the process environment to enable YouTube.'
}
& $projectPython -m incubrix_engine.submission $Mode --sources $Sources
if ($LASTEXITCODE -ne 0) { throw 'Engine operation failed. Inspect its log and preserve existing outputs.' }
Write-Host 'Operation completed. output/CURRENT_RUN.json points to the latest complete production run. Execution success does not mean submission-ready.'
