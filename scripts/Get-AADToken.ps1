#!/usr/bin/env pwsh

<#
.SYNOPSIS
    Get Azure AD access token for Azure Cosmos DB MCP Server

.DESCRIPTION
    This script retrieves an Azure AD access token that can be used to authenticate
    with the Azure Cosmos DB MCP Server. The token is scoped to the Entra ID app
    created during deployment.

.PARAMETER ClientId
    The Client ID of the Entra ID application (from deployment-info.json)

.PARAMETER Resource
    The resource URI for the token (defaults to api://{ClientId})

.PARAMETER TenantId
    The Azure AD tenant ID (optional, uses current tenant if not specified)

.EXAMPLE
    .\Get-AADToken.ps1 -ClientId "12345678-1234-1234-1234-123456789abc"

.EXAMPLE
    .\Get-AADToken.ps1 -ClientId "12345678-1234-1234-1234-123456789abc" -TenantId "87654321-4321-4321-4321-210987654321"
#>

param(
    [Parameter(Mandatory = $true)]
    [string]$ClientId,
    
    [Parameter(Mandatory = $false)]
    [string]$Resource,
    
    [Parameter(Mandatory = $false)]
    [string]$TenantId
)

# Set default resource if not provided
if (-not $Resource) {
    $Resource = "api://$ClientId"
}

Write-Host "🔐 Getting Azure AD Access Token..." -ForegroundColor Green
Write-Host "Client ID: $ClientId" -ForegroundColor Gray
Write-Host "Resource: $Resource" -ForegroundColor Gray

try {
    # Build az command
    $azCommand = @("account", "get-access-token", "--resource", $Resource, "--query", "accessToken", "--output", "tsv")
    
    if ($TenantId) {
        $azCommand += @("--tenant", $TenantId)
        Write-Host "Tenant ID: $TenantId" -ForegroundColor Gray
    }
    
    # Get the token
    $token = & az @azCommand
    
    if ($LASTEXITCODE -ne 0 -or [string]::IsNullOrWhiteSpace($token)) {
        throw "Failed to get access token. Make sure you're logged in with 'az login'"
    }
    
    Write-Host "✅ Token retrieved successfully!" -ForegroundColor Green
    Write-Host ""
    Write-Host "Access Token:" -ForegroundColor Yellow
    Write-Host $token
    Write-Host ""
    Write-Host "💡 Usage Examples:" -ForegroundColor Cyan
    Write-Host "# Test MCP tools list:" -ForegroundColor Gray
    Write-Host "curl -X POST 'https://your-app.azurecontainerapps.io/mcp' \\" -ForegroundColor Gray
    Write-Host "  -H 'Authorization: Bearer $token' \\" -ForegroundColor Gray
    Write-Host "  -H 'Content-Type: application/json' \\" -ForegroundColor Gray
    Write-Host "  -d '{\"jsonrpc\":\"2.0\",\"method\":\"tools/list\",\"id\":1}'" -ForegroundColor Gray
    Write-Host ""
    Write-Host "# Set as environment variable:" -ForegroundColor Gray
    Write-Host "`$env:ACCESS_TOKEN = '$token'" -ForegroundColor Gray
    
    # Also set it in the current session for convenience
    $env:ACCESS_TOKEN = $token
    Write-Host "✅ Token also set as `$env:ACCESS_TOKEN for this session" -ForegroundColor Green
    
    return $token
    
} catch {
    Write-Error "❌ Error getting token: $($_.Exception.Message)"
    Write-Host ""
    Write-Host "🔧 Troubleshooting:" -ForegroundColor Yellow
    Write-Host "1. Make sure you're logged in: az login" -ForegroundColor Gray
    Write-Host "2. Check if the Client ID is correct" -ForegroundColor Gray
    Write-Host "3. Ensure you have permissions to the Entra ID app" -ForegroundColor Gray
    Write-Host "4. Verify you have the 'Mcp.Tool.Executor' role assigned" -ForegroundColor Gray
    exit 1
}