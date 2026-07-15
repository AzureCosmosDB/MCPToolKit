# Loads cosmos-retriever/.env is handled automatically by python-dotenv,
# so this just activates the venv interpreter and starts the FastAPI service.
# Usage:  .\run-retriever.ps1
$ErrorActionPreference = "Stop"
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
$py = Join-Path $here ".venv\Scripts\python.exe"
if (-not (Test-Path $py)) {
    throw "venv not found at $py. Run: uv venv --python 3.11 .venv; uv pip install --python .venv\Scripts\python.exe -e `".[dev]`""
}
Write-Host "Starting cosmos-retriever FastAPI service (reads .env)..." -ForegroundColor Cyan
& $py -m cosmos_retriever serve
