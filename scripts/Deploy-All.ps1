#!/usr/bin/env pwsh
<#
.SYNOPSIS
    Complete deployment script for Azure Cosmos DB MCP Toolkit with AI Foundry integration
.DESCRIPTION
    This script performs a complete end-to-end deployment:
    1. Creates/updates Azure resources (Container App, Cosmos DB, AI Foundry)
    2. Creates Entra app with proper roles for AI Foundry managed identity authentication
    3. Assigns necessary permissions (Cosmos DB, Entra app roles)
    4. Deploys the MCP server container
    5. Sets up AI Foundry role assignments
.PARAMETER ResourceGroup
    Name of the Azure resource group
.PARAMETER Location
    Azure region for resources (default: eastus)
.PARAMETER CosmosAccountName
    Name of the Cosmos DB account (default: cosmosmcpkit)
.PARAMETER ContainerAppName
    Name of the container app (default: mcp-toolkit-app)
.PARAMETER AIFoundryProjectResourceId
    Full resource ID of the AI Foundry project (optional - for AI Foundry integration)
.EXAMPLE
    ./Deploy-All.ps1 -ResourceGroup "cosmos-mcp-toolkit-final"
.EXAMPLE
    ./Deploy-All.ps1 -ResourceGroup "cosmos-mcp-toolkit-final" -AIFoundryProjectResourceId "/subscriptions/.../Microsoft.MachineLearningServices/workspaces/cosmos-mcp-toolkit-test/projects/cosmos-mcp-toolkit-test-project"
#>

param(
    [Parameter(Mandatory=$true)]
    [string]$ResourceGroup,
    
    [Parameter(Mandatory=$false)]
    [string]$Location = "eastus",
    
    [Parameter(Mandatory=$false)]
    [string]$CosmosAccountName = "cosmosmcpkit",
    
    [Parameter(Mandatory=$false)]
    [string]$ContainerAppName = "mcp-toolkit-app",
    
    [Parameter(Mandatory=$false)]
    [string]$AIFoundryProjectResourceId
)

$ErrorActionPreference = "Stop"

Write-Host "==================================================" -ForegroundColor Cyan
Write-Host "Azure Cosmos DB MCP Toolkit - Complete Deployment" -ForegroundColor Cyan
Write-Host "==================================================" -ForegroundColor Cyan
Write-Host ""

# Get current Azure context
$context = az account show | ConvertFrom-Json
$subscriptionId = $context.id
$tenantId = $context.tenantId

Write-Host "✓ Using subscription: $($context.name) ($subscriptionId)" -ForegroundColor Green
Write-Host "✓ Tenant ID: $tenantId" -ForegroundColor Green
Write-Host ""

# Step 1: Ensure resource group exists
Write-Host "Step 1: Checking resource group..." -ForegroundColor Yellow
$rgExists = az group exists --name $ResourceGroup
if ($rgExists -eq "false") {
    Write-Host "Creating resource group '$ResourceGroup' in $Location..." -ForegroundColor Yellow
    az group create --name $ResourceGroup --location $Location --output none
    Write-Host "✓ Resource group created" -ForegroundColor Green
} else {
    Write-Host "✓ Resource group exists" -ForegroundColor Green
}
Write-Host ""

# Step 2: Build and push Docker image
Write-Host "Step 2: Building and pushing Docker image..." -ForegroundColor Yellow
$timestamp = Get-Date -Format "yyyyMMdd-HHmmss"
$acrName = (az acr list --resource-group $ResourceGroup --query "[0].name" -o tsv)
if (-not $acrName) {
    Write-Host "Error: No Azure Container Registry found in resource group" -ForegroundColor Red
    exit 1
}
$imageTag = "$acrName.azurecr.io/mcp-toolkit:$timestamp"

Write-Host "Building .NET application..." -ForegroundColor Yellow
dotnet publish src/AzureCosmosDB.MCP.Toolkit/AzureCosmosDB.MCP.Toolkit.csproj -c Release -o src/AzureCosmosDB.MCP.Toolkit/bin/publish

Write-Host "Building Docker image..." -ForegroundColor Yellow
docker build -t $imageTag -f Dockerfile .

Write-Host "Pushing to ACR..." -ForegroundColor Yellow
docker push $imageTag
Write-Host "✓ Image pushed: $imageTag" -ForegroundColor Green
Write-Host ""

# Step 3: Create Entra App for authentication
Write-Host "Step 3: Creating Entra App for MCP authentication..." -ForegroundColor Yellow
$appName = "MCP-Toolkit-Auth-$(Get-Date -Format 'yyyyMMddHHmmss')"
Write-Host "Creating app: $appName" -ForegroundColor Yellow

# Create the app
$appJson = az ad app create --display-name $appName --sign-in-audience AzureADMyOrg | ConvertFrom-Json
$clientId = $appJson.appId
Write-Host "✓ App created with Client ID: $clientId" -ForegroundColor Green

# Create the Mcp.Tool.Executor role
$roleId = [guid]::NewGuid().ToString()
$appRoles = @(
    @{
        allowedMemberTypes = @("User", "Application")
        description = "Can execute MCP tools"
        displayName = "Mcp.Tool.Executor"
        id = $roleId
        isEnabled = $true
        value = "Mcp.Tool.Executor"
    }
)

$appRolesJson = ($appRoles | ConvertTo-Json -Depth 10 -Compress).Replace('"', '\"')
az ad app update --id $clientId --app-roles $appRolesJson --output none
Write-Host "✓ Added Mcp.Tool.Executor role" -ForegroundColor Green

# Expose API scope (for user consent without admin)
$oauth2PermissionId = [guid]::NewGuid().ToString()
$oauth2Permissions = @{
    oauth2PermissionScopes = @(
        @{
            adminConsentDescription = "Allow the application to access MCP Toolkit on behalf of the signed-in user"
            adminConsentDisplayName = "Access MCP Toolkit"
            id = $oauth2PermissionId
            isEnabled = $true
            type = "User"
            userConsentDescription = "Allow the application to access MCP Toolkit on your behalf"
            userConsentDisplayName = "Access MCP Toolkit"
            value = "user_impersonation"
        }
    )
}

$identifierUri = "api://$clientId"
az ad app update --id $clientId --identifier-uris $identifierUri --output none

$apiJson = ($oauth2Permissions | ConvertTo-Json -Depth 10 -Compress).Replace('"', '\"')
$apiBody = "{`"api`": $apiJson}"
az rest --method PATCH --uri "https://graph.microsoft.com/v1.0/applications/$($appJson.id)" --headers "Content-Type=application/json" --body $apiBody --output none
Write-Host "✓ Exposed API with user consent scope" -ForegroundColor Green
Write-Host ""

# Step 4: Get managed identity for container app
Write-Host "Step 4: Getting container app managed identity..." -ForegroundColor Yellow
$containerApp = az containerapp show --name $ContainerAppName --resource-group $ResourceGroup | ConvertFrom-Json
if (-not $containerApp) {
    Write-Host "Error: Container app '$ContainerAppName' not found. Please run infrastructure deployment first." -ForegroundColor Red
    exit 1
}

$managedIdentityId = ($containerApp.identity.userAssignedIdentities.PSObject.Properties.Name)[0]
$managedIdentity = az identity show --ids $managedIdentityId | ConvertFrom-Json
$miPrincipalId = $managedIdentity.principalId
Write-Host "✓ Managed Identity Principal ID: $miPrincipalId" -ForegroundColor Green
Write-Host ""

# Step 5: Assign Cosmos DB permissions
Write-Host "Step 5: Assigning Cosmos DB permissions to managed identity..." -ForegroundColor Yellow
$cosmosAccountId = "/subscriptions/$subscriptionId/resourceGroups/$ResourceGroup/providers/Microsoft.DocumentDB/databaseAccounts/$CosmosAccountName"
$roleDefinitionId = "00000000-0000-0000-0000-000000000001" # Built-in Data Reader

$existingAssignment = az cosmosdb sql role assignment list --account-name $CosmosAccountName --resource-group $ResourceGroup --query "[?principalId=='$miPrincipalId']" | ConvertFrom-Json
if ($existingAssignment.Count -eq 0) {
    az cosmosdb sql role assignment create `
        --account-name $CosmosAccountName `
        --resource-group $ResourceGroup `
        --role-definition-id $roleDefinitionId `
        --principal-id $miPrincipalId `
        --scope $cosmosAccountId `
        --output none
    Write-Host "✓ Cosmos DB Data Reader role assigned" -ForegroundColor Green
} else {
    Write-Host "✓ Cosmos DB role already assigned" -ForegroundColor Green
}
Write-Host ""

# Step 6: Update container app with authentication settings
Write-Host "Step 6: Updating container app with authentication configuration..." -ForegroundColor Yellow

# Get existing environment variables
$existingEnv = $containerApp.properties.template.containers[0].env

# Update with authentication settings
$envVars = @()
foreach ($env in $existingEnv) {
    if ($env.name -notin @("AzureAd__ClientId", "AzureAd__TenantId", "AzureAd__Audience")) {
        $envVars += "$($env.name)=$($env.value)"
    }
}
$envVars += "AzureAd__ClientId=$clientId"
$envVars += "AzureAd__TenantId=$tenantId"
$envVars += "AzureAd__Audience=$clientId"

$envVarString = $envVars -join " "

az containerapp update `
    --name $ContainerAppName `
    --resource-group $ResourceGroup `
    --image $imageTag `
    --set-env-vars $envVarString `
    --output none

Write-Host "✓ Container app updated with new image and authentication settings" -ForegroundColor Green
Write-Host ""

# Step 7: AI Foundry integration (if project resource ID provided)
if ($AIFoundryProjectResourceId) {
    Write-Host "Step 7: Setting up AI Foundry integration..." -ForegroundColor Yellow
    
    # Parse project resource ID
    if ($AIFoundryProjectResourceId -match '/projects/([^/]+)$') {
        $projectName = $matches[1]
    } else {
        Write-Host "Error: Invalid AI Foundry project resource ID format" -ForegroundColor Red
        exit 1
    }
    
    # Get AI Foundry project managed identity
    $aifIdentity = az rest --method GET --url "${AIFoundryProjectResourceId}?api-version=2024-07-01-preview" --resource https://management.azure.com | ConvertFrom-Json
    $aifPrincipalId = $aifIdentity.identity.principalId
    
    Write-Host "✓ AI Foundry Project Principal ID: $aifPrincipalId" -ForegroundColor Green
    
    # Assign Mcp.Tool.Executor role to AI Foundry MI
    Write-Host "Assigning Mcp.Tool.Executor role to AI Foundry managed identity..." -ForegroundColor Yellow
    
    $token = az account get-access-token --resource https://graph.microsoft.com --query accessToken -o tsv
    $headers = @{
        "Authorization" = "Bearer $token"
        "Content-Type" = "application/json"
    }
    
    $assignmentBody = @{
        principalId = $aifPrincipalId
        resourceId = $appJson.id
        appRoleId = $roleId
    } | ConvertTo-Json
    
    try {
        Invoke-RestMethod -Method Post `
            -Uri "https://graph.microsoft.com/v1.0/servicePrincipals/$($appJson.id)/appRoleAssignedTo" `
            -Headers $headers `
            -Body $assignmentBody `
            -ErrorAction SilentlyContinue | Out-Null
        Write-Host "✓ Mcp.Tool.Executor role assigned to AI Foundry" -ForegroundColor Green
    } catch {
        if ($_.Exception.Response.StatusCode -eq 409) {
            Write-Host "✓ Role already assigned to AI Foundry" -ForegroundColor Green
        } else {
            Write-Host "Warning: Could not assign role. Error: $($_.Exception.Message)" -ForegroundColor Yellow
        }
    }
    
    Write-Host ""
    Write-Host "AI Foundry Connection Configuration:" -ForegroundColor Cyan
    Write-Host "  Connection Name: Give it a name (e.g., 'mcp-cosmos-connection')" -ForegroundColor White
    Write-Host "  MCP Server URL: https://$($containerApp.properties.configuration.ingress.fqdn)/mcp" -ForegroundColor White
    Write-Host "  Authentication: Connection (Managed Identity)" -ForegroundColor White
    Write-Host "  Audience/Client ID: $clientId" -ForegroundColor White
    Write-Host ""
} else {
    Write-Host "Step 7: Skipping AI Foundry integration (no project resource ID provided)" -ForegroundColor Yellow
    Write-Host ""
}

# Step 8: Display summary
Write-Host "==================================================" -ForegroundColor Cyan
Write-Host "Deployment Complete!" -ForegroundColor Green
Write-Host "==================================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "MCP Server Endpoint:" -ForegroundColor Cyan
Write-Host "  https://$($containerApp.properties.configuration.ingress.fqdn)/mcp" -ForegroundColor White
Write-Host ""
Write-Host "Authentication Configuration:" -ForegroundColor Cyan
Write-Host "  Entra App Client ID: $clientId" -ForegroundColor White
Write-Host "  Tenant ID: $tenantId" -ForegroundColor White
Write-Host "  Required Role: Mcp.Tool.Executor" -ForegroundColor White
Write-Host ""
Write-Host "Container App:" -ForegroundColor Cyan
Write-Host "  Name: $ContainerAppName" -ForegroundColor White
Write-Host "  Image: $imageTag" -ForegroundColor White
Write-Host "  Managed Identity: $miPrincipalId" -ForegroundColor White
Write-Host ""
Write-Host "Next Steps:" -ForegroundColor Cyan
if ($AIFoundryProjectResourceId) {
    Write-Host "  1. Create MCP connection in AI Foundry using the configuration above" -ForegroundColor White
    Write-Host "  2. Test the connection with your AI agent" -ForegroundColor White
} else {
    Write-Host "  1. Configure your MCP client with the endpoint and authentication details" -ForegroundColor White
    Write-Host "  2. Use Client ID '$clientId' as the audience for bearer tokens" -ForegroundColor White
}
Write-Host ""
Write-Host "Documentation: See README.md for detailed usage instructions" -ForegroundColor White
Write-Host ""
