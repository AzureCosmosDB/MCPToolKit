#!/usr/bin/env pwsh

<#
.SYNOPSIS
    Assigns the Mcp.Tool.Executor role to AI Foundry project's managed identity
.DESCRIPTION
    This script assigns the required role for AI Foundry integration with MCP Toolkit
.PARAMETER ResourceGroup
    Resource group where MCP Toolkit is deployed
.PARAMETER AIFoundryProjectResourceId
    Full resource ID of the AI Foundry project
.PARAMETER EntraAppClientId
    Optional: Client ID of the Entra app (speeds up execution)
#>

param(
    [Parameter(Mandatory=$true)]
    [string]$ResourceGroup,
    
    [Parameter(Mandatory=$true)]
    [string]$AIFoundryProjectResourceId,
    
    [Parameter(Mandatory=$false)]
    [string]$EntraAppClientId
)

$ErrorActionPreference = "Stop"

Write-Host "Setting up AI Foundry MCP Role Assignment" -ForegroundColor Cyan
Write-Host "==========================================" -ForegroundColor Cyan

# Get AI Foundry project managed identity
Write-Host "Getting AI Foundry project managed identity..." -ForegroundColor Yellow
$projectInfo = az rest --method GET --url "https://management.azure.com$($AIFoundryProjectResourceId)?api-version=2025-10-01-preview" | ConvertFrom-Json
$principalId = $projectInfo.identity.principalId
Write-Host "AI Foundry Managed Identity Principal ID: $principalId" -ForegroundColor Green

# Get MCP Toolkit Entra App
Write-Host "Getting MCP Toolkit Entra App..." -ForegroundColor Yellow

if ($EntraAppClientId) {
    $clientId = $EntraAppClientId
    Write-Host "Using provided Client ID: $clientId" -ForegroundColor Green
    $appInfo = az ad app show --id $clientId | ConvertFrom-Json
} else {
    # Fall back to searching - get from container app
    Write-Host "Looking up from Container App..." -ForegroundColor Gray
    $clientId = az containerapp show --name "mcp-toolkit-app" --resource-group $ResourceGroup --query "properties.template.containers[0].env[?name=='AzureAd__ClientId'].value" --output tsv
    
    if (-not $clientId) {
        Write-Error "Could not find Client ID. Please provide it via -EntraAppClientId parameter"
        exit 1
    }
    Write-Host "Found Client ID: $clientId" -ForegroundColor Green
    $appInfo = az ad app show --id $clientId | ConvertFrom-Json
}

# Get Service Principal
$spInfo = az ad sp show --id $clientId | ConvertFrom-Json
$spObjectId = $spInfo.id
Write-Host "Service Principal Object ID: $spObjectId" -ForegroundColor Green

# Get the Mcp.Tool.Executor role ID
$roleInfo = $appInfo.appRoles | Where-Object { $_.value -eq "Mcp.Tool.Executor" }
$roleId = $roleInfo.id
Write-Host "Mcp.Tool.Executor Role ID: $roleId" -ForegroundColor Green

# Check if role assignment already exists
Write-Host "Checking for existing role assignment..." -ForegroundColor Yellow
$existingAssignments = az rest --method GET --url "https://graph.microsoft.com/v1.0/servicePrincipals/$spObjectId/appRoleAssignedTo" | ConvertFrom-Json
$existingAssignment = $existingAssignments.value | Where-Object { $_.principalId -eq $principalId -and $_.appRoleId -eq $roleId }

if ($existingAssignment) {
    Write-Host "Role assignment already exists!" -ForegroundColor Green
    Write-Host "Assignment ID: $($existingAssignment.id)" -ForegroundColor Gray
} else {
    Write-Host "Creating role assignment..." -ForegroundColor Yellow
    
    # Get Graph API token
    $token = az account get-access-token --resource https://graph.microsoft.com --query accessToken -o tsv
    
    # Create role assignment payload
    $payload = @{
        principalId = $principalId
        resourceId = $spObjectId
        appRoleId = $roleId
    }

    # Create the role assignment using Invoke-RestMethod
    $headers = @{
        "Authorization" = "Bearer $token"
        "Content-Type" = "application/json"
    }
    
    $assignment = Invoke-RestMethod -Method POST `
        -Uri "https://graph.microsoft.com/v1.0/servicePrincipals/$spObjectId/appRoleAssignedTo" `
        -Headers $headers `
        -Body ($payload | ConvertTo-Json)
    
    Write-Host "Role assignment created successfully!" -ForegroundColor Green
    Write-Host "Assignment ID: $($assignment.id)" -ForegroundColor Gray
}

Write-Host ""
Write-Host "AI Foundry integration setup complete!" -ForegroundColor Green
