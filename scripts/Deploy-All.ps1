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

Write-Host "Authenticating to ACR..." -ForegroundColor Yellow
az acr login --name $acrName --output none
if ($LASTEXITCODE -ne 0) {
    Write-Host "Error: Failed to authenticate to ACR" -ForegroundColor Red
    exit 1
}
Write-Host "✓ ACR authentication successful" -ForegroundColor Green

Write-Host "Building .NET application..." -ForegroundColor Yellow
dotnet publish src/AzureCosmosDB.MCP.Toolkit/AzureCosmosDB.MCP.Toolkit.csproj -c Release -o src/AzureCosmosDB.MCP.Toolkit/bin/publish

Write-Host "Building Docker image..." -ForegroundColor Yellow
docker build -t $imageTag -f Dockerfile .
if ($LASTEXITCODE -ne 0) {
    Write-Host "Error: Docker build failed" -ForegroundColor Red
    exit 1
}
Write-Host "✓ Image built successfully" -ForegroundColor Green

Write-Host "Pushing to ACR..." -ForegroundColor Yellow
docker push $imageTag
if ($LASTEXITCODE -ne 0) {
    Write-Host "Error: Failed to push image to ACR" -ForegroundColor Red
    exit 1
}

# Verify image exists in ACR
Write-Host "Verifying image in ACR..." -ForegroundColor Yellow
$imageExists = az acr repository show --name $acrName --repository mcp-toolkit --output none 2>&1
if ($LASTEXITCODE -eq 0) {
    Write-Host "✓ Image verified in ACR: $imageTag" -ForegroundColor Green
} else {
    Write-Host "Error: Image not found in ACR after push" -ForegroundColor Red
    exit 1
}
Write-Host ""

# Step 3: Create Entra App for authentication
Write-Host "Step 3: Creating Entra App for MCP authentication..." -ForegroundColor Yellow
$appName = "MCP-Toolkit-Auth-$(Get-Date -Format 'yyyyMMddHHmmss')"
Write-Host "Creating app: $appName" -ForegroundColor Yellow

# Create the app
try {
    $appJson = az ad app create --display-name $appName --sign-in-audience AzureADMyOrg --service-management-reference "4405e061-966a-4249-afdd-f7435f54a510" | ConvertFrom-Json
    if (-not $appJson -or -not $appJson.appId) {
        throw "Failed to create Entra App"
    }
    $clientId = $appJson.appId
    Write-Host "✓ App created with Client ID: $clientId" -ForegroundColor Green
} catch {
    Write-Host "Error creating Entra App: $_" -ForegroundColor Red
    Write-Host "Please ensure you have permissions to create Azure AD applications" -ForegroundColor Yellow
    exit 1
}

# Create the Mcp.Tool.Executor role
$roleId = [guid]::NewGuid().ToString()
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
az ad app update --id $clientId --app-roles "@$roleFile" --output none
Remove-Item $roleFile -Force
Write-Host "✓ Added Mcp.Tool.Executor role" -ForegroundColor Green

# Expose API scope (for user consent without admin)
$oauth2PermissionId = [guid]::NewGuid().ToString()
$identifierUri = "api://$clientId"
az ad app update --id $clientId --identifier-uris $identifierUri --output none

$apiManifest = @"
{
  "oauth2PermissionScopes": [
    {
      "id": "$oauth2PermissionId",
      "adminConsentDescription": "Allow the application to access MCP Toolkit on behalf of the signed-in user",
      "adminConsentDisplayName": "Access MCP Toolkit",
      "userConsentDescription": "Allow the application to access MCP Toolkit on your behalf",
      "userConsentDisplayName": "Access MCP Toolkit",
      "value": "user_impersonation",
      "type": "User",
      "isEnabled": true
    }
  ]
}
"@

# Get app object ID for Graph API call
$appObjectId = az ad app show --id $clientId --query "id" --output tsv

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
    Write-Host "✓ Exposed API with user consent scope" -ForegroundColor Green
} catch {
    Write-Host "Warning: Could not expose API automatically - $_" -ForegroundColor Yellow
}

# Create service principal (required for role assignments)
Write-Host "Creating service principal..." -ForegroundColor Yellow
az ad sp create --id $clientId --output none 2>$null
if ($LASTEXITCODE -eq 0) {
    Write-Host "✓ Service principal created" -ForegroundColor Green
} else {
    Write-Host "✓ Service principal already exists" -ForegroundColor Green
}

# Configure redirect URIs for Container App web UI
Write-Host "Configuring redirect URIs for web UI..." -ForegroundColor Yellow
$containerAppFqdn = az containerapp show --name $ContainerAppName --resource-group $ResourceGroup --query "properties.configuration.ingress.fqdn" -o tsv
if ($containerAppFqdn) {
    $redirectUris = @("https://$containerAppFqdn", "https://$containerAppFqdn/")
    $spaConfig = @{
        spa = @{
            redirectUris = $redirectUris
        }
    } | ConvertTo-Json -Depth 10
    
    try {
        Invoke-RestMethod -Uri "https://graph.microsoft.com/v1.0/applications/$appObjectId" `
            -Method PATCH `
            -Headers $headers `
            -Body $spaConfig | Out-Null
        Write-Host "✓ Redirect URIs configured for web UI" -ForegroundColor Green
    } catch {
        Write-Host "Warning: Could not configure redirect URIs - $_" -ForegroundColor Yellow
    }
} else {
    Write-Host "Warning: Container App FQDN not found, skipping redirect URIs" -ForegroundColor Yellow
}

# Assign current user to MCP role
Write-Host "Assigning current user to MCP role..." -ForegroundColor Yellow
$currentUserEmail = az account show --query "user.name" -o tsv
try {
    $spId = az ad sp list --filter "appId eq '$clientId'" --query "[0].id" -o tsv
    $userId = az ad user show --id $currentUserEmail --query "id" -o tsv 2>$null
    
    if ($userId) {
        $appRoleId = $roleId  # Use the role ID we created earlier
        
        $roleAssignmentBody = @{
            principalId = $userId
            resourceId = $spId
            appRoleId = $appRoleId
        } | ConvertTo-Json
        
        try {
            Invoke-RestMethod -Uri "https://graph.microsoft.com/v1.0/users/$userId/appRoleAssignments" `
                -Method POST `
                -Headers $headers `
                -Body $roleAssignmentBody | Out-Null
            Write-Host "✓ User $currentUserEmail assigned to MCP role" -ForegroundColor Green
        } catch {
            if ($_.Exception.Response.StatusCode.Value__ -eq 400) {
                Write-Host "✓ User already has MCP role" -ForegroundColor Green
            } else {
                Write-Host "Warning: Could not assign user role - $_" -ForegroundColor Yellow
            }
        }
    } else {
        Write-Host "Warning: Could not find current user, skipping role assignment" -ForegroundColor Yellow
    }
} catch {
    Write-Host "Warning: User role assignment skipped - $_" -ForegroundColor Yellow
}
Write-Host ""

# Step 4: Get managed identity for container app
Write-Host "Step 4: Getting container app managed identity..." -ForegroundColor Yellow
$containerApp = az containerapp show --name $ContainerAppName --resource-group $ResourceGroup | ConvertFrom-Json
if (-not $containerApp) {
    Write-Host "Error: Container app '$ContainerAppName' not found. Please run infrastructure deployment first." -ForegroundColor Red
    exit 1
}

# Extract managed identity principal ID from the container app
if ($containerApp.identity -and $containerApp.identity.userAssignedIdentities) {
    $identityKeys = $containerApp.identity.userAssignedIdentities.PSObject.Properties.Name
    if ($identityKeys) {
        $managedIdentityId = $identityKeys[0]
        $identityDetails = $containerApp.identity.userAssignedIdentities.PSObject.Properties.Value[0]
        $miPrincipalId = $identityDetails.principalId
        Write-Host "✓ Managed Identity Principal ID: $miPrincipalId" -ForegroundColor Green
    } else {
        Write-Host "Warning: No user-assigned identity found on container app" -ForegroundColor Yellow
        $miPrincipalId = $null
    }
} else {
    Write-Host "Warning: Container app has no managed identity configured" -ForegroundColor Yellow
    $miPrincipalId = $null
}
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

# Assign AcrPull permission to managed identity for container registry
Write-Host "Assigning ACR pull permission to managed identity..." -ForegroundColor Yellow
$acrId = az acr show --name $acrName --resource-group $ResourceGroup --query id -o tsv
$existingAcrRole = az role assignment list --assignee $miPrincipalId --scope $acrId --role "AcrPull" --query "[0].id" -o tsv
if (-not $existingAcrRole) {
    az role assignment create --assignee $miPrincipalId --role "AcrPull" --scope $acrId --output none
    Write-Host "✓ AcrPull role assigned to managed identity" -ForegroundColor Green
} else {
    Write-Host "✓ AcrPull role already assigned" -ForegroundColor Green
}
Write-Host ""

# Step 6: Configure container app with ACR authentication
Write-Host "Step 6: Configuring container app ACR authentication..." -ForegroundColor Yellow
$managedIdentityId = $managedIdentityId  # From Step 4
az containerapp registry set `
    --name $ContainerAppName `
    --resource-group $ResourceGroup `
    --server "$acrName.azurecr.io" `
    --identity $managedIdentityId `
    --output none
Write-Host "✓ Container app configured to use managed identity for ACR" -ForegroundColor Green
Write-Host ""

# Step 7: Update container app with authentication settings
Write-Host "Step 7: Updating container app with authentication configuration..." -ForegroundColor Yellow

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

# Use --replace-env-vars with each env var as a separate argument
az containerapp update `
    --name $ContainerAppName `
    --resource-group $ResourceGroup `
    --image $imageTag `
    --replace-env-vars $envVars `
    --output none

Write-Host "✓ Container app updated with new image and authentication settings" -ForegroundColor Green
Write-Host ""

# Step 8: AI Foundry integration (if project resource ID provided)
if ($AIFoundryProjectResourceId) {
    Write-Host "Step 8: Setting up AI Foundry integration..." -ForegroundColor Yellow
    
    # Get AI Foundry project managed identity
    Write-Host "Getting AI Foundry managed identity..." -ForegroundColor Yellow
    
    # Try to get the identity from the project resource
    # AI Foundry projects can be either CognitiveServices accounts or MachineLearningServices workspaces
    $aifPrincipalId = $null
    
    # First, try as CognitiveServices (common for AI Foundry)
    if ($AIFoundryProjectResourceId -match 'Microsoft\.CognitiveServices/accounts/([^/]+)') {
        $accountName = $matches[1]
        $rgMatch = $AIFoundryProjectResourceId -match '/resourceGroups/([^/]+)'
        $aifResourceGroup = $matches[1]
        
        $aifPrincipalId = az cognitiveservices account show --name $accountName --resource-group $aifResourceGroup --query "identity.principalId" -o tsv 2>$null
    }
    
    # If not found, try as MachineLearningServices workspace
    if (-not $aifPrincipalId) {
        $aifIdentity = az rest --method GET --url "${AIFoundryProjectResourceId}?api-version=2024-07-01-preview" --resource https://management.azure.com 2>$null | ConvertFrom-Json
        $aifPrincipalId = $aifIdentity.identity.principalId
    }
    
    if (-not $aifPrincipalId) {
        Write-Host "Error: Could not get AI Foundry managed identity principal ID" -ForegroundColor Red
        Write-Host "Skipping AI Foundry role assignment" -ForegroundColor Yellow
    } else {
        Write-Host "✓ AI Foundry Managed Identity Principal ID: $aifPrincipalId" -ForegroundColor Green
        
        # Get service principal object ID for the Entra App
        Write-Host "Getting service principal object ID..." -ForegroundColor Yellow
        $spObjectId = az ad sp show --id $clientId --query "id" -o tsv
        if (-not $spObjectId) {
            Write-Host "Error: Could not get service principal object ID" -ForegroundColor Red
            exit 1
        }
        Write-Host "✓ Service Principal Object ID: $spObjectId" -ForegroundColor Green
        
        # Assign Mcp.Tool.Executor role to AI Foundry MI
        Write-Host "Assigning Mcp.Tool.Executor role to AI Foundry managed identity..." -ForegroundColor Yellow
        
        $token = az account get-access-token --resource https://graph.microsoft.com --query accessToken -o tsv
        $headers = @{
            "Authorization" = "Bearer $token"
            "Content-Type" = "application/json"
        }
        
        $assignmentBody = @{
            principalId = $aifPrincipalId
            resourceId = $spObjectId
            appRoleId = $roleId
        } | ConvertTo-Json
        
        try {
            Invoke-RestMethod -Method Post `
                -Uri "https://graph.microsoft.com/v1.0/servicePrincipals/$spObjectId/appRoleAssignedTo" `
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
    }
    
    Write-Host ""
    Write-Host "AI Foundry Connection Configuration:" -ForegroundColor Cyan
    Write-Host "  Connection Name: Give it a name (e.g., 'mcp-cosmos-connection')" -ForegroundColor White
    Write-Host "  MCP Server URL: https://$($containerApp.properties.configuration.ingress.fqdn)/mcp" -ForegroundColor White
    Write-Host "  Authentication: Connection (Managed Identity)" -ForegroundColor White
    Write-Host "  Audience/Client ID: $clientId" -ForegroundColor White
    Write-Host ""
} else {
    Write-Host "Step 8: Skipping AI Foundry integration (no project resource ID provided)" -ForegroundColor Yellow
    Write-Host ""
}

# Validate all required values before displaying summary
Write-Host "Validating deployment..." -ForegroundColor Yellow
$validationErrors = @()

if (-not $clientId) {
    $validationErrors += "Client ID is missing (Entra App creation may have failed)"
}
if (-not $tenantId) {
    $validationErrors += "Tenant ID is missing"
}
if (-not $miPrincipalId) {
    $validationErrors += "Managed Identity Principal ID is missing"
}
if (-not $containerApp.properties.configuration.ingress.fqdn) {
    $validationErrors += "Container App FQDN is missing"
}

if ($validationErrors.Count -gt 0) {
    Write-Host ""
    Write-Host "==================================================" -ForegroundColor Red
    Write-Host "Deployment completed with errors" -ForegroundColor Red
    Write-Host "==================================================" -ForegroundColor Red
    Write-Host ""
    Write-Host "The following issues were detected:" -ForegroundColor Yellow
    foreach ($error in $validationErrors) {
        Write-Host "  ✗ $error" -ForegroundColor Red
    }
    Write-Host ""
    Write-Host "Please run the Setup-Permissions.ps1 script to fix these issues:" -ForegroundColor Yellow
    Write-Host "  .\scripts\Setup-Permissions.ps1 -ResourceGroup `"$ResourceGroup`"" -ForegroundColor White
    Write-Host ""
    exit 1
}

Write-Host "✓ All components validated successfully" -ForegroundColor Green
Write-Host ""

# Step 8: Display comprehensive summary with AI Foundry configuration
Write-Host "==================================================" -ForegroundColor Cyan
Write-Host "           Deployment Complete! ✓" -ForegroundColor Green
Write-Host "==================================================" -ForegroundColor Cyan
Write-Host ""

Write-Host "🔧 MCP TOOLKIT CONFIGURATION VALUES" -ForegroundColor Yellow
Write-Host "==================================================" -ForegroundColor Cyan
Write-Host ""

Write-Host "1. MCP Server Endpoint:" -ForegroundColor Cyan
Write-Host "   https://$($containerApp.properties.configuration.ingress.fqdn)/mcp" -ForegroundColor Green
Write-Host ""

Write-Host "2. Audience / Client ID:" -ForegroundColor Cyan
Write-Host "   $clientId" -ForegroundColor Green
Write-Host ""

Write-Host "3. Tenant ID:" -ForegroundColor Cyan
Write-Host "   $tenantId" -ForegroundColor Green
Write-Host ""

Write-Host "4. Managed Identity Principal ID:" -ForegroundColor Cyan
Write-Host "   $miPrincipalId" -ForegroundColor Green
Write-Host ""

Write-Host "5. Container App:" -ForegroundColor Cyan
Write-Host "   Name: $ContainerAppName" -ForegroundColor White
Write-Host "   Resource Group: $ResourceGroup" -ForegroundColor White
Write-Host "   Image: $imageTag" -ForegroundColor White
Write-Host ""

Write-Host "==================================================" -ForegroundColor Cyan
Write-Host "🤖 AI FOUNDRY MCP CONNECTION SETUP" -ForegroundColor Yellow
Write-Host "==================================================" -ForegroundColor Cyan
Write-Host ""

Write-Host "To configure your AI Foundry project:" -ForegroundColor White
Write-Host ""
Write-Host "1. Navigate to:" -ForegroundColor Cyan
Write-Host "   https://ai.azure.com" -ForegroundColor White
Write-Host "   → Select your project" -ForegroundColor White
Write-Host "   → Tools → Connections" -ForegroundColor White
Write-Host ""

Write-Host "2. Click 'New Connection' and use these values:" -ForegroundColor Cyan
Write-Host ""
Write-Host "   Connection Name:      cosmos-mcp-toolkit" -ForegroundColor White
Write-Host "                         (or any name you prefer)" -ForegroundColor Gray
Write-Host ""
Write-Host "   MCP Server URL:       https://$($containerApp.properties.configuration.ingress.fqdn)/mcp" -ForegroundColor White
Write-Host ""
Write-Host "   Authentication:       Connection (Managed Identity)" -ForegroundColor White
Write-Host ""
Write-Host "   Audience/Client ID:   $clientId" -ForegroundColor White
Write-Host ""

Write-Host "3. Test the connection:" -ForegroundColor Cyan
Write-Host "   Click 'Test Connection' - you should see ✓ Success" -ForegroundColor White
Write-Host ""

Write-Host "4. Available MCP Tools:" -ForegroundColor Cyan
Write-Host "   • list_databases - List all Cosmos DB databases" -ForegroundColor White
Write-Host "   • list_collections - List containers in a database" -ForegroundColor White
Write-Host "   • get_recent_documents - Get recent documents from a container" -ForegroundColor White
Write-Host "   • find_document_by_id - Find a specific document by ID" -ForegroundColor White
Write-Host "   • text_search - Full-text search across documents" -ForegroundColor White
Write-Host "   • vector_search - AI-powered semantic search" -ForegroundColor White
Write-Host "   • get_approximate_schema - Get container schema" -ForegroundColor White
Write-Host ""

if ($AIFoundryProjectResourceId) {
    Write-Host "==================================================" -ForegroundColor Cyan
    Write-Host "✓ AI Foundry Integration Configured" -ForegroundColor Green
    Write-Host "==================================================" -ForegroundColor Cyan
    Write-Host ""
    Write-Host "Your AI Foundry project's managed identity has been granted" -ForegroundColor White
    Write-Host "the 'Mcp.Tool.Executor' role and can now call MCP tools." -ForegroundColor White
    Write-Host ""
}

Write-Host "==================================================" -ForegroundColor Cyan
Write-Host "📋 QUICK TEST COMMANDS" -ForegroundColor Yellow
Write-Host "==================================================" -ForegroundColor Cyan
Write-Host ""

Write-Host "Test via PowerShell:" -ForegroundColor Cyan
Write-Host ""
Write-Host "`$token = az account get-access-token --resource `"api://$clientId`" --query accessToken -o tsv" -ForegroundColor Gray
Write-Host "`$headers = @{Authorization=`"Bearer `$token`"; `"Content-Type`"=`"application/json`"}" -ForegroundColor Gray
Write-Host "`$body = '{`"jsonrpc`":`"2.0`",`"method`":`"tools/list`",`"id`":1}'" -ForegroundColor Gray
Write-Host "Invoke-RestMethod -Uri `"https://$($containerApp.properties.configuration.ingress.fqdn)/mcp`" -Method Post -Headers `$headers -Body `$body" -ForegroundColor Gray
Write-Host ""

Write-Host "Test via Web UI:" -ForegroundColor Cyan
Write-Host "   https://$($containerApp.properties.configuration.ingress.fqdn)" -ForegroundColor White
Write-Host ""

Write-Host "==================================================" -ForegroundColor Cyan
Write-Host "📚 Documentation" -ForegroundColor Yellow
Write-Host "==================================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "For more information, see:" -ForegroundColor White
Write-Host "  • README.md - Full documentation" -ForegroundColor Gray
Write-Host "  • TESTING_GUIDE.md - Testing instructions" -ForegroundColor Gray
Write-Host "  • docs/TROUBLESHOOTING.md - Common issues" -ForegroundColor Gray
Write-Host ""
Write-Host "✓ Deployment successful! Your MCP Toolkit is ready to use." -ForegroundColor Green
Write-Host ""
