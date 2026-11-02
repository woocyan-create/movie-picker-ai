$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot
$candidates = @(
    (Join-Path $PSScriptRoot '.venv\Scripts\python.exe'),
    (Join-Path $PSScriptRoot '..\.tools\python\python.exe')
)
$pythonCommand = Get-Command python -ErrorAction SilentlyContinue
if ($pythonCommand) { $candidates += $pythonCommand.Source }
$pythonExe = $candidates | Where-Object { Test-Path -LiteralPath $_ } | Select-Object -First 1
if (-not $pythonExe) { throw 'Python 3.12 is required. See README.md.' }
foreach ($port in @(8000, 8501)) {
    if (Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue) {
        throw "Port $port is already in use. Stop that server before starting Movie Picker."
    }
}
if (-not (Test-Path -LiteralPath '.env')) { Copy-Item -LiteralPath '.env.example' -Destination '.env' }
New-Item -ItemType Directory -Force runtime | Out-Null
$apiProcess = Start-Process -FilePath $pythonExe -ArgumentList @('-m', 'uvicorn', 'app.api:app', '--host', '127.0.0.1', '--port', '8000') -WorkingDirectory $PSScriptRoot -RedirectStandardOutput 'runtime/api.log' -RedirectStandardError 'runtime/api-error.log' -WindowStyle Hidden -PassThru
$uiProcess = Start-Process -FilePath $pythonExe -ArgumentList @('-m', 'streamlit', 'run', 'streamlit_app.py', '--server.address=127.0.0.1', '--server.port=8501', '--server.headless=true', '--browser.gatherUsageStats=false') -WorkingDirectory $PSScriptRoot -RedirectStandardOutput 'runtime/ui.log' -RedirectStandardError 'runtime/ui-error.log' -WindowStyle Hidden -PassThru
Write-Output "Movie Picker: http://localhost:8501"
Write-Output "API: http://localhost:8000/docs"
Write-Output "Processes: API=$($apiProcess.Id), UI=$($uiProcess.Id). Logs: runtime/"
