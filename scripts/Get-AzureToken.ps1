#!/usr/bin/env pwsh

<#
.SYNOPSIS
    Get Azure access token from deployment info

.DESCRIPTION
    This script reads the deployment-info.json file and automatically gets an
    access token for the deployed Azure Cosmos DB MCP Server.

.PARAMETER DeploymentInfoPath
    Path to the deployment-info.json file (defaults to scripts/deployment-info.json)

.EXAMPLE
    .\Get-AzureToken.ps1

.EXAMPLE
    .\Get-AzureToken.ps1 -DeploymentInfoPath "./my-deployment-info.json"
#>

param(
    [Parameter(Mandatory = $false)]
    [string]$DeploymentInfoPath = "$PSScriptRoot/deployment-info.json"
)

Write-Host "🔍 Reading deployment information..." -ForegroundColor Green

# Check if deployment info file exists
if (-not (Test-Path $DeploymentInfoPath)) {
    Write-Error "❌ Deployment info file not found: $DeploymentInfoPath"
    Write-Host ""
    Write-Host "🔧 To create this file, run one of these deployment scripts:" -ForegroundColor Yellow
    Write-Host "• .\scripts\Deploy-CosmosMcpServer.ps1" -ForegroundColor Gray
    Write-Host "• ./scripts/deploy-cosmos-mcp-server.sh" -ForegroundColor Gray
    exit 1
}

try {
    # Read and parse deployment info
    $deploymentInfo = Get-Content $DeploymentInfoPath | ConvertFrom-Json
    
    if (-not $deploymentInfo.ENTRA_APP_CLIENT_ID) {
        throw "ENTRA_APP_CLIENT_ID not found in deployment info"
    }
    
    $clientId = $deploymentInfo.ENTRA_APP_CLIENT_ID
    $serverUrl = $deploymentInfo.MCP_SERVER_URI
    $tenantId = $deploymentInfo.AZURE_TENANT_ID
    
    Write-Host "✅ Deployment info loaded" -ForegroundColor Green
    Write-Host "Server URL: $serverUrl" -ForegroundColor Gray
    Write-Host "Client ID: $clientId" -ForegroundColor Gray
    if ($tenantId) {
        Write-Host "Tenant ID: $tenantId" -ForegroundColor Gray
    }
    
    # Get the token using our other script
    Write-Host ""
    $scriptPath = Join-Path $PSScriptRoot "Get-AADToken.ps1"
    
    if ($tenantId) {
        $token = & $scriptPath -ClientId $clientId -TenantId $tenantId
    } else {
        $token = & $scriptPath -ClientId $clientId
    }
    
    if ($token) {
        Write-Host ""
        Write-Host "🌐 Ready to test with your deployed server:" -ForegroundColor Cyan
        Write-Host "curl -X POST '$serverUrl/mcp' \\" -ForegroundColor Gray
        Write-Host "  -H 'Authorization: Bearer $token' \\" -ForegroundColor Gray
        Write-Host "  -H 'Content-Type: application/json' \\" -ForegroundColor Gray
        Write-Host "  -d '{\"jsonrpc\":\"2.0\",\"method\":\"tools/list\",\"id\":1}'" -ForegroundColor Gray
    }
    
    return $token
    
} catch {
    Write-Error "❌ Error reading deployment info: $($_.Exception.Message)"
    exit 1
}