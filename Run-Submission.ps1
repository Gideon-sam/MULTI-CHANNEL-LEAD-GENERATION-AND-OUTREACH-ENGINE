param(
    [ValidateSet('production', 'smoke', 'assemble', 'support')]
    [string]$Mode = 'production',
    [ValidateSet('auto', 'all', 'both', 'apple', 'podcastindex', 'youtube')]
    [string]$Sources = 'auto'
)
$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
$localEnvPath = Join-Path $PSScriptRoot '.env'
if (Test-Path -LiteralPath $localEnvPath) {
    foreach ($rawLine in Get-Content -LiteralPath $localEnvPath) {
        $line = $rawLine.Trim()
        if (-not $line -or $line.StartsWith('#')) { continue }
        $separator = $line.IndexOf('=')
        if ($separator -lt 1) { throw 'Invalid .env line: expected NAME=VALUE.' }
        $name = $line.Substring(0, $separator).Trim()
        $value = $line.Substring($separator + 1).Trim()
        if ($name -notmatch '^[A-Za-z_][A-Za-z0-9_]*$') {
            throw 'Invalid .env variable name.'
        }
        if ($value -and -not [Environment]::GetEnvironmentVariable($name, 'Process')) {
            [Environment]::SetEnvironmentVariable($name, $value, 'Process')
        }
    }
}
$credentialNames = @(
    'YOUTUBE_API_KEY',
    'TAVILY_API_KEY',
    'PODCAST_INDEX_API_KEY',
    'PODCAST_INDEX_API_SECRET'
)
foreach ($name in $credentialNames) {
    if (-not [Environment]::GetEnvironmentVariable($name, 'Process')) {
        $userValue = [Environment]::GetEnvironmentVariable($name, 'User')
        if ($userValue) {
            [Environment]::SetEnvironmentVariable($name, $userValue, 'Process')
        }
    }
}
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
