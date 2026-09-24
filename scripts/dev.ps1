# Windows equivalent of the Makefile. Usage: powershell -File scripts/dev.ps1 <setup|dev|test|audit|build|up|down|seed|predownload [--yes]|offline-check>
param([Parameter(Mandatory = $true)][string]$Task, [Parameter(ValueFromRemainingArguments = $true)][string[]]$Rest)
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
$Api = Join-Path $Root "services/api"
$Web = Join-Path $Root "apps/web"
$env:NEXT_TELEMETRY_DISABLED = "1"

# Fail early, and say who holds the port, instead of a cryptic EADDRINUSE / WinError 10013.
function Assert-PortFree([int]$port, [string]$what) {
  $c = Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue | Select-Object -First 1
  if ($c) {
    $p = Get-Process -Id $c.OwningProcess -ErrorAction SilentlyContinue
    throw "Port $port ($what) is already in use by PID $($c.OwningProcess) ($($p.ProcessName)). KILA may already be running; stop it with: Stop-Process -Id $($c.OwningProcess)"
  }
}

function Run([string]$exe, [string[]]$argv) {
  & $exe @argv
  if ($LASTEXITCODE -ne 0) { throw "$exe $($argv -join ' ') failed ($LASTEXITCODE)" }
}

switch ($Task) {
  "setup" {
    Run uv @("sync", "--directory", $Api, "--python", "3.11")
    Run npm @("--prefix", $Web, "ci")
    if (-not (Test-Path (Join-Path $Root ".env"))) { Copy-Item (Join-Path $Root ".env.example") (Join-Path $Root ".env"); Write-Host "created .env; set KILA_SECRET_KEY" }
  }
  "dev" {
    Assert-PortFree 8000 "API"
    Assert-PortFree 3000 "web"
    $api = Start-Process -NoNewWindow -PassThru uv -ArgumentList "run", "--directory", $Api, "uvicorn", "kila.main:app", "--host", "127.0.0.1", "--port", "8000", "--reload"
    try {
      Write-Host "API on http://127.0.0.1:8000, web on http://localhost:3000 (Ctrl+C stops both)"
      Run npm @("--prefix", $Web, "run", "dev")
    } finally {
      # uv -> uvicorn reloader -> worker: stop the whole tree so port 8000 is freed.
      if (-not $api.HasExited) { taskkill /T /F /PID $api.Id | Out-Null }
    }
  }
  "test" { Run uv @("run", "--directory", $Api, "pytest"); Run npm @("--prefix", $Web, "run", "typecheck") }
  "audit" { Run uv @("run", "--directory", $Api, "python", "../../scripts/licence_audit.py") }
  "build" { Run docker @("compose", "build") }
  "up" { Run docker @("compose", "up", "-d") }
  "down" { Run docker @("compose", "down") }
  "predownload" { Run uv (@("run", "--directory", $Api, "--group", "setup", "python", "../../scripts/predownload.py") + $Rest) }
  "seed" { Run uv @("run", "--directory", $Api, "python", "-m", "kila.seed") }
  "offline-check" { Run uv @("run", "--directory", $Api, "python", "../../scripts/offline_check.py") }
  default { throw "unknown task: $Task" }
}
