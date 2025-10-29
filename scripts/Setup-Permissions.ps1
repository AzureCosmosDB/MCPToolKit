#!/usr/bin/env pwsh
<#
.SYNOPSIS
    Easy setup script for MCP Toolkit permissions
.DESCRIPTION
    Automatically configures all required permissions for the MCP Toolkit:
    1. Creates or updates the Entra ID application with MCP Tool Executor role
    2. Assigns the current user (or specified user) to the MCP role
    3. Configures Cosmos DB "Built-in Data Reader" role for the managed identity
    4. Configures AI Foundry "Cognitive Services OpenAI User" role for the managed identity (optional)
    
    This script should be run AFTER deploying the infrastructure with deploy-all-resources.bicep.
    
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

# Create new Entra App (always create fresh with unique name)
Write-Host "Creating new Entra ID App..." -ForegroundColor Yellow
$timestamp = Get-Date -Format "yyyyMMdd-HHmmss"
$appName = "Azure Cosmos DB MCP Toolkit API $timestamp"
$ClientId = $null
    
    # Create the app with service management reference (required by Azure policy)
    $roleId = [System.Guid]::NewGuid().ToString()
    
    try {
        $appJson = az ad app create --display-name $appName --service-management-reference "4405e061-966a-4249-afdd-f7435f54a510"
        if ($LASTEXITCODE -ne 0) { throw "Failed to create app" }
        
        $app = $appJson | ConvertFrom-Json
        $ClientId = $app.appId
        
        # Set identifier URI
        az ad app update --id $ClientId --identifier-uris "api://$ClientId" | Out-Null
        if ($LASTEXITCODE -ne 0) { throw "Failed to set identifier URI" }
        
        # Add app role - supports both User and Application for managed identity auth
        $roleManifest = @"
[
  {
    "id": "$roleId",
    "displayName": "MCP Tool Executor",
    "description": "Executor role for MCP Tool operations on Cosmos DB",
    "value": "Mcp.Tool.Executor",
    "isEnabled": true,
    "allowedMemberTypes": ["User", "Application"]
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
        
        # Expose an API scope so tokens can be requested without admin consent
        Write-Host "Exposing API..." -ForegroundColor Yellow
        $scopeId = [System.Guid]::NewGuid().ToString()
        $apiManifest = @"
{
  "oauth2PermissionScopes": [
    {
      "id": "$scopeId",
      "adminConsentDescription": "Allow the application to access MCP Toolkit API on behalf of the signed-in user",
      "adminConsentDisplayName": "Access MCP Toolkit API",
      "isEnabled": true,
      "type": "User",
      "userConsentDescription": "Allow the application to access MCP Toolkit API on your behalf",
      "userConsentDisplayName": "Access MCP Toolkit API",
      "value": "access_as_user"
    }
  ]
}
"@
        $apiFile = [System.IO.Path]::GetTempFileName()
        $apiManifest | Out-File -FilePath $apiFile -Encoding utf8 -NoNewline
        
        # Get app object ID for Graph API call
        $appObjectId = az ad app show --id $ClientId --query "id" --output tsv
        
        # Use Microsoft Graph API to update
        $token = az account get-access-token --resource https://graph.microsoft.com --query accessToken -o tsv
        $headers = @{
            "Authorization" = "Bearer $token"
            "Content-Type" = "application/json"
        }
        
        try {
            Invoke-RestMethod -Uri "https://graph.microsoft.com/v1.0/applications/$appObjectId" `
                -Method PATCH `
                -Headers $headers `
                -Body $apiManifest | Out-Null
            Write-Host "API exposed successfully" -ForegroundColor Green
        } catch {
            Write-Host "Warning: Could not expose API automatically" -ForegroundColor Yellow
        }
        
        Remove-Item $apiFile -Force -ErrorAction SilentlyContinue
        
        Write-Host "Created new MCP app with ID: $ClientId" -ForegroundColor Green
        Write-Host "App Name: $appName" -ForegroundColor Green
    } catch {
        Write-Error "Failed to create Entra app: $_"
        exit 1
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
    exit 1
}

# Update Container App with new Entra App Client ID
Write-Host "Updating Container App with new Entra App Client ID..." -ForegroundColor Yellow
$tenantId = az account show --query "tenantId" --output tsv

try {
    az containerapp update `
        --name $ContainerAppName `
        --resource-group $ResourceGroup `
        --set-env-vars "AzureAd__TenantId=$tenantId" "AzureAd__ClientId=$ClientId" "AzureAd__Audience=$ClientId" | Out-Null
    
    Write-Host "Container App environment updated with Client ID: $ClientId" -ForegroundColor Green
} catch {
    Write-Host "Warning: Could not update Container App automatically. You may need to update it manually." -ForegroundColor Yellow
    Write-Host "Run: az containerapp update --name $ContainerAppName --resource-group $ResourceGroup --set-env-vars AzureAd__ClientId=$ClientId" -ForegroundColor Yellow
}

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

# Find and configure AI Foundry or Azure OpenAI
Write-Host "Configuring AI Foundry / Azure OpenAI permissions..." -ForegroundColor Yellow
try {
    # First try to find AI Foundry projects
    $AIFoundryProjectsJson = az ml workspace list --resource-type project 2>$null
    if ($AIFoundryProjectsJson) {
        $AIFoundryProjects = $AIFoundryProjectsJson | ConvertFrom-Json
        if ($AIFoundryProjects -and $AIFoundryProjects.Count -gt 0) {
            $AIProject = $AIFoundryProjects[0]
            $SubscriptionId = az account show --query "id" --output tsv
            $AIProjectScope = "/subscriptions/$SubscriptionId/resourceGroups/$($AIProject.resourceGroup)/providers/Microsoft.MachineLearningServices/workspaces/$($AIProject.name)"
            
            az role assignment create `
                --assignee $ManagedIdentityId `
                --role "Cognitive Services OpenAI User" `
                --scope $AIProjectScope 2>$null | Out-Null
            
            if ($LASTEXITCODE -eq 0) {
                Write-Host "AI Foundry permissions configured for: $($AIProject.name)" -ForegroundColor Green
            } else {
                Write-Host "AI Foundry permissions may already be configured" -ForegroundColor Yellow
            }
        } else {
            # Fallback to legacy Azure OpenAI
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
                    Write-Host "No AI Foundry or Azure OpenAI found - skip this step" -ForegroundColor Yellow
                }
            } else {
                Write-Host "No AI Foundry or Azure OpenAI found - skip this step" -ForegroundColor Yellow
            }
        }
    } else {
        Write-Host "No AI Foundry found - checking for legacy Azure OpenAI..." -ForegroundColor Yellow
        # Fallback to legacy Azure OpenAI
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
            Write-Host "No AI Foundry or Azure OpenAI found - skip this step" -ForegroundColor Yellow
        }
    }
} catch {
    Write-Host "Note: AI Foundry / Azure OpenAI configuration may already exist or not available" -ForegroundColor Yellow
}

Write-Host ""
Write-Host "Setup Complete!" -ForegroundColor Green
Write-Host "Summary:" -ForegroundColor Cyan
Write-Host "- User can now access MCP tools: $UserEmail" -ForegroundColor Gray
Write-Host "- Managed identity has Cosmos DB read access" -ForegroundColor Gray
Write-Host "- Managed identity has AI Foundry / Azure OpenAI access" -ForegroundColor Gray
Write-Host ""
Write-Host "Test access:" -ForegroundColor Cyan
Write-Host "az account get-access-token --resource api://$ClientId" -ForegroundColor Gray