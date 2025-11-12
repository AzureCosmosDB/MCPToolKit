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
.PARAMETER EntraAppName
    Name of the Entra App registration (default: "Azure Cosmos DB MCP Toolkit API")
    Use this to create a unique app if the default name is already taken
.EXAMPLE
    ./Deploy-Cosmos-MCP-Server.ps1 -ResourceGroup "my-cosmos-mcp-rg"
.EXAMPLE
    ./Deploy-Cosmos-MCP-Server.ps1 -ResourceGroup "my-project" -Location "westus2" -CosmosAccountName "mycosmosdb"
.EXAMPLE
    ./Deploy-Cosmos-MCP-Server.ps1 -ResourceGroup "my-rg" -EntraAppName "My Custom MCP App"
#>

param(
    [Parameter(Mandatory=$true)]
    [string]$ResourceGroup,
    
    [Parameter(Mandatory=$false)]
    [string]$Location = "eastus",
    
    [Parameter(Mandatory=$false)]
    [string]$CosmosAccountName = "",
    
    [Parameter(Mandatory=$false)]
    [string]$ContainerAppName = "",
    
    [Parameter(Mandatory=$false)]
    [string]$EntraAppName = ""
)

$ErrorActionPreference = "Stop"
$SCRIPT_DIR = Split-Path -Parent $MyInvocation.MyCommand.Path

# Entra App Configuration (following PostgreSQL pattern)
$DEFAULT_ENTRA_APP_NAME = "Azure Cosmos DB MCP Toolkit API"
$ENTRA_APP_ROLE_DESC = "Executor role for MCP Tool operations on Cosmos DB"
$ENTRA_APP_ROLE_DISPLAY = "MCP Tool Executor"
$ENTRA_APP_ROLE_VALUE = "Mcp.Tool.Executor"

# Use custom app name if provided, otherwise use default
if ([string]::IsNullOrWhiteSpace($EntraAppName)) {
    $ENTRA_APP_NAME = $DEFAULT_ENTRA_APP_NAME
}
else {
    $ENTRA_APP_NAME = $EntraAppName
}

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
    # Set script-level variables for use in all functions
    $script:RESOURCE_GROUP = $ResourceGroup
    $script:LOCATION = $Location
    $script:CosmosAccountName = $CosmosAccountName
    $script:ContainerAppName = $ContainerAppName
    
    Write-Info "Using Azure Resource Group: $ResourceGroup"
    Write-Info "Using Location: $Location"
    Write-Info "Using Cosmos Account Name: $CosmosAccountName"
    Write-Info "Using Container App Name: $ContainerAppName"
}

function Create-Entra-App {
    Write-Info "Checking for existing Entra App registration: $ENTRA_APP_NAME"

    # Get current user info for owner checks
    $currentUserEmail = az account show --query "user.name" -o tsv
    $currentUserObjectId = az ad user show --id $currentUserEmail --query "id" -o tsv 2>$null

    # Check if app already exists
    $existingApp = az ad app list --display-name $ENTRA_APP_NAME --query "[0]" | ConvertFrom-Json
    
    if ($existingApp -and $existingApp.appId) {
        Write-Info "Found existing Entra App with name: $ENTRA_APP_NAME"
        
        # Check if current user is an owner of the existing app
        $isOwner = $false
        if ($currentUserObjectId -and $currentUserObjectId -ne "null") {
            $owners = az ad app owner list --id $existingApp.appId --query "[].id" -o tsv 2>$null
            if ($owners -contains $currentUserObjectId) {
                $isOwner = $true
                Write-Info "Current user is an owner of the existing app"
            }
            else {
                Write-Warn "Current user is NOT an owner of the existing app"
                Write-Warn "You may not have permissions to modify this app or assign roles"
            }
        }
        
        # Always use existing app if found (but warn if not owner)
        $ENTRA_APP_CLIENT_ID = $existingApp.appId
        $ENTRA_APP_OBJECT_ID = $existingApp.id
        
        Write-Info "ENTRA_APP_CLIENT_ID=$ENTRA_APP_CLIENT_ID"
        Write-Info "ENTRA_APP_OBJECT_ID=$ENTRA_APP_OBJECT_ID"
        
        if (-not $isOwner) {
            Write-Warn "IMPORTANT: Since you're not an owner, you may need to:"
            Write-Warn "1. Ask the app owner to add you as an owner, OR"
            Write-Warn "2. Manually assign the Mcp.Tool.Executor role to yourself in Azure Portal, OR"
            Write-Warn "3. Use a different app name by setting -EntraAppName parameter"
        }
    }
    else {
        Write-Info "Creating new Entra App registration: $ENTRA_APP_NAME"
        
        # Try without service-management-reference first (works for most subscriptions)
        # Capture output and suppress PowerShell error handling temporarily
        $oldErrorActionPreference = $ErrorActionPreference
        $ErrorActionPreference = 'Continue'
        
        $appJson = (az ad app create --display-name $ENTRA_APP_NAME 2>&1) | Out-String
        $firstExitCode = $LASTEXITCODE
        
        $ErrorActionPreference = $oldErrorActionPreference
        
        # If it failed due to service-management-reference requirement, try to auto-detect
        if ($firstExitCode -ne 0) {
            if ($appJson -match "ServiceManagementReference") {
                Write-Warn "Subscription requires service-management-reference parameter"
                Write-Info "Attempting to auto-detect service-management-reference GUID from existing apps..."
                Write-Info "(This may take 10-20 seconds...)"
                
                # Query with a timeout to avoid hanging indefinitely
                # Use --top to limit the number of apps fetched from the API
                $job = Start-Job -ScriptBlock {
                    az ad app list --top 5 --query "[?serviceManagementReference != null] | [0].{name:displayName, smRef:serviceManagementReference}" 2>$null
                }
                
                # Wait for up to 30 seconds
                $completed = Wait-Job -Job $job -Timeout 30
                
                if ($completed) {
                    $result = Receive-Job -Job $job
                    Remove-Job -Job $job
                    
                    if ($result) {
                        $existingApps = $result | ConvertFrom-Json
                    }
                    else {
                        $existingApps = $null
                    }
                }
                else {
                    Write-Warn "Auto-detection timed out after 30 seconds"
                    Stop-Job -Job $job
                    Remove-Job -Job $job
                    $existingApps = $null
                }
                
                if ($existingApps -and $existingApps.Count -gt 0) {
                    $smRef = $existingApps[0].serviceManagementReference
                    Write-Info "Found service-management-reference from existing app '$($existingApps[0].name)': $smRef"
                    Write-Info "Attempting to create Entra App with detected GUID..."
                    
                    $appJson = az ad app create --display-name $ENTRA_APP_NAME --service-management-reference $smRef 2>&1
                    $secondExitCode = $LASTEXITCODE
                    
                    if ($secondExitCode -eq 0) {
                        Write-Info "Successfully created Entra App with auto-detected service-management-reference"
                    }
                    else {
                        Write-Error @"
Failed to create Entra App with auto-detected service-management-reference.

The detected GUID '$smRef' from existing app '$($existingApps[0].name)' didn't work.

MANUAL SOLUTION:
1. Find the correct service-management-reference GUID from your IT department
2. Create the app manually:
   az ad app create --display-name "$ENTRA_APP_NAME" --service-management-reference YOUR_SERVICE_GUID

3. Then re-run this script with:
   -EntraAppName "$ENTRA_APP_NAME"
"@
                        exit 1
                    }
                }
                else {
                    Write-Error @"
================================================================================
SUBSCRIPTION POLICY REQUIRES SERVICE-MANAGEMENT-REFERENCE
================================================================================

Your subscription requires the --service-management-reference parameter.
Auto-detection failed or timed out.

FASTEST SOLUTION - SKIP AUTO-DETECTION:

If you already created the Entra App manually, rerun with:
  -EntraAppName "Azure Cosmos DB MCP Toolkit API"

MANUAL CREATION OPTIONS:

1. CREATE WITH A KNOWN GUID:
   Ask your IT department for the service-management-reference GUID, then:
   
   az ad app create --display-name "Azure Cosmos DB MCP Toolkit API" \
     --service-management-reference YOUR_SERVICE_GUID
   
   Then re-run this script with: -EntraAppName "Azure Cosmos DB MCP Toolkit API"

2. FIND AN EXISTING APP'S GUID:
   Run: az ad app show --id <any-existing-app-id> --query serviceManagementReference
   Then use that GUID to create your app.

For more information: https://aka.ms/service-management-reference-error
================================================================================
"@
                    exit 1
                }
            }
            else {
                Write-Error "Failed to create Entra App: $appJson"
                exit 1
            }
        }
        
        # Parse the JSON response
        $appJson = $appJson | ConvertFrom-Json
        
        $ENTRA_APP_CLIENT_ID = $appJson.appId
        $ENTRA_APP_OBJECT_ID = $appJson.id
        
        if (-not $ENTRA_APP_CLIENT_ID -or -not $ENTRA_APP_OBJECT_ID) {
            Write-Error "Failed to create Entra App or retrieve app details"
            exit 1
        }
        
        Write-Info "ENTRA_APP_CLIENT_ID=$ENTRA_APP_CLIENT_ID"
        Write-Info "ENTRA_APP_OBJECT_ID=$ENTRA_APP_OBJECT_ID"
    }

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

        # Create a temporary file for the body to avoid issues with special characters
        $tempRolesFile = [System.IO.Path]::GetTempFileName()
        $rolesPayload | Out-File -FilePath $tempRolesFile -Encoding utf8 -NoNewline
        
        # PATCH back the updated app-roles
        az rest --method PATCH --url $ENTRA_APP_URL --headers "Content-Type=application/json" --body "@$tempRolesFile" | Out-Null
        
        # Clean up temp file
        Remove-Item $tempRolesFile -Force

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
    
    # Try to show the SP directly by appId (fastest method)
    # Suppress error output properly
    $ErrorActionPreference = 'SilentlyContinue'
    $ENTRA_APP_SP_OBJECT_ID = az ad sp show --id $ENTRA_APP_CLIENT_ID --query "id" -o tsv 2>&1 | Where-Object { $_ -notmatch "ERROR" }
    $ErrorActionPreference = 'Continue'
    
    if (-not $ENTRA_APP_SP_OBJECT_ID -or $ENTRA_APP_SP_OBJECT_ID -eq "null" -or $ENTRA_APP_SP_OBJECT_ID -eq "") {
        Write-Info "Service Principal not found, creating one..."
        
        $createResult = az ad sp create --id $ENTRA_APP_CLIENT_ID 2>&1
        if ($LASTEXITCODE -ne 0) {
            Write-Warn "Failed to create Service Principal, it may already exist"
        }
        
        Start-Sleep -Seconds 5  # Wait for SP to propagate
        $ENTRA_APP_SP_OBJECT_ID = az ad sp show --id $ENTRA_APP_CLIENT_ID --query "id" -o tsv 2>&1 | Where-Object { $_ -notmatch "ERROR" }
    }
    
    if (-not $ENTRA_APP_SP_OBJECT_ID -or $ENTRA_APP_SP_OBJECT_ID -eq "null" -or $ENTRA_APP_SP_OBJECT_ID -eq "") {
        Write-Error "Failed to get or create Service Principal for Entra App"
        exit 1
    }
    
    Write-Info "Entra App Service Principal Object ID: $ENTRA_APP_SP_OBJECT_ID"

    # Export variables for use in other functions
    $script:ENTRA_APP_CLIENT_ID = $ENTRA_APP_CLIENT_ID
    $script:ENTRA_APP_OBJECT_ID = $ENTRA_APP_OBJECT_ID
    $script:ENTRA_APP_ROLE_VALUE = $ENTRA_APP_ROLE_VALUE
    $script:ENTRA_APP_SP_OBJECT_ID = $ENTRA_APP_SP_OBJECT_ID

    # Ensure current user is an owner of the app
    Write-Info "Ensuring current user is an owner of the Entra App..."
    try {
        $currentUserEmail = az account show --query "user.name" -o tsv
        $currentUserObjectId = az ad user show --id $currentUserEmail --query "id" -o tsv 2>$null
        
        if ($currentUserObjectId -and $currentUserObjectId -ne "null") {
            # Check if user is already an owner
            $owners = az ad app owner list --id $ENTRA_APP_CLIENT_ID --query "[].id" -o tsv 2>$null
            
            if ($owners -notcontains $currentUserObjectId) {
                Write-Info "Adding current user as owner of the Entra App..."
                az ad app owner add --id $ENTRA_APP_CLIENT_ID --owner-object-id $currentUserObjectId 2>$null
                Write-Info "User added as owner successfully"
            }
            else {
                Write-Info "Current user is already an owner of the Entra App"
            }
        }
    }
    catch {
        Write-Warn "Could not ensure user is owner of Entra App: $_"
        Write-Warn "This may affect automatic role assignment"
    }

    Write-Info "Entra App registration completed successfully!"
}

function Assign-Current-User-Role {
    Write-Info "Assigning Mcp.Tool.Executor role to current user..."
    
    # Get current user
    $currentUserEmail = az account show --query "user.name" -o tsv
    Write-Info "Current user: $currentUserEmail"
    
    # Get user object ID - try standard method first
    $userObjectId = az ad user show --id $currentUserEmail --query "id" -o tsv 2>$null
    
    if (-not $userObjectId -or $userObjectId -eq "null" -or $userObjectId -eq "") {
        Write-Info "Standard user lookup failed, trying Graph API /me endpoint..."
        Write-Info "(This is common for Visual Studio subscriptions, personal accounts, or guest users)"
        
        # Fallback: Use Graph API /me endpoint - works for all account types
        try {
            $meResult = az rest --method GET --url "https://graph.microsoft.com/v1.0/me" 2>&1
            
            if ($LASTEXITCODE -eq 0 -and $meResult) {
                $meData = $meResult | ConvertFrom-Json
                $userObjectId = $meData.id
                $userDisplayName = $meData.displayName
                $userUPN = $meData.userPrincipalName
                
                Write-Info "Found user via Graph API:"
                Write-Info "  Display Name: $userDisplayName"
                Write-Info "  UPN: $userUPN"
                Write-Info "  Object ID: $userObjectId"
            }
            else {
                throw "Graph API /me endpoint failed"
            }
        }
        catch {
            Write-Warn "Could not find user object ID using any method"
            Write-Warn ""
            Write-Warn "This can happen with:"
            Write-Warn "  - Visual Studio subscriptions with Microsoft Accounts"
            Write-Warn "  - Personal Azure subscriptions"
            Write-Warn "  - Limited directory permissions"
            Write-Warn ""
            Write-Warn "MANUAL ROLE ASSIGNMENT REQUIRED:"
            Write-Warn "Run this command to get your Object ID:"
            Write-Warn "  az rest --method GET --url `"https://graph.microsoft.com/v1.0/me`" --query id -o tsv"
            Write-Warn ""
            Write-Warn "Then assign the role manually or see the troubleshooting guide:"
            Write-Warn "  docs/TROUBLESHOOTING-DEPLOYMENT.md"
            return
        }
    }
    else {
        Write-Info "User Object ID: $userObjectId"
    }
    
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
        # Create a temporary file for the body to avoid shell escaping issues
        $tempBodyFile = [System.IO.Path]::GetTempFileName()
        $body | Out-File -FilePath $tempBodyFile -Encoding utf8 -NoNewline
        
        $output = az rest --method POST --url "https://graph.microsoft.com/v1.0/servicePrincipals/$($script:ENTRA_APP_SP_OBJECT_ID)/appRoleAssignedTo" --headers "Content-Type=application/json" --body "@$tempBodyFile" 2>&1
        
        # Clean up temp file
        Remove-Item $tempBodyFile -Force
        
        # Check if the command succeeded
        if ($LASTEXITCODE -eq 0) {
            Write-Info "Successfully assigned Mcp.Tool.Executor role to $currentUserEmail"
            Write-Info "Note: Sign out and sign in again in the browser for the role to take effect"
        }
        else {
            # Check if it's a permissions error
            if ($output -match "Authorization_RequestDenied|Insufficient privileges") {
                Write-Warn "Insufficient permissions to assign the Entra App role automatically."
                Write-Warn ""
                Write-Warn "REQUIRED ACTION:"
                Write-Warn "1. Ask an Azure AD administrator or application owner to assign you the role"
                Write-Warn "2. They can use this command:"
                Write-Warn "   az ad app permission grant --id $($script:ENTRA_APP_CLIENT_ID) --api 00000003-0000-0000-c000-000000000000 --scope AppRoleAssignment.ReadWrite.All"
                Write-Warn ""
                Write-Warn "OR manually assign the role in Azure Portal:"
                Write-Warn "1. Go to Azure Portal > Enterprise Applications"
                Write-Warn "2. Search for app: $($script:ENTRA_APP_NAME)"
                Write-Warn "3. Go to 'Users and groups'"
                Write-Warn "4. Click 'Add user/group'"
                Write-Warn "5. Select your user ($currentUserEmail) and assign the 'Mcp.Tool.Executor' role"
                Write-Warn ""
                Write-Warn "Deployment will continue, but you won't be able to use the web UI until the role is assigned."
            }
            else {
                throw "Azure CLI command failed: $output"
            }
        }
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

    try {
        # Login to ACR - specify resource group to avoid auto-discovery issues
        az acr login --name $ACR_NAME --resource-group $script:RESOURCE_GROUP
        
        if ($LASTEXITCODE -ne 0) {
            throw "ACR login failed with exit code $LASTEXITCODE"
        }

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
            
            if ($LASTEXITCODE -ne 0) {
                throw "Docker build failed with exit code $LASTEXITCODE"
            }

            Write-Info "Pushing image: $IMAGE_TAG"
            docker push $IMAGE_TAG
            
            if ($LASTEXITCODE -ne 0) {
                throw "Docker push failed with exit code $LASTEXITCODE"
            }

            $script:IMAGE_TAG = $IMAGE_TAG
            Write-Info "Image pushed successfully!"
        }
        finally {
            Pop-Location
        }
    }
    catch {
        Write-Warn "Failed to build or push container image: $_"
        Write-Warn ""
        Write-Warn "TROUBLESHOOTING:"
        Write-Warn "1. Check network connectivity to ACR: az acr check-health -n $ACR_NAME --yes"
        Write-Warn "2. Verify Docker is running: docker ps"
        Write-Warn "3. If behind a proxy, configure Docker proxy settings"
        Write-Warn ""
        Write-Warn "Deployment will continue without updating the container image."
        Write-Warn "The Container App will keep using its existing image."
        Write-Warn ""
        $script:IMAGE_TAG = $null
    }
}

function Update-Container-App {
    Write-Info "Updating Azure Container App with MCP Toolkit image..."

    # Get current tenant ID
    $CURRENT_TENANT_ID = az account show --query "tenantId" --output tsv
    Write-Info "Current Tenant ID: $CURRENT_TENANT_ID"

    # Get Cosmos DB endpoint
    $cosmosEndpoint = az cosmosdb show --name $CosmosAccountName --resource-group $ResourceGroup --query "documentEndpoint" --output tsv
    Write-Info "Cosmos DB Endpoint: $cosmosEndpoint"
    
    # Get Container App to extract existing environment variables
    $containerApp = az containerapp show --name $ContainerAppName --resource-group $ResourceGroup | ConvertFrom-Json
    
    # Enable system-assigned managed identity if not already enabled
    $identityJustCreated = $false
    if ($containerApp.identity.type -ne "SystemAssigned") {
        Write-Info "Enabling SystemAssigned managed identity on Container App..."
        az containerapp identity assign --name $ContainerAppName --resource-group $ResourceGroup --system-assigned
        Write-Info "SystemAssigned managed identity enabled successfully"
        
        # Wait for the identity to propagate
        Write-Info "Waiting 15 seconds for identity to propagate..."
        Start-Sleep -Seconds 15
        
        # Refresh container app info
        $containerApp = az containerapp show --name $ContainerAppName --resource-group $ResourceGroup | ConvertFrom-Json
        $identityJustCreated = $true
    } else {
        Write-Info "Container App is already using SystemAssigned managed identity"
    }
    
    # Get existing environment variables to extract AI Foundry and embedding settings
    $existingEnvVars = $containerApp.properties.template.containers[0].env
    $aifProjectEndpoint = ($existingEnvVars | Where-Object { $_.name -eq "OPENAI_ENDPOINT" }).value
    $embeddingDeployment = ($existingEnvVars | Where-Object { $_.name -eq "OPENAI_EMBEDDING_DEPLOYMENT" }).value
    
    if (-not $aifProjectEndpoint) {
        Write-Warn "OPENAI_ENDPOINT not found in existing container app configuration"
        Write-Warn "Please set this manually using: az containerapp update --name $ContainerAppName --resource-group $ResourceGroup --set-env-vars 'OPENAI_ENDPOINT=<your-endpoint>'"
    } else {
        Write-Info "AI Foundry Endpoint: $aifProjectEndpoint"
    }
    
    if (-not $embeddingDeployment) {
        Write-Warn "OPENAI_EMBEDDING_DEPLOYMENT not found in existing container app configuration"
        Write-Warn "Please set this manually using: az containerapp update --name $ContainerAppName --resource-group $ResourceGroup --set-env-vars 'OPENAI_EMBEDDING_DEPLOYMENT=<your-deployment>'"
    } else {
        Write-Info "Embedding Deployment: $embeddingDeployment"
    }

    # Build environment variables list (no AZURE_CLIENT_ID needed for system-assigned identity)
    $envVars = @(
        "AzureAd__ClientId=$script:ENTRA_APP_CLIENT_ID"
        "AzureAd__TenantId=$CURRENT_TENANT_ID"
        "AzureAd__Audience=$script:ENTRA_APP_CLIENT_ID"
        "COSMOS_ENDPOINT=$cosmosEndpoint"
        "ASPNETCORE_ENVIRONMENT=Production"
        "ASPNETCORE_URLS=http://+:8080"
    )
    
    if ($aifProjectEndpoint) {
        $envVars += "OPENAI_ENDPOINT=$aifProjectEndpoint"
    }
    
    if ($embeddingDeployment) {
        $envVars += "OPENAI_EMBEDDING_DEPLOYMENT=$embeddingDeployment"
    }

    # First, ensure ingress is configured correctly for port 8080
    Write-Info "Configuring ingress to use target port 8080..."
    try {
        az containerapp ingress update --name $ContainerAppName --resource-group $ResourceGroup --target-port 8080 | Out-Null
        Write-Info "Ingress updated successfully"
    }
    catch {
        Write-Warn "Failed to update ingress configuration: $_"
    }
    
    # Configure CORS for the Container App
    Write-Info "Configuring CORS to allow all origins..."
    
    # First check if CORS is already configured
    $existingCors = az containerapp ingress cors show --name $ContainerAppName --resource-group $ResourceGroup 2>$null | ConvertFrom-Json
    
    if ($existingCors -and $existingCors.allowedOrigins -contains "*") {
        Write-Info "CORS already configured with allowed origins: $($existingCors.allowedOrigins -join ', ')"
    }
    else {
        try {
            # Wait a moment for the container app to be ready
            Start-Sleep -Seconds 2
            
            $ErrorActionPreference = "Continue"
            az containerapp ingress cors enable --name $ContainerAppName --resource-group $ResourceGroup --allowed-origins "*" --allowed-methods "GET,POST,PUT,DELETE,OPTIONS" --allowed-headers "*" --expose-headers "*" --max-age 3600 --output none 2>&1 | Out-Null
            $ErrorActionPreference = "Stop"
            
            # Verify CORS was configured by checking again
            Start-Sleep -Seconds 1
            $corsConfig = az containerapp ingress cors show --name $ContainerAppName --resource-group $ResourceGroup 2>$null | ConvertFrom-Json
            
            if ($corsConfig -and $corsConfig.allowedOrigins) {
                Write-Info "CORS configured successfully"
                Write-Info "Allowed origins: $($corsConfig.allowedOrigins -join ', ')"
            }
            else {
                Write-Warn "Could not verify CORS configuration. Please check manually in Azure Portal"
                Write-Warn "Run: az containerapp ingress cors show --name $ContainerAppName --resource-group $ResourceGroup"
            }
        }
        catch {
            Write-Warn "Exception during CORS configuration: $_"
            # Check if CORS was configured despite the error
            $corsConfig = az containerapp ingress cors show --name $ContainerAppName --resource-group $ResourceGroup 2>$null | ConvertFrom-Json
            if ($corsConfig -and $corsConfig.allowedOrigins) {
                Write-Info "CORS was configured successfully despite warning"
                Write-Info "Allowed origins: $($corsConfig.allowedOrigins -join ', ')"
            }
            else {
                Write-Warn "You may need to configure CORS manually in Azure Portal"
            }
        }
    }
    
    # Get ACR credentials and configure registry
    Write-Info "Configuring ACR credentials for container app..."
    $acrName = az acr list --resource-group $ResourceGroup --query "[0].name" -o tsv
    $acrLoginServer = az acr show --name $acrName --resource-group $ResourceGroup --query "loginServer" -o tsv
    $acrUsername = az acr credential show --name $acrName --resource-group $ResourceGroup --query "username" -o tsv
    $acrPassword = az acr credential show --name $acrName --resource-group $ResourceGroup --query "passwords[0].value" -o tsv
    
    Write-Info "ACR Login Server: $acrLoginServer"
    Write-Info "ACR Username: $acrUsername"
    
    # Set ACR credentials on the container app
    Write-Info "Setting ACR registry credentials..."
    try {
        az containerapp registry set --name $ContainerAppName --resource-group $ResourceGroup --server $acrLoginServer --username $acrUsername --password $acrPassword --output none
        Write-Info "ACR credentials configured successfully"
    }
    catch {
        Write-Warn "Failed to set ACR credentials: $_"
    }
    
    # Only update image if a new one was built successfully
    if ($script:IMAGE_TAG) {
        Write-Info "Updating container app with new image: $script:IMAGE_TAG"
        
        try {
            az containerapp update --name $ContainerAppName --resource-group $ResourceGroup --image $script:IMAGE_TAG --set-env-vars $envVars --output none
            
            if ($LASTEXITCODE -ne 0) {
                throw "Container app update failed with exit code $LASTEXITCODE"
            }
            
            Write-Info "Container app updated successfully with new image!"
        }
        catch {
            $errorMessage = $_.Exception.Message
            Write-Error "Container app update failed: $errorMessage"
            Write-Error "Check the container app logs for more details:"
            Write-Info "az containerapp logs show --name $ContainerAppName --resource-group $ResourceGroup --follow"
            exit 1
        }
    }
    else {
        Write-Warn "Skipping image update (no new image was built)"
        Write-Info "Updating only environment variables..."
        
        try {
            az containerapp update --name $ContainerAppName --resource-group $ResourceGroup --set-env-vars $envVars --output none
            
            if ($LASTEXITCODE -ne 0) {
                throw "Container app update failed with exit code $LASTEXITCODE"
            }
            
            Write-Info "Container app environment variables updated successfully!"
            Write-Info "Note: Container app is still using its existing image"
        }
        catch {
            $errorMessage = $_.Exception.Message
            Write-Warn "Failed to update environment variables: $errorMessage"
            Write-Warn "Continuing with deployment..."
        }
    }

    $script:CURRENT_TENANT_ID = $CURRENT_TENANT_ID
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

function Assign-AI-Foundry-RBAC {
    Write-Info "Assigning AI Foundry / Azure OpenAI permissions to Container App Managed Identity..."

    # Get Container App to extract OpenAI endpoint
    $containerApp = az containerapp show --name $ContainerAppName --resource-group $ResourceGroup | ConvertFrom-Json
    $existingEnvVars = $containerApp.properties.template.containers[0].env
    $aifProjectEndpoint = ($existingEnvVars | Where-Object { $_.name -eq "OPENAI_ENDPOINT" }).value
    
    if (-not $aifProjectEndpoint) {
        Write-Warn "OPENAI_ENDPOINT not configured. Skipping AI Foundry RBAC assignment."
        return
    }
    
    Write-Info "AI Foundry Endpoint: $aifProjectEndpoint"
    
    # Search for Cognitive Services accounts in the resource group
    Write-Info "Searching for Cognitive Services / AI Foundry resources in resource group..."
    $cognitiveAccounts = az cognitiveservices account list --resource-group $ResourceGroup | ConvertFrom-Json
    
    if (-not $cognitiveAccounts -or $cognitiveAccounts.Count -eq 0) {
        Write-Warn "No Cognitive Services accounts found in resource group: $ResourceGroup"
        Write-Warn "Please manually assign 'Cognitive Services OpenAI User' role to managed identity:"
        Write-Warn "  Principal ID: $($script:ACA_MI_PRINCIPAL_ID)"
        return
    }
    
    # If it's an AI Foundry endpoint (services.ai.azure.com), try to find the connected account
    $matchingAccount = $null
    
    if ($aifProjectEndpoint -match "\.services\.ai\.azure\.com") {
        Write-Info "Detected AI Foundry project endpoint format"
        
        # For AI Foundry, we typically want OpenAI accounts in the same resource group
        # Prefer accounts with "openai" in the endpoint or kind
        foreach ($account in $cognitiveAccounts) {
            if ($account.kind -eq "OpenAI" -or $account.properties.endpoint -match "openai\.azure\.com") {
                $matchingAccount = $account
                Write-Info "Found OpenAI account for AI Foundry project: $($account.name)"
                break
            }
        }
        
        # If no OpenAI account found, use the first Cognitive Services account
        if (-not $matchingAccount -and $cognitiveAccounts.Count -gt 0) {
            $matchingAccount = $cognitiveAccounts[0]
            Write-Info "Using Cognitive Services account: $($matchingAccount.name)"
        }
    }
    else {
        # Direct endpoint match for classic Azure OpenAI
        $endpointHost = ([System.Uri]$aifProjectEndpoint).Host
        foreach ($account in $cognitiveAccounts) {
            $accountEndpoint = $account.properties.endpoint
            if ($accountEndpoint -and ($accountEndpoint.Contains($endpointHost) -or $endpointHost.Contains($account.name))) {
                $matchingAccount = $account
                break
            }
        }
    }
    
    if (-not $matchingAccount) {
        Write-Warn "Could not automatically determine which Cognitive Services account to use"
        Write-Warn "Found these accounts in resource group:"
        foreach ($account in $cognitiveAccounts) {
            Write-Warn "  - $($account.name): $($account.properties.endpoint) (Kind: $($account.kind))"
        }
        Write-Warn ""
        Write-Warn "Attempting to assign role to all OpenAI accounts in the resource group..."
        
        # Try to assign to all OpenAI accounts
        $assigned = $false
        foreach ($account in $cognitiveAccounts) {
            if ($account.kind -eq "OpenAI") {
                Write-Info "Assigning role to OpenAI account: $($account.name)"
                $existingRoleAssignment = az role assignment list --assignee $script:ACA_MI_PRINCIPAL_ID --scope $account.id --query "[?roleDefinitionName=='Cognitive Services OpenAI User'].id" -o tsv
                
                if (-not $existingRoleAssignment) {
                    az role assignment create --role "Cognitive Services OpenAI User" --assignee-object-id $script:ACA_MI_PRINCIPAL_ID --assignee-principal-type ServicePrincipal --scope $account.id
                    Write-Info "Successfully assigned role to $($account.name)"
                    $assigned = $true
                }
                else {
                    Write-Info "Role already assigned to $($account.name)"
                    $assigned = $true
                }
            }
        }
        
        if (-not $assigned) {
            Write-Warn "No OpenAI accounts found. Please manually assign the role."
        }
        return
    }
    
    $resourceId = $matchingAccount.id
    $resourceName = $matchingAccount.name
    Write-Info "Target Cognitive Services account: $resourceName"
    
    # Check if role assignment already exists
    $existingRoleAssignment = az role assignment list --assignee $script:ACA_MI_PRINCIPAL_ID --scope $resourceId --query "[?roleDefinitionName=='Cognitive Services OpenAI User'].id" -o tsv
    
    if ($existingRoleAssignment) {
        Write-Info "'Cognitive Services OpenAI User' role already assigned to Container App MI"
    } else {
        Write-Info "Assigning 'Cognitive Services OpenAI User' role..."
        az role assignment create --role "Cognitive Services OpenAI User" --assignee-object-id $script:ACA_MI_PRINCIPAL_ID --assignee-principal-type ServicePrincipal --scope $resourceId
        Write-Info "Successfully assigned 'Cognitive Services OpenAI User' role to Container App MI"
    }
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
    Write-Info "Note: Initial container startup can take 1-3 minutes..."
    
    # First check if the revision is provisioned
    Write-Info "Checking container app revision status..."
    $revision = az containerapp revision list --name $ContainerAppName --resource-group $ResourceGroup --query "[0]" | ConvertFrom-Json
    if ($revision.properties.provisioningState -ne "Provisioned") {
        Write-Warn "Container revision is not yet provisioned. Current state: $($revision.properties.provisioningState)"
        Write-Info "Waiting 30 seconds for revision to provision..."
        Start-Sleep -Seconds 30
    }
    
    $maxRetries = 18  # 3 minutes total (10 seconds * 18)
    $retryDelay = 10
    
    for ($i = 1; $i -le $maxRetries; $i++) {
        Write-Info "Health check attempt $i of $maxRetries..."
        
        try {
            # Test basic connectivity with longer timeout
            $response = Invoke-WebRequest -Uri "$($script:CONTAINER_APP_URL)/" -UseBasicParsing -TimeoutSec 30
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
    Update-Frontend-Config  # Must run BEFORE Build-And-Push-Image so HTML is updated before build
    Build-And-Push-Image
    Update-Container-App
    Configure-Entra-App-RedirectURIs
    Assign-Cosmos-RBAC
    Assign-AI-Foundry-RBAC
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