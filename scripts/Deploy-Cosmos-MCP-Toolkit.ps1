#!/usr/bin/env pwsh
<#
.SYNOPSIS
    Deploy Azure Cosmos DB MCP Toolkit to Azure Container App
.DESCRIPTION
    This script performs the complete MCP deployment following the PostgreSQL team's pattern:
    1. Creates Entra app with proper authentication and role
    2. Deploys infrastructure if needed
    3. Builds and pushes Docker image
    4. Assigns necessary permissions (Cosmos DB, Container Registry)
    5. Updates container app with new image and authentication
    6. Creates deployment-info.json for AI Foundry integration
.PARAMETER ResourceGroup
    Azure Resource Group name for deployment (REQUIRED)
.PARAMETER Location
    Azure region for deployment (default: eastus)
.PARAMETER CosmosAccountName
    Name of the Cosmos DB account (default: cosmosmcpkit)
.PARAMETER ContainerAppName
    Name of the container app (default: mcp-toolkit-app)
.EXAMPLE
    ./Deploy-Cosmos-MCP-Server.ps1 -ResourceGroup "my-cosmos-mcp-rg"
.EXAMPLE
    ./Deploy-Cosmos-MCP-Server.ps1 -ResourceGroup "my-project" -Location "westus2" -CosmosAccountName "mycosmosdb"
#>

param(
    [Parameter(Mandatory=$true)]
    [string]$ResourceGroup,
    
    [Parameter(Mandatory=$false)]
    [string]$Location = "eastus",
    
    [Parameter(Mandatory=$false)]
    [string]$CosmosAccountName = "",
    
    [Parameter(Mandatory=$false)]
    [string]$ContainerAppName = ""
)

$ErrorActionPreference = "Stop"
$SCRIPT_DIR = Split-Path -Parent $MyInvocation.MyCommand.Path

# Entra App Configuration (following PostgreSQL pattern)
$ENTRA_APP_NAME = "Azure Cosmos DB MCP Toolkit API"
$ENTRA_APP_ROLE_DESC = "Executor role for MCP Tool operations on Cosmos DB"
$ENTRA_APP_ROLE_DISPLAY = "MCP Tool Executor"
$ENTRA_APP_ROLE_VALUE = "Mcp.Tool.Executor"

# Color functions
function Write-Info { param($Message) Write-Host "[INFO] $Message" -ForegroundColor Green }
function Write-Warn { param($Message) Write-Host "[WARN] $Message" -ForegroundColor Yellow }
function Write-Error { param($Message) Write-Host "[ERROR] $Message" -ForegroundColor Red }

function Auto-Detect-Resources {
    Write-Info "Auto-detecting resources in resource group: $ResourceGroup"
    
    # Auto-detect Cosmos DB account
    if ([string]::IsNullOrEmpty($script:CosmosAccountName)) {
        $cosmosAccounts = az cosmosdb list --resource-group $ResourceGroup --query "[].name" -o tsv
        if ($cosmosAccounts) {
            $script:CosmosAccountName = ($cosmosAccounts -split "`n")[0].Trim()
            Write-Info "Auto-detected Cosmos DB account: $script:CosmosAccountName"
        } else {
            Write-Error "No Cosmos DB account found in resource group $ResourceGroup"
            exit 1
        }
    }
    
    # Auto-detect Container App
    if ([string]::IsNullOrEmpty($script:ContainerAppName)) {
        $containerApps = az containerapp list --resource-group $ResourceGroup --query "[].name" -o tsv
        if ($containerApps) {
            $script:ContainerAppName = ($containerApps -split "`n")[0].Trim()
            Write-Info "Auto-detected Container App: $script:ContainerAppName"
        } else {
            Write-Error "No Container App found in resource group $ResourceGroup"
            exit 1
        }
    }
}

function Show-Usage {
    Write-Host "Usage: $($MyInvocation.MyCommand.Name) -ResourceGroup <resource_group> [-Location <location>]"
    Write-Host ""
    Write-Host "Arguments:"
    Write-Host "  -ResourceGroup           Azure Resource Group name for deployment"
    Write-Host "  -Location               Azure region for deployment (optional, defaults to eastus)"
    Write-Host "  -CosmosAccountName      Name of the Cosmos DB account (optional, defaults to cosmosmcpkit)"
    Write-Host "  -ContainerAppName       Name of the container app (optional, defaults to mcp-toolkit-app)"
    Write-Host ""
    exit 1
}

function Parse-Arguments {
    Write-Info "Using Azure Resource Group: $ResourceGroup"
    Write-Info "Using Location: $Location"
    Write-Info "Using Cosmos Account Name: $CosmosAccountName"
    Write-Info "Using Container App Name: $ContainerAppName"
}

function Create-Entra-App {
    Write-Info "Creating Entra App registration for Azure Cosmos DB MCP Toolkit: $ENTRA_APP_NAME"

    # Check if jq equivalent (ConvertFrom-Json) is available - it's built-in to PowerShell
    
    # Register the Entra App with app-role
    $appJson = az ad app create --display-name $ENTRA_APP_NAME --service-management-reference "4405e061-966a-4249-afdd-f7435f54a510" | ConvertFrom-Json
    $ENTRA_APP_CLIENT_ID = $appJson.appId
    $ENTRA_APP_OBJECT_ID = $appJson.id
    
    Write-Info "ENTRA_APP_CLIENT_ID=$ENTRA_APP_CLIENT_ID"
    Write-Info "ENTRA_APP_OBJECT_ID=$ENTRA_APP_OBJECT_ID"

    $GRAPH_BASE = "https://graph.microsoft.com/v1.0"
    $ENTRA_APP_URL = "$GRAPH_BASE/applications/$ENTRA_APP_OBJECT_ID"
    $ENTRA_APP_ROLE_ID = [guid]::NewGuid().ToString()

    # Set Application ID (audience) URI for the Entra App
    Write-Info "Setting Application ID URI..."
    try {
        # Use az ad app update instead of az rest for better compatibility
        az ad app update --id $ENTRA_APP_CLIENT_ID --identifier-uris "api://$ENTRA_APP_CLIENT_ID" | Out-Null
    }
    catch {
        Write-Warn "Failed to set Application ID URI, but continuing deployment..."
    }

    # Define the app-role in the Entra App
    Write-Info "Checking for existing app role: $ENTRA_APP_ROLE_VALUE"

    # Check if the role already exists
    $appDetails = az rest --method GET --url $ENTRA_APP_URL | ConvertFrom-Json
    $existingRole = $appDetails.appRoles | Where-Object { $_.value -eq $ENTRA_APP_ROLE_VALUE }

    if (-not $existingRole) {
        Write-Info "Role does not exist, adding app role: $ENTRA_APP_ROLE_VALUE"

        # Prepare the app-roles payload by fetching existing roles, appending a new one
        $existingRoles = $appDetails.appRoles
        $newRole = @{
            allowedMemberTypes = @("Application")
            description = $ENTRA_APP_ROLE_DESC
            displayName = $ENTRA_APP_ROLE_DISPLAY
            id = $ENTRA_APP_ROLE_ID
            isEnabled = $true
            value = $ENTRA_APP_ROLE_VALUE
            origin = "Application"
        }
        
        $updatedRoles = $existingRoles + $newRole
        $rolesPayload = @{ appRoles = $updatedRoles } | ConvertTo-Json -Depth 10

        # PATCH back the updated app-roles
        az rest --method PATCH --url $ENTRA_APP_URL --body $rolesPayload | Out-Null

        Write-Info "App role added successfully"
        $script:ENTRA_APP_ROLE_ID_BY_VALUE = $ENTRA_APP_ROLE_ID
    }
    else {
        Write-Info "App role '$ENTRA_APP_ROLE_VALUE' already exists, extracting role ID"
        $script:ENTRA_APP_ROLE_ID_BY_VALUE = $existingRole.id
    }

    # Print the app-roles to verify
    $appRoles = az rest --method GET --url $ENTRA_APP_URL --query appRoles | ConvertFrom-Json
    Write-Info "Roles in Entra App:"
    Write-Host ($appRoles | ConvertTo-Json)
    
    # Get the service principal object ID for the Entra App
    Write-Info "Getting Entra App Service Principal Object ID..."
    $ENTRA_APP_SP_OBJECT_ID = az ad sp list --filter "appId eq '$ENTRA_APP_CLIENT_ID'" --query "[0].id" -o tsv
    if (-not $ENTRA_APP_SP_OBJECT_ID -or $ENTRA_APP_SP_OBJECT_ID -eq "null") {
        Write-Info "Entra App Service Principal not found, creating one..."
        az ad sp create --id $ENTRA_APP_CLIENT_ID | Out-Null
        $ENTRA_APP_SP_OBJECT_ID = az ad sp list --filter "appId eq '$ENTRA_APP_CLIENT_ID'" --query "[0].id" -o tsv
    }
    Write-Info "Entra App Service Principal Object ID: $ENTRA_APP_SP_OBJECT_ID"

    # Export variables for use in other functions
    $script:ENTRA_APP_CLIENT_ID = $ENTRA_APP_CLIENT_ID
    $script:ENTRA_APP_OBJECT_ID = $ENTRA_APP_OBJECT_ID
    $script:ENTRA_APP_ROLE_VALUE = $ENTRA_APP_ROLE_VALUE
    $script:ENTRA_APP_SP_OBJECT_ID = $ENTRA_APP_SP_OBJECT_ID

    Write-Info "Entra App registration completed successfully!"
}

function Assign-Current-User-Role {
    Write-Info "Assigning Mcp.Tool.Executor role to current user..."
    
    # Get current user
    $currentUserEmail = az account show --query "user.name" -o tsv
    Write-Info "Current user: $currentUserEmail"
    
    # Get user object ID
    $userObjectId = az ad user show --id $currentUserEmail --query "id" -o tsv 2>$null
    
    if (-not $userObjectId -or $userObjectId -eq "null") {
        Write-Warn "Could not find user object ID for: $currentUserEmail"
        Write-Warn "You may need to manually assign the role in Azure Portal"
        return
    }
    
    Write-Info "User Object ID: $userObjectId"
    
    # Check if role assignment already exists
    $existingAssignment = az rest --method GET --url "https://graph.microsoft.com/v1.0/servicePrincipals/$($script:ENTRA_APP_SP_OBJECT_ID)/appRoleAssignedTo" --query "value[?principalId=='$userObjectId' && appRoleId=='$($script:ENTRA_APP_ROLE_ID_BY_VALUE)']" | ConvertFrom-Json
    
    if ($existingAssignment -and $existingAssignment.Count -gt 0) {
        Write-Info "User already has the Mcp.Tool.Executor role assigned"
        return
    }
    
    # Assign the role
    Write-Info "Assigning role to user..."
    
    $body = @{
        principalId = $userObjectId
        resourceId = $script:ENTRA_APP_SP_OBJECT_ID
        appRoleId = $script:ENTRA_APP_ROLE_ID_BY_VALUE
    } | ConvertTo-Json
    
    try {
        az rest --method POST --url "https://graph.microsoft.com/v1.0/servicePrincipals/$($script:ENTRA_APP_SP_OBJECT_ID)/appRoleAssignedTo" --headers "Content-Type=application/json" --body $body | Out-Null
        Write-Info "Successfully assigned Mcp.Tool.Executor role to $currentUserEmail"
        Write-Info "Note: Sign out and sign in again in the browser for the role to take effect"
    }
    catch {
        Write-Warn "Failed to assign role automatically: $_"
        Write-Warn "Please assign the Mcp.Tool.Executor role manually in Azure Portal"
    }
}

function Check-Prerequisites {
    Write-Info "Checking prerequisites (az-cli, docker)..."

    if (-not (Get-Command az -ErrorAction SilentlyContinue)) {
        Write-Error "Azure CLI is not installed. Please install it from https://docs.microsoft.com/en-us/cli/azure/install-azure-cli"
        exit 1
    }

    if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
        Write-Error "Docker is not installed. Please install Docker Desktop."
        exit 1
    }

    Write-Info "Prerequisites satisfied."
}

function Login-Azure {
    Write-Info "Checking az cli login status..."

    try {
        az account show | Out-Null
    }
    catch {
        Write-Info "Not logged in to az-cli. running 'az login'..."
        az login
    }

    if ($SUBSCRIPTION_ID) {
        Write-Info "Setting subscription to $SUBSCRIPTION_ID"
        az account set --subscription $SUBSCRIPTION_ID
    }

    Write-Info "az cli login successful!"
}

function Verify-Resource-Group {
    Write-Info "Verifying resource group exists: $ResourceGroup"
    
    $rgExists = az group exists --name $ResourceGroup
    if ($rgExists -eq "false") {
        Write-Error "Resource group '$ResourceGroup' does not exist. Please create it first or use an existing resource group."
        exit 1
    }
    
    Write-Info "Resource group verified successfully"
}

function Deploy-Infrastructure {
    Write-Info "Checking if Container App exists..."
    
    try {
        $existingApp = az containerapp show --name $ContainerAppName --resource-group $ResourceGroup 2>$null | ConvertFrom-Json
        if ($existingApp) {
            Write-Info "Container App already exists, skipping infrastructure deployment"
            $script:SKIP_INFRA = $true
            return
        }
    }
    catch {
        # Container app doesn't exist, need to deploy infrastructure
        $script:SKIP_INFRA = $false
    }

    Write-Info "Creating Azure Container resources..."
    Write-Info "Note: Initial deployment may show as 'Failed' - this is expected and will be fixed after ACR permissions are assigned"

    az deployment group create --resource-group $ResourceGroup --template-file "infrastructure/main.bicep" --output table

    Write-Info "Azure Container resources deployment completed!"
}

function Get-Deployment-Outputs {
    Write-Info "Getting deployment outputs..."

    # Get ACR and Container App details
    $acrName = az acr list --resource-group $ResourceGroup --query "[0].name" -o tsv
    $containerApp = az containerapp show --name $ContainerAppName --resource-group $ResourceGroup | ConvertFrom-Json
    
    $script:CONTAINER_REGISTRY = "$acrName.azurecr.io"
    $script:CONTAINER_APP_URL = "https://$($containerApp.properties.configuration.ingress.fqdn)"

    Write-Info "Container Registry: $script:CONTAINER_REGISTRY"
    Write-Info "Container App URL: $script:CONTAINER_APP_URL"
}

function Build-And-Push-Image {
    Write-Info "Building and pushing container image..."

    # Extract ACR name from login server
    $ACR_NAME = $script:CONTAINER_REGISTRY -replace '\.azurecr\.io$', ''
    Write-Info "Logging into ACR: $ACR_NAME"

    # Login to ACR
    az acr login --name $ACR_NAME

    # Build image
    $timestamp = Get-Date -Format "yyyyMMdd-HHmmss"
    $IMAGE_TAG = "$($script:CONTAINER_REGISTRY)/mcp-toolkit:$timestamp"

    # Ensure we're in the root directory
    $rootDir = Split-Path -Parent $SCRIPT_DIR
    Push-Location $rootDir
    
    try {
        Write-Info "Building .NET application from: $(Get-Location)"
        dotnet publish src/AzureCosmosDB.MCP.Toolkit/AzureCosmosDB.MCP.Toolkit.csproj -c Release -o src/AzureCosmosDB.MCP.Toolkit/bin/publish

        Write-Info "Building image: $IMAGE_TAG"
        docker build -t $IMAGE_TAG -f Dockerfile .

        Write-Info "Pushing image: $IMAGE_TAG"
        docker push $IMAGE_TAG

        $script:IMAGE_TAG = $IMAGE_TAG
        Write-Info "Image pushed successfully!"
    }
    finally {
        Pop-Location
    }
}

function Update-Container-App {
    Write-Info "Updating Azure Container App with MCP Toolkit image..."

    # Get current tenant ID
    $CURRENT_TENANT_ID = az account show --query "tenantId" --output tsv
    Write-Info "Current Tenant ID: $CURRENT_TENANT_ID"

    # Update container app with new image and authentication
    Write-Info "Updating container app with image: $script:IMAGE_TAG"
    az containerapp update --name $ContainerAppName --resource-group $ResourceGroup --image $script:IMAGE_TAG --set-env-vars "AzureAd__ClientId=$script:ENTRA_APP_CLIENT_ID" "AzureAd__TenantId=$CURRENT_TENANT_ID" "AzureAd__Audience=$script:ENTRA_APP_CLIENT_ID"

    $script:CURRENT_TENANT_ID = $CURRENT_TENANT_ID
    Write-Info "Azure Container App updated successfully!"
}

function Assign-ACR-Permissions {
    Write-Info "Verifying ACR permissions for Container App Managed Identity..."
    
    # Get Container App Managed Identity Principal ID (user-assigned identity)
    $identity = az containerapp show --resource-group $ResourceGroup --name $ContainerAppName --query "identity" | ConvertFrom-Json
    
    $ACA_MI_PRINCIPAL_ID = $null
    if ($identity.userAssignedIdentities) {
        # Get the first user-assigned identity's principal ID
        $identityKey = ($identity.userAssignedIdentities | Get-Member -MemberType NoteProperty)[0].Name
        $ACA_MI_PRINCIPAL_ID = $identity.userAssignedIdentities.$identityKey.principalId
    } elseif ($identity.principalId) {
        # Fallback to system-assigned identity
        $ACA_MI_PRINCIPAL_ID = $identity.principalId
    }
    
    if (-not $ACA_MI_PRINCIPAL_ID) {
        Write-Error "Failed to get Container App managed identity principal ID"
        exit 1
    }
    
    Write-Info "Container App MI Principal ID: $ACA_MI_PRINCIPAL_ID"
    
    # Verify ACR role assignment exists (should be created by Bicep)
    $acrName = az acr list --resource-group $ResourceGroup --query "[0].name" -o tsv
    $acrResourceId = "/subscriptions/$((az account show --query id -o tsv))/resourceGroups/$ResourceGroup/providers/Microsoft.ContainerRegistry/registries/$acrName"
    
    $roleCheck = az role assignment list --assignee $ACA_MI_PRINCIPAL_ID --scope $acrResourceId --role "AcrPull" --query "[0]" | ConvertFrom-Json
    if ($roleCheck) {
        Write-Info "ACR permissions verified - AcrPull role assignment exists"
    } else {
        Write-Warning "ACR role assignment not found - this should have been created by Bicep template"
        Write-Info "Creating ACR role assignment as fallback..."
        az role assignment create --assignee $ACA_MI_PRINCIPAL_ID --role "AcrPull" --scope $acrResourceId
        Write-Info "Waiting 30 seconds for role assignment to propagate..."
        Start-Sleep -Seconds 30
    }
}

function Configure-Entra-App-RedirectURIs {
    Write-Info "Configuring redirect URIs for Entra App as Single-Page Application..."
    
    # Extract FQDN from Container App URL
    $containerAppFqdn = $script:CONTAINER_APP_URL -replace '^https?://', ''
    
    $redirectUris = @(
        "https://$containerAppFqdn"
        "https://$containerAppFqdn/signin-oidc"
    )
    
    $ENTRA_APP_URL = "https://graph.microsoft.com/v1.0/applications/$($script:ENTRA_APP_OBJECT_ID)"
    
    # Create temporary file for JSON body
    $tempFile = [System.IO.Path]::GetTempFileName()
    
    # Configure as SPA (Single-Page Application) with proper token settings
    # This fixes the "Cross-origin token redemption" error and enables API access tokens
    $body = @{
        spa = @{
            redirectUris = $redirectUris
        }
        web = @{
            implicitGrantSettings = @{
                enableIdTokenIssuance = $true
                enableAccessTokenIssuance = $true
            }
        }
        # Enable the application to request access tokens (not just ID tokens)
        requiredResourceAccess = @(
            @{
                resourceAppId = "00000003-0000-0000-c000-000000000000"  # Microsoft Graph
                resourceAccess = @(
                    @{
                        id = "e1fe6dd8-ba31-4d61-89e7-88639da4683d"  # User.Read
                        type = "Scope"
                    }
                )
            }
        )
    } | ConvertTo-Json -Depth 10
    
    $body | Out-File -FilePath $tempFile -Encoding utf8 -NoNewline
    
    try {
        az rest --method PATCH --url $ENTRA_APP_URL --headers "Content-Type=application/json" --body "@$tempFile" | Out-Null
        Write-Info "Redirect URIs configured successfully as SPA:"
        foreach ($uri in $redirectUris) {
            Write-Info "  - $uri"
        }
        Write-Info "Access token issuance enabled for SPA authentication"
    }
    catch {
        Write-Warn "Failed to configure redirect URIs automatically."
        Write-Warn "Please add these redirect URIs manually in Azure Portal as SPA redirect URIs:"
        foreach ($uri in $redirectUris) {
            Write-Warn "  - $uri"
        }
    }
    finally {
        # Clean up temp file
        if (Test-Path $tempFile) {
            Remove-Item $tempFile -Force
        }
    }
}

function Assign-Cosmos-RBAC {
    Write-Info "Assigning Cosmos DB permissions to Container App Managed Identity..."

    Write-Info "Getting Container App Managed Identity Principal ID..."
    $ACA_MI_PRINCIPAL_ID = az containerapp show --resource-group $ResourceGroup --name $ContainerAppName --query "identity.principalId" --output tsv
    
    if (-not $ACA_MI_PRINCIPAL_ID -or $ACA_MI_PRINCIPAL_ID -eq "null") {
        Write-Error "Failed to get Container App Managed Identity Principal ID"
        Write-Error "Make sure the Container App has a system-assigned managed identity enabled"
        exit 1
    }
    
    $ACA_MI_DISPLAY_NAME = $ContainerAppName

    Write-Info "Container App MI Principal ID: $ACA_MI_PRINCIPAL_ID"
    
    # Assign Cosmos DB Data Reader role
    Write-Info "Assigning Cosmos DB Data Reader role..."
    $cosmosResourceId = "/subscriptions/$((az account show --query id -o tsv))/resourceGroups/$ResourceGroup/providers/Microsoft.DocumentDB/databaseAccounts/$CosmosAccountName"
    $roleDefinitionId = "00000000-0000-0000-0000-000000000001"

    $existingAssignment = az cosmosdb sql role assignment list --account-name $CosmosAccountName --resource-group $ResourceGroup --query "[?principalId=='$ACA_MI_PRINCIPAL_ID']" | ConvertFrom-Json

    if ($existingAssignment.Count -eq 0) {
        az cosmosdb sql role assignment create --account-name $CosmosAccountName --resource-group $ResourceGroup --role-definition-id $roleDefinitionId --principal-id $ACA_MI_PRINCIPAL_ID --scope $cosmosResourceId
        Write-Info "Successfully assigned Cosmos DB Data Reader role to Container App MI"
    } else {
        Write-Info "Cosmos DB Data Reader role assignment already exists"
    }
    
    # Export variables for use in deployment summary
    $script:ACA_MI_PRINCIPAL_ID = $ACA_MI_PRINCIPAL_ID
    $script:ACA_MI_DISPLAY_NAME = $ACA_MI_DISPLAY_NAME
}

function Show-Container-Logs {
    Write-Info "Waiting 10 seconds for Azure Container App to initialize then fetching logs..."
    Start-Sleep 10

    Write-Host ""
    Write-Info "Azure Container App logs (hosting 'Azure Cosmos DB MCP Toolkit'):"
    Write-Host "Begin_Azure_Container_App_Logs ---->"
    
    try {
        az containerapp logs show --name $ContainerAppName --resource-group $ResourceGroup --tail 50 --output table
        Write-Host "<---- End_Azure_Container_App_Logs"
        Write-Host ""
    }
    catch {
        Write-Warn "Could not retrieve logs. The Azure Container App might still be starting up, use the following command to check logs later."
        Write-Info "az containerapp logs show --name $ContainerAppName --resource-group $ResourceGroup --tail 50"
    }
}

function Test-MCP-Server-Health {
    Write-Info "Verifying MCP server deployment and health..."
    
    $maxRetries = 12  # 2 minutes total (10 seconds * 12)
    $retryDelay = 10
    
    for ($i = 1; $i -le $maxRetries; $i++) {
        Write-Info "Health check attempt $i of $maxRetries..."
        
        try {
            # Test basic connectivity
            $response = Invoke-WebRequest -Uri "$($script:CONTAINER_APP_URL)/" -UseBasicParsing -TimeoutSec 15
            Write-Info "[OK] MCP server is responding! Status: $($response.StatusCode)"
            
            # Test health endpoint if available
            try {
                $healthResponse = Invoke-WebRequest -Uri "$($script:CONTAINER_APP_URL)/health" -UseBasicParsing -TimeoutSec 10
                Write-Info "[OK] Health endpoint responding: $($healthResponse.StatusCode)"
            }
            catch {
                Write-Info "[WARN] Health endpoint not accessible, but main server is running"
            }
            
            # Test MCP protocol endpoint
            try {
                $mcpResponse = Invoke-WebRequest -Uri "$($script:CONTAINER_APP_URL)/mcp" -UseBasicParsing -TimeoutSec 10
                Write-Info "[OK] MCP protocol endpoint responding: $($mcpResponse.StatusCode)"
            }
            catch {
                Write-Info "[INFO] MCP endpoint returned: $($_.Exception.Message)"
            }
            
            Write-Info "[SUCCESS] MCP server verification completed successfully!"
            return $true
        }
        catch {
            Write-Info "[RETRY] Attempt $i failed: $($_.Exception.Message)"
            if ($i -eq $maxRetries) {
                Write-Error "[FAILED] MCP server failed to respond after $maxRetries attempts"
                Write-Error "This might indicate a configuration issue or the application needs more time to start"
                return $false
            }
            Write-Info "Waiting $retryDelay seconds before next attempt..."
            Start-Sleep -Seconds $retryDelay
        }
    }
}

function Verify-Container-App-Status {
    Write-Info "Checking Container App revision status..."
    
    # Check revision status
    $revision = az containerapp revision list --name $ContainerAppName --resource-group $ResourceGroup --query "[0]" | ConvertFrom-Json
    
    Write-Info "Revision Status:"
    Write-Info "  - Name: $($revision.name)"
    Write-Info "  - Provisioning: $($revision.properties.provisioningState)"
    Write-Info "  - Health: $($revision.properties.healthState)"
    Write-Info "  - Active: $($revision.properties.active)"
    Write-Info "  - Replicas: $($revision.properties.replicas)"
    
    if ($revision.properties.provisioningState -ne "Provisioned") {
        Write-Warning "[WARN] Container App revision is not fully provisioned: $($revision.properties.provisioningState)"
        
        # Try to restart if failed
        if ($revision.properties.provisioningState -eq "Failed") {
            Write-Info "Attempting to restart failed revision..."
            az containerapp revision restart --name $ContainerAppName --resource-group $ResourceGroup --revision $revision.name
            Write-Info "Waiting 30 seconds for restart to complete..."
            Start-Sleep -Seconds 30
        }
    }
    
    if ($revision.properties.healthState -eq "Unhealthy") {
        Write-Warning "[WARN] Container App health check is failing - this may be normal for MCP servers without health endpoints"
    }
    
    return $revision.properties.provisioningState -eq "Provisioned"
}

function Show-Deployment-Summary {
    Write-Info "Deployment Summary (JSON):"
    
    # Create JSON summary (following PostgreSQL pattern exactly)
    $SUMMARY = @{
        MCP_SERVER_URI = $script:CONTAINER_APP_URL
        ENTRA_APP_CLIENT_ID = $script:ENTRA_APP_CLIENT_ID
        ENTRA_APP_OBJECT_ID = $script:ENTRA_APP_OBJECT_ID
        ENTRA_APP_SP_OBJECT_ID = $script:ENTRA_APP_SP_OBJECT_ID
        ENTRA_APP_ROLE_VALUE = $script:ENTRA_APP_ROLE_VALUE
        ENTRA_APP_ROLE_ID_BY_VALUE = $script:ENTRA_APP_ROLE_ID_BY_VALUE
        ACA_MI_PRINCIPAL_ID = $script:ACA_MI_PRINCIPAL_ID
        ACA_MI_DISPLAY_NAME = $script:ACA_MI_DISPLAY_NAME
        RESOURCE_GROUP = $ResourceGroup
        SUBSCRIPTION_ID = (az account show --query id -o tsv)
        TENANT_ID = (az account show --query tenantId -o tsv)
        COSMOS_ACCOUNT_NAME = $CosmosAccountName
        LOCATION = $Location
    }
    
    $SUMMARY_JSON = $SUMMARY | ConvertTo-Json
    Write-Host $SUMMARY_JSON
    
    $DEPLOYMENT_INFO_FILE = "$SCRIPT_DIR/deployment-info.json"
    $SUMMARY_JSON | Out-File -FilePath $DEPLOYMENT_INFO_FILE -Encoding UTF8
    Write-Info "Deployment information written to: $DEPLOYMENT_INFO_FILE"
}

function Update-Frontend-Config {
    Write-Info "Updating frontend configuration with deployment URLs..."
    
    # Build path incrementally for compatibility
    $projectRoot = Split-Path -Parent $SCRIPT_DIR
    $srcPath = Join-Path $projectRoot "src"
    $projectPath = Join-Path $srcPath "AzureCosmosDB.MCP.Toolkit"
    $wwwrootPath = Join-Path $projectPath "wwwroot"
    $htmlPath = Join-Path $wwwrootPath "index.html"
    
    if (-not (Test-Path $htmlPath)) {
        Write-Warn "Frontend HTML file not found at: $htmlPath"
        return
    }
    
    try {
        $htmlContent = Get-Content $htmlPath -Raw
        
        # Update the serverUrl input default value
        $htmlContent = $htmlContent -replace 'value="https://[^"]*azurecontainerapps\.io"', "value=`"$($script:CONTAINER_APP_URL)`""
        
        # Save the updated HTML
        $htmlContent | Out-File -FilePath $htmlPath -Encoding UTF8 -NoNewline
        
        Write-Info "Updated frontend default Server URL to: $($script:CONTAINER_APP_URL)"
    }
    catch {
        Write-Warn "Failed to update frontend configuration: $_"
    }
}

# Main function (following PostgreSQL pattern)
function Main {
    param($Arguments)
    
    Write-Info "Starting Azure Container Apps deployment..."

    Parse-Arguments
    Check-Prerequisites
    Login-Azure
    Verify-Resource-Group
    Auto-Detect-Resources
    Create-Entra-App
    Assign-Current-User-Role
    Deploy-Infrastructure
    Get-Deployment-Outputs
    Build-And-Push-Image
    Update-Container-App
    Configure-Entra-App-RedirectURIs
    Update-Frontend-Config
    Assign-Cosmos-RBAC
    Show-Container-Logs

    Write-Info "Deployment completed!"
    
    # Verify deployment health
    Write-Info "`n" + "="*80
    Write-Info "DEPLOYMENT VERIFICATION"
    Write-Info "="*80
    
    $containerHealthy = Verify-Container-App-Status
    if (-not $containerHealthy) {
        Write-Warning "Container App verification had issues, but continuing with MCP server testing..."
    }
    
    $mcpHealthy = Test-MCP-Server-Health
    if (-not $mcpHealthy) {
        Write-Warning "MCP server health verification failed - please check the container logs for more details"
        $logCommand = "az containerapp logs show --name $ContainerAppName --resource-group $ResourceGroup --follow"
        Write-Info "You can check logs with: $logCommand"
    }
    
    Show-Deployment-Summary
    
    # Final instructions
    Write-Info "`n" + "="*80
    Write-Info "IMPORTANT: AUTHENTICATION SETUP"
    Write-Info "="*80
    Write-Info "The Mcp.Tool.Executor role has been assigned to your user."
    Write-Info ""
    Write-Info "To use the frontend, you MUST:"
    Write-Info "  1. Sign out completely in the browser if already logged in"
    Write-Info "  2. Clear browser cache or use incognito/private window"
    Write-Info "  3. Sign in again to get a fresh token with the role claim"
    Write-Info ""
    Write-Info "Access the MCP Toolkit at:"
    Write-Info "  $($script:CONTAINER_APP_URL)"
    Write-Info ""
    Write-Info "After signing in, check the 'Roles' field shows: Mcp.Tool.Executor"
    Write-Info "="*80
}

# Run main function
Main $args