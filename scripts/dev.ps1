# Windows equivalent of the Makefile. Usage: powershell -File scripts/dev.ps1 <setup|dev|test|audit|build|up|down|seed|predownload [--yes]|offline-check>
param([Parameter(Mandatory = $true)][string]$Task, [Parameter(ValueFromRemainingArguments = $true)][string[]]$args)
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
$Api = Join-Path $Root "services/api"
$Web = Join-Path $Root "apps/web"
$env:NEXT_TELEMETRY_DISABLED = "1"

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
    Start-Process -NoNewWindow uv -ArgumentList "run", "--directory", $Api, "uvicorn", "kila.main:app", "--host", "127.0.0.1", "--port", "8000", "--reload"
    Run npm @("--prefix", $Web, "run", "dev")
  }
  "test" { Run uv @("run", "--directory", $Api, "pytest"); Run npm @("--prefix", $Web, "run", "typecheck") }
  "audit" { Run uv @("run", "--directory", $Api, "python", "../../scripts/licence_audit.py") }
  "build" { Run docker @("compose", "build") }
  "up" { Run docker @("compose", "up", "-d") }
  "down" { Run docker @("compose", "down") }
  "predownload" { Run uv (@("run", "--directory", $Api, "--group", "setup", "python", "../../scripts/predownload.py") + $args) }
  "seed" { Run uv @("run", "--directory", $Api, "python", "-m", "kila.seed") }
  "offline-check" { Run uv @("run", "--directory", $Api, "python", "../../scripts/offline_check.py") }
  default { throw "unknown task: $Task" }
}
