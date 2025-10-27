#!/usr/bin/env pwsh
<#
.SYNOPSIS
    Easy setup script for MCP Toolkit permissions
.DESCRIPTION
    Automatically configures all required permissions for the MCP Toolkit
.PARAMETER ResourceGroup
    The Azure resource group name
.PARAMETER UserEmail
    Email address of user to grant access (optional - uses current user if not specified)
.EXAMPLE
    .\Setup-Permissions.ps1 -ResourceGroup "rg-sajee-cosmos-mcp-kit"
    .\Setup-Permissions.ps1 -ResourceGroup "rg-sajee-cosmos-mcp-kit" -UserEmail "user@domain.com"
#>

param(
    [Parameter(Mandatory=$true)]
    [string]$ResourceGroup,
    
    [Parameter(Mandatory=$false)]
    [string]$UserEmail
)

$ErrorActionPreference = "Stop"

Write-Host "🔧 MCP Toolkit Easy Setup" -ForegroundColor Cyan
Write-Host "=========================" -ForegroundColor Cyan

# Get current user if not specified
if (-not $UserEmail) {
    $UserEmail = az account show --query "user.name" --output tsv
    Write-Host "Using current user: $UserEmail" -ForegroundColor Gray
}

# Get the Entra App Client ID
Write-Host "🔍 Finding Entra ID App..." -ForegroundColor Yellow
$ClientId = az ad app list --display-name "*mcp*" --query "[0].appId" --output tsv
if (-not $ClientId) {
    Write-Error "Could not find MCP Entra ID app. Make sure you deployed the infrastructure first."
}
Write-Host "Found App ID: $ClientId" -ForegroundColor Green

# Get Container App managed identity
Write-Host "🔍 Getting managed identity..." -ForegroundColor Yellow
$ContainerAppName = az containerapp list --resource-group $ResourceGroup --query "[0].name" --output tsv
$ManagedIdentityId = az containerapp show --name $ContainerAppName --resource-group $ResourceGroup --query "identity.principalId" --output tsv
Write-Host "Managed Identity: $ManagedIdentityId" -ForegroundColor Green

# Assign user to MCP role
Write-Host "👤 Assigning user to MCP role..." -ForegroundColor Yellow
az ad app role assignment create --id $ClientId --principal $UserEmail --role "Mcp.Tool.Executor"
Write-Host "✅ User role assigned" -ForegroundColor Green

# Find and configure Cosmos DB
Write-Host "🗄️ Configuring Cosmos DB permissions..." -ForegroundColor Yellow
$CosmosAccount = az cosmosdb list --query "[0].{name:name,resourceGroup:resourceGroup}" | ConvertFrom-Json
if ($CosmosAccount) {
    az cosmosdb sql role assignment create `
        --account-name $CosmosAccount.name `
        --resource-group $CosmosAccount.resourceGroup `
        --scope "/" `
        --principal-id $ManagedIdentityId `
        --role-definition-name "Cosmos DB Built-in Data Reader"
    Write-Host "✅ Cosmos DB permissions configured" -ForegroundColor Green
} else {
    Write-Host "⚠️ No Cosmos DB found - you'll need to configure this manually" -ForegroundColor Yellow
}

# Find and configure Azure OpenAI
Write-Host "🤖 Configuring Azure OpenAI permissions..." -ForegroundColor Yellow
$OpenAIAccount = az cognitiveservices account list --query "[?kind=='OpenAI'] | [0].{name:name,resourceGroup:resourceGroup}" | ConvertFrom-Json
if ($OpenAIAccount) {
    $SubscriptionId = az account show --query "id" --output tsv
    $OpenAIScope = "/subscriptions/$SubscriptionId/resourceGroups/$($OpenAIAccount.resourceGroup)/providers/Microsoft.CognitiveServices/accounts/$($OpenAIAccount.name)"
    
    az role assignment create `
        --assignee $ManagedIdentityId `
        --role "Cognitive Services OpenAI User" `
        --scope $OpenAIScope
    Write-Host "✅ Azure OpenAI permissions configured" -ForegroundColor Green
} else {
    Write-Host "⚠️ No Azure OpenAI found - you'll need to configure this manually" -ForegroundColor Yellow
}

Write-Host ""
Write-Host "🎉 Setup Complete!" -ForegroundColor Green
Write-Host "📋 Summary:" -ForegroundColor Cyan
Write-Host "   • User '$UserEmail' can now access MCP tools" -ForegroundColor Gray
Write-Host "   • Managed identity has Cosmos DB read access" -ForegroundColor Gray
Write-Host "   • Managed identity has Azure OpenAI access" -ForegroundColor Gray
Write-Host ""
Write-Host "🧪 Test access:" -ForegroundColor Cyan
Write-Host "   az account get-access-token --resource 'api://$ClientId'" -ForegroundColor Gray