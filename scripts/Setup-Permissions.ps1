#!/usr/bin/env pwsh
<#
.SYNOPSIS
    Easy setup script for MCP Toolkit permissions
.DESCRIPTION
    Automatically configures all required permissions for the MCP Toolkit:
    1. Creates or updates the Entra ID application with MCP Tool Executor role
    2. Assigns the current user (or specified user) to the MCP role
    3. Configures Cosmos DB "Built-in Data Reader" role for the managed identity
    4. Configures Azure OpenAI "Cognitive Services OpenAI User" role for the managed identity
    
    This script should be run AFTER deploying the infrastructure with main.bicep.
    
.PARAMETER ResourceGroup
    The Azure resource group name where the infrastructure was deployed
.PARAMETER UserEmail
    Email address of user to grant access (optional - uses current user if not specified)
.EXAMPLE
    .\Setup-Permissions.ps1 -ResourceGroup "rg-sajee-mcp-toolkit"
    .\Setup-Permissions.ps1 -ResourceGroup "rg-sajee-mcp-toolkit" -UserEmail "user@domain.com"
.NOTES
    Prerequisites:
    - Azure CLI must be installed and logged in
    - User must have permissions to create Entra ID apps and assign roles
    - Infrastructure must be deployed using infrastructure/main.bicep
#>

param(
    [Parameter(Mandatory=$true)]
    [string]$ResourceGroup,
    
    [Parameter(Mandatory=$false)]
    [string]$UserEmail
)

$ErrorActionPreference = "Stop"

Write-Host "MCP Toolkit Easy Setup" -ForegroundColor Cyan
Write-Host "======================" -ForegroundColor Cyan

# Get current user if not specified
if (-not $UserEmail) {
    $UserEmail = az account show --query "user.name" --output tsv
    Write-Host "Using current user: $UserEmail" -ForegroundColor Gray
}

# Get the Entra App Client ID
Write-Host "Finding Entra ID App..." -ForegroundColor Yellow
$ClientId = az ad app list --query "[?contains(displayName, 'Azure Cosmos DB MCP Toolkit API')].appId | [0]" --output tsv

if (-not $ClientId) {
    Write-Host "No MCP app found. Creating one now..." -ForegroundColor Yellow
    
    # Create the app with service management reference (required by Azure policy)
    $roleId = [System.Guid]::NewGuid().ToString()
    $appManifest = @"
{
  "displayName": "Azure Cosmos DB MCP Toolkit API",
  "serviceManagementReference": "4405e061-966a-4249-afdd-f7435f54a510",
  "appRoles": [
    {
      "id": "$roleId",
      "displayName": "MCP Tool Executor",
      "description": "Executor role for MCP Tool operations on Cosmos DB",
      "value": "Mcp.Tool.Executor",
      "isEnabled": true,
      "allowedMemberTypes": ["User"]
    }
  ]
}
"@
    
    $tempFile = [System.IO.Path]::GetTempFileName()
    $appManifest | Out-File -FilePath $tempFile -Encoding utf8 -NoNewline
    
    try {
        $appJson = az ad app create --display-name "Azure Cosmos DB MCP Toolkit API" --service-management-reference "4405e061-966a-4249-afdd-f7435f54a510"
        if ($LASTEXITCODE -ne 0) { throw "Failed to create app" }
        
        $app = $appJson | ConvertFrom-Json
        $ClientId = $app.appId
        
        # Set identifier URI
        az ad app update --id $ClientId --identifier-uris "api://$ClientId" | Out-Null
        if ($LASTEXITCODE -ne 0) { throw "Failed to set identifier URI" }
        
        # Add app role
        $roleManifest = @"
[
  {
    "id": "$roleId",
    "displayName": "MCP Tool Executor",
    "description": "Executor role for MCP Tool operations on Cosmos DB",
    "value": "Mcp.Tool.Executor",
    "isEnabled": true,
    "allowedMemberTypes": ["User"]
  }
]
"@
        $roleFile = [System.IO.Path]::GetTempFileName()
        $roleManifest | Out-File -FilePath $roleFile -Encoding utf8 -NoNewline
        az ad app update --id $ClientId --app-roles "@$roleFile" | Out-Null
        Remove-Item $roleFile -Force
        
        if ($LASTEXITCODE -ne 0) { throw "Failed to add app role" }
        
        # Create service principal
        az ad sp create --id $ClientId | Out-Null
        if ($LASTEXITCODE -ne 0) { throw "Failed to create service principal" }
        
        Write-Host "Created new MCP app with ID: $ClientId" -ForegroundColor Green
    } finally {
        if (Test-Path $tempFile) { Remove-Item $tempFile -Force }
    }
} else {
    Write-Host "Found existing app with ID: $ClientId" -ForegroundColor Green
    
    # Make sure service principal exists
    $spExists = az ad sp show --id $ClientId 2>$null
    if ($LASTEXITCODE -ne 0) {
        Write-Host "Creating service principal..." -ForegroundColor Yellow
        az ad sp create --id $ClientId | Out-Null
    }
    
    # Make sure identifier URI is set
    $appInfo = az ad app show --id $ClientId | ConvertFrom-Json
    if (-not $appInfo.identifierUris -or $appInfo.identifierUris.Count -eq 0) {
        Write-Host "Setting identifier URI..." -ForegroundColor Yellow
        az ad app update --id $ClientId --identifier-uris "api://$ClientId" | Out-Null
    }
    
    # Make sure app role exists
    if (-not $appInfo.appRoles -or $appInfo.appRoles.Count -eq 0) {
        Write-Host "Adding app role..." -ForegroundColor Yellow
        $roleId = [System.Guid]::NewGuid().ToString()
        $roleManifest = @"
[
  {
    "id": "$roleId",
    "displayName": "MCP Tool Executor",
    "description": "Executor role for MCP Tool operations on Cosmos DB",
    "value": "Mcp.Tool.Executor",
    "isEnabled": true,
    "allowedMemberTypes": ["User"]
  }
]
"@
        $roleFile = [System.IO.Path]::GetTempFileName()
        $roleManifest | Out-File -FilePath $roleFile -Encoding utf8 -NoNewline
        az ad app update --id $ClientId --app-roles "@$roleFile" | Out-Null
        Remove-Item $roleFile -Force
    }
}

# Configure redirect URIs for the Container App
Write-Host "Configuring redirect URIs..." -ForegroundColor Yellow
$ContainerAppFqdn = az containerapp list --resource-group $ResourceGroup --query "[0].properties.configuration.ingress.fqdn" --output tsv

if ($ContainerAppFqdn) {
    $redirectUris = @("https://$ContainerAppFqdn", "https://$ContainerAppFqdn/")
    
    try {
        # Get app object ID
        $appObjectId = az ad app show --id $ClientId --query "id" --output tsv
        
        # Use Microsoft Graph API to set SPA redirect URIs
        $token = az account get-access-token --resource https://graph.microsoft.com --query accessToken -o tsv
        $headers = @{
            "Authorization" = "Bearer $token"
            "Content-Type" = "application/json"
        }
        
        $spaConfig = @{
            spa = @{
                redirectUris = $redirectUris
            }
        } | ConvertTo-Json -Depth 10
        
        Invoke-RestMethod -Uri "https://graph.microsoft.com/v1.0/applications/$appObjectId" `
            -Method PATCH `
            -Headers $headers `
            -Body $spaConfig | Out-Null
        
        Write-Host "Redirect URIs configured: $($redirectUris -join ', ')" -ForegroundColor Green
    } catch {
        Write-Host "Warning: Could not configure redirect URIs automatically. You may need to add them manually in the Azure Portal." -ForegroundColor Yellow
        Write-Host "Add these URIs to the SPA platform: $($redirectUris -join ', ')" -ForegroundColor Yellow
    }
} else {
    Write-Host "Warning: Could not find Container App URL. Redirect URIs not configured." -ForegroundColor Yellow
}

# Get Container App managed identity
Write-Host "Getting managed identity..." -ForegroundColor Yellow
$ContainerAppName = az containerapp list --resource-group $ResourceGroup --query "[0].name" --output tsv

if (-not $ContainerAppName) {
    Write-Error "No Container App found in resource group $ResourceGroup"
}

# Get the identity - handle both system and user-assigned
$identityJson = az containerapp show --name $ContainerAppName --resource-group $ResourceGroup --query "identity" --output json
$identity = $identityJson | ConvertFrom-Json

if ($identity.type -eq "SystemAssigned" -or $identity.type -eq "SystemAssigned, UserAssigned") {
    $ManagedIdentityId = $identity.principalId
} elseif ($identity.type -eq "UserAssigned") {
    # Get the first user-assigned identity
    $userIdentityKey = ($identity.userAssignedIdentities | Get-Member -MemberType NoteProperty)[0].Name
    $ManagedIdentityId = $identity.userAssignedIdentities.$userIdentityKey.principalId
} else {
    Write-Error "Container App does not have a managed identity configured"
}

Write-Host "Managed Identity: $ManagedIdentityId" -ForegroundColor Green

# Assign user to MCP role
Write-Host "Assigning user to MCP role..." -ForegroundColor Yellow
try {
    # Get the service principal ID
    $spId = az ad sp list --filter "appId eq '$ClientId'" --query "[0].id" --output tsv
    
    # Get user object ID
    $userId = az ad user show --id $UserEmail --query "id" --output tsv
    
    # Get the app role ID
    $appRoleId = az ad app show --id $ClientId --query "appRoles[0].id" --output tsv
    
    # Assign the role using Microsoft Graph API
    $body = @{
        principalId = $userId
        resourceId = $spId
        appRoleId = $appRoleId
    } | ConvertTo-Json
    
    az rest --method POST --uri "https://graph.microsoft.com/v1.0/users/$userId/appRoleAssignments" --body $body --headers "Content-Type=application/json" | Out-Null
    
    if ($LASTEXITCODE -eq 0) {
        Write-Host "User role assigned" -ForegroundColor Green
    } else {
        Write-Host "Role may already be assigned or there was an error" -ForegroundColor Yellow
    }
} catch {
    Write-Host "Note: Role assignment may already exist" -ForegroundColor Yellow
}

# Find and configure Cosmos DB
Write-Host "Configuring Cosmos DB permissions..." -ForegroundColor Yellow
try {
    $CosmosAccountsJson = az cosmosdb list 2>$null
    if ($CosmosAccountsJson) {
        $CosmosAccounts = $CosmosAccountsJson | ConvertFrom-Json
        if ($CosmosAccounts -and $CosmosAccounts.Count -gt 0) {
            $CosmosAccount = $CosmosAccounts[0]
            az cosmosdb sql role assignment create `
                --account-name $CosmosAccount.name `
                --resource-group $CosmosAccount.resourceGroup `
                --scope "/" `
                --principal-id $ManagedIdentityId `
                --role-definition-name "Cosmos DB Built-in Data Reader" 2>$null | Out-Null
            
            if ($LASTEXITCODE -eq 0) {
                Write-Host "Cosmos DB permissions configured for: $($CosmosAccount.name)" -ForegroundColor Green
            } else {
                Write-Host "Cosmos DB permissions may already be configured" -ForegroundColor Yellow
            }
        } else {
            Write-Host "No Cosmos DB found - skip this step" -ForegroundColor Yellow
        }
    } else {
        Write-Host "No Cosmos DB found - skip this step" -ForegroundColor Yellow
    }
} catch {
    Write-Host "Note: Cosmos DB configuration may already exist or not available" -ForegroundColor Yellow
}

# Find and configure Azure OpenAI
Write-Host "Configuring Azure OpenAI permissions..." -ForegroundColor Yellow
try {
    $OpenAIAccountsJson = az cognitiveservices account list --query "[?kind=='OpenAI']" 2>$null
    if ($OpenAIAccountsJson) {
        $OpenAIAccounts = $OpenAIAccountsJson | ConvertFrom-Json
        if ($OpenAIAccounts -and $OpenAIAccounts.Count -gt 0) {
            $OpenAIAccount = $OpenAIAccounts[0]
            $SubscriptionId = az account show --query "id" --output tsv
            $OpenAIScope = "/subscriptions/$SubscriptionId/resourceGroups/$($OpenAIAccount.resourceGroup)/providers/Microsoft.CognitiveServices/accounts/$($OpenAIAccount.name)"
            
            az role assignment create `
                --assignee $ManagedIdentityId `
                --role "Cognitive Services OpenAI User" `
                --scope $OpenAIScope 2>$null | Out-Null
            
            if ($LASTEXITCODE -eq 0) {
                Write-Host "Azure OpenAI permissions configured for: $($OpenAIAccount.name)" -ForegroundColor Green
            } else {
                Write-Host "Azure OpenAI permissions may already be configured" -ForegroundColor Yellow
            }
        } else {
            Write-Host "No Azure OpenAI found - skip this step" -ForegroundColor Yellow
        }
    } else {
        Write-Host "No Azure OpenAI found - skip this step" -ForegroundColor Yellow
    }
} catch {
    Write-Host "Note: Azure OpenAI configuration may already exist or not available" -ForegroundColor Yellow
}

Write-Host ""
Write-Host "Setup Complete!" -ForegroundColor Green
Write-Host "Summary:" -ForegroundColor Cyan
Write-Host "- User can now access MCP tools: $UserEmail" -ForegroundColor Gray
Write-Host "- Managed identity has Cosmos DB read access" -ForegroundColor Gray
Write-Host "- Managed identity has Azure OpenAI access" -ForegroundColor Gray
Write-Host ""
Write-Host "Test access:" -ForegroundColor Cyan
Write-Host "az account get-access-token --resource api://$ClientId" -ForegroundColor Gray