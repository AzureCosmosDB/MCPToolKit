# Loads the repo-root .env into the current process environment (the .NET
# server does NOT read .env on its own), then starts the MCP Toolkit server.
# Usage:  .\run-mcp-server.ps1
$ErrorActionPreference = "Stop"
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
$envFile = Join-Path $here ".env"

if (Test-Path $envFile) {
    Get-Content $envFile | ForEach-Object {
        $line = $_.Trim()
        if ($line -and -not $line.StartsWith("#") -and $line.Contains("=")) {
            $idx = $line.IndexOf("=")
            $name = $line.Substring(0, $idx).Trim()
            $value = $line.Substring($idx + 1).Trim()
            if ($value -match '^<.*>$') {
                Write-Warning "Env var '$name' still has a placeholder value; skipping. Edit .env."
            } else {
                [Environment]::SetEnvironmentVariable($name, $value, "Process")
                Write-Host "  set $name" -ForegroundColor DarkGray
            }
        }
    }
} else {
    Write-Warning "No .env file found at $envFile"
}

Write-Host "Starting Azure Cosmos DB MCP Toolkit on http://localhost:8080 ..." -ForegroundColor Cyan
dotnet run --project (Join-Path $here "src\AzureCosmosDB.MCP.Toolkit")
