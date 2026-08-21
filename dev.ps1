# dev.ps1 - start QCnext (backend + frontend) from the development folder.
$ErrorActionPreference = "Stop"

$root = $PSScriptRoot
$backendPython = Join-Path $root "backend\.venv\Scripts\python.exe"
$frontendDir = Join-Path $root "frontend"
$backendPort = 8765
$frontendPort = 5173

if (-not (Test-Path -LiteralPath $backendPython)) {
    Write-Error "Backend venv not found at $backendPython. Create it first (see backend/README)."
}

$backend = $null
$frontend = $null
$cleanup = {
    if ($backend -and -not $backend.HasExited) { Stop-Process -Id $backend.Id -Force }
    if ($frontend -and -not $frontend.HasExited) { Stop-Process -Id $frontend.Id -Force }
}
Register-EngineEvent PowerShell.Exiting -Action $cleanup

Write-Host "Starting backend on http://localhost:$backendPort ..."
$backend = Start-Process -FilePath $backendPython -ArgumentList @(
    "-m", "uvicorn", "qualcoder_api.main:app", "--port", "$backendPort", "--reload"
) -WorkingDirectory $root -PassThru

Write-Host "Starting frontend on http://localhost:$frontendPort ..."
$npm = (Get-Command npm.cmd -ErrorAction Stop).Source
$frontend = Start-Process -FilePath $npm -ArgumentList @("run", "dev") -WorkingDirectory $frontendDir -PassThru

Write-Host "QCnext is running: http://localhost:$frontendPort"
Write-Host "Backend (PID $($backend.Id)), frontend (PID $($frontend.Id)). Ctrl+C to stop."

$frontend.WaitForExit()
$cleanup.Invoke()
