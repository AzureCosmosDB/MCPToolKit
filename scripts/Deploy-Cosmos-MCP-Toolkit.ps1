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
    6. Creates deployment-info.json for Microsoft Foundry integration
.PARAMETER ResourceGroup
    Azure Resource Group name for deployment (REQUIRED)
.PARAMETER Location
    Azure region for deployment (default: eastus)
.PARAMETER CosmosAccountName
    Name of the Cosmos DB account (default: cosmosmcpkit)
.PARAMETER CosmosResourceGroup
    Resource group containing the Cosmos DB account (default: same as ResourceGroup)
.PARAMETER AcrResourceGroup
    Resource group containing Azure Container Registry (default: same as ResourceGroup)
.PARAMETER AcrName
    Existing Azure Container Registry name to use (optional)
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
.EXAMPLE
    ./Deploy-Cosmos-MCP-Server.ps1 -ResourceGroup "aca-rg" -CosmosResourceGroup "cosmos-rg" -AcrResourceGroup "acr-rg" -AcrName "mysharedacr"
#>

param(
    [Parameter(Mandatory=$true)]
    [string]$ResourceGroup,
    
    [Parameter(Mandatory=$false)]
    [string]$Location = "eastus",
    
    [Parameter(Mandatory=$false)]
    [string]$CosmosAccountName = "",

    [Parameter(Mandatory=$false)]
    [string]$CosmosResourceGroup = "",

    [Parameter(Mandatory=$false)]
    [string]$AcrResourceGroup = "",

    [Parameter(Mandatory=$false)]
    [string]$AcrName = "",
    
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
    
    # Auto-detect Cosmos DB account
    if ([string]::IsNullOrEmpty($script:CosmosAccountName)) {
        $cosmosAccounts = az cosmosdb list --resource-group $script:COSMOS_RESOURCE_GROUP --query "[].name" -o tsv
        if ($cosmosAccounts) {
            $script:CosmosAccountName = ($cosmosAccounts -split "`n")[0].Trim()
            Write-Info "Auto-detected Cosmos DB account: $script:CosmosAccountName"
        } else {
            Write-Error "No Cosmos DB account found in resource group $($script:COSMOS_RESOURCE_GROUP)"
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

    # Auto-detect ACR only when using an external/different resource group and AcrName is not provided
    if ([string]::IsNullOrEmpty($script:ACR_NAME) -and $script:USE_EXISTING_ACR) {
        $registries = az acr list --resource-group $script:ACR_RESOURCE_GROUP --query "[].name" -o tsv
        if ($registries) {
            $script:ACR_NAME = ($registries -split "`n")[0].Trim()
            Write-Info "Auto-detected ACR: $($script:ACR_NAME)"
        }
        else {
            Write-Error "No ACR registry found in resource group $($script:ACR_RESOURCE_GROUP). Provide -AcrName explicitly."
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
    Write-Host "  -CosmosResourceGroup    Resource group for Cosmos DB account (optional, defaults to ResourceGroup)"
    Write-Host "  -AcrResourceGroup       Resource group for ACR (optional, defaults to ResourceGroup)"
    Write-Host "  -AcrName                Existing ACR name to use (optional)"
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
    $script:COSMOS_RESOURCE_GROUP = if ([string]::IsNullOrWhiteSpace($CosmosResourceGroup)) { $ResourceGroup } else { $CosmosResourceGroup }
    $script:ACR_RESOURCE_GROUP = if ([string]::IsNullOrWhiteSpace($AcrResourceGroup)) { $ResourceGroup } else { $AcrResourceGroup }
    $script:ACR_NAME = $AcrName
    $script:USE_EXISTING_ACR = ($script:ACR_RESOURCE_GROUP -ne $ResourceGroup) -or (-not [string]::IsNullOrWhiteSpace($script:ACR_NAME))
    
    Write-Info "Resource Group: $ResourceGroup | Location: $Location | Cosmos RG: $($script:COSMOS_RESOURCE_GROUP)"
}

function Create-Entra-App {
    Write-Info "Configuring Entra App: $ENTRA_APP_NAME"

    # Check if app already exists
    $existingApp = az ad app list --display-name $ENTRA_APP_NAME --query "[0]" | ConvertFrom-Json
    
    if ($existingApp -and $existingApp.appId) {
        $ENTRA_APP_CLIENT_ID = $existingApp.appId
        $ENTRA_APP_OBJECT_ID = $existingApp.id
        Write-Info "Using existing app: ClientID=$ENTRA_APP_CLIENT_ID"
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
        
        Write-Info "Created new app: ClientID=$ENTRA_APP_CLIENT_ID"
    }

    $GRAPH_BASE = "https://graph.microsoft.com/v1.0"
    $ENTRA_APP_URL = "$GRAPH_BASE/applications/$ENTRA_APP_OBJECT_ID"
    $ENTRA_APP_ROLE_ID = [guid]::NewGuid().ToString()

    # Set Application ID (audience) URI
    try {
        az ad app update --id $ENTRA_APP_CLIENT_ID --identifier-uris "api://$ENTRA_APP_CLIENT_ID" | Out-Null
    }
    catch {
        Write-Warn "Failed to set Application ID URI, but continuing deployment..."
    }

    # Add OAuth2 permission scope and pre-authorize Azure CLI
    try {
        $appDetails = az rest --method GET --url $ENTRA_APP_URL | ConvertFrom-Json
        $existingScopes = $appDetails.api.oauth2PermissionScopes
        $hasAccessScope = $existingScopes | Where-Object { $_.value -eq "access_as_user" }

        if (-not $hasAccessScope) {
            Write-Info "Adding 'access_as_user' OAuth2 permission scope..."
            $scopeId = [guid]::NewGuid().ToString()
            $scopePayload = @{
                api = @{
                    oauth2PermissionScopes = @(
                        @{
                            adminConsentDescription = "Allow the application to access the Cosmos DB MCP Toolkit API on behalf of the signed-in user."
                            adminConsentDisplayName = "Access Cosmos DB MCP Toolkit API"
                            id = $scopeId
                            isEnabled = $true
                            type = "User"
                            userConsentDescription = "Allow the application to access the Cosmos DB MCP Toolkit API on your behalf."
                            userConsentDisplayName = "Access Cosmos DB MCP Toolkit API"
                            value = "access_as_user"
                        }
                    )
                }
            } | ConvertTo-Json -Depth 10

            $tempScopeFile = [System.IO.Path]::GetTempFileName()
            $scopePayload | Out-File -FilePath $tempScopeFile -Encoding utf8 -NoNewline
            az rest --method PATCH --url $ENTRA_APP_URL --headers "Content-Type=application/json" --body "@$tempScopeFile" | Out-Null
            Remove-Item $tempScopeFile -Force
        } else {
            $scopeId = $hasAccessScope.id
        }

        # Pre-authorize Azure CLI (04b07795-8ddb-461a-bbee-02f9e1bf7b46) for the scope
        $azureCliAppId = "04b07795-8ddb-461a-bbee-02f9e1bf7b46"

        $refreshedApp = az rest --method GET --url $ENTRA_APP_URL | ConvertFrom-Json
        $existingPreAuth = $refreshedApp.api.preAuthorizedApplications | Where-Object { $_.appId -eq $azureCliAppId }

        if (-not $existingPreAuth) {
            $preAuthPayload = @{
                api = @{
                    preAuthorizedApplications = @(
                        @{
                            appId = $azureCliAppId
                            delegatedPermissionIds = @($scopeId)
                        }
                    )
                }
            } | ConvertTo-Json -Depth 10

            $tempPreAuthFile = [System.IO.Path]::GetTempFileName()
            $preAuthPayload | Out-File -FilePath $tempPreAuthFile -Encoding utf8 -NoNewline
            az rest --method PATCH --url $ENTRA_APP_URL --headers "Content-Type=application/json" --body "@$tempPreAuthFile" | Out-Null
            Remove-Item $tempPreAuthFile -Force
        } else {
            # Already pre-authorized
        }
    }
    catch {
        Write-Warn "Failed to configure OAuth2 scope/pre-authorization: $_"
        Write-Warn "You may need to manually add a scope and authorize Azure CLI in the Azure Portal."
        Write-Warn "See: Entra App > Expose an API > Add a scope, then Add a client application"
    }

    # Define the app-role in the Entra App
    $appDetails = az rest --method GET --url $ENTRA_APP_URL | ConvertFrom-Json
    $existingRole = $appDetails.appRoles | Where-Object { $_.value -eq $ENTRA_APP_ROLE_VALUE }

    if (-not $existingRole) {
        Write-Info "Adding app role: $ENTRA_APP_ROLE_VALUE"

        # Prepare the app-roles payload by fetching existing roles, appending a new one
        $existingRoles = $appDetails.appRoles
        $newRole = @{
            allowedMemberTypes = @("User", "Application")
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

        $script:ENTRA_APP_ROLE_ID_BY_VALUE = $ENTRA_APP_ROLE_ID
    }
    else {
        $script:ENTRA_APP_ROLE_ID_BY_VALUE = $existingRole.id
    }

    # Get the service principal object ID
    Write-Info "Getting Entra App Service Principal..."
    
    # Helper function to look up SP object ID using multiple methods
    function Get-SpObjectId {
        param([string]$AppId)
        
        $oldEAP = $ErrorActionPreference
        $spId = $null
        
        # Method 1: az ad sp show --id <appId> (fastest)
        $ErrorActionPreference = 'SilentlyContinue'
        try {
            $spRaw = az ad sp show --id $AppId --output json 2>$null
            if ($LASTEXITCODE -eq 0 -and $spRaw) {
                $spObj = $spRaw | ConvertFrom-Json
                if ($spObj -and $spObj.id) {
                    $spId = $spObj.id
                }
            }
        } catch { }
        $ErrorActionPreference = $oldEAP
        if ($spId) { return $spId }
        
        # Method 2: az ad sp list --filter (handles replication delays)
        $ErrorActionPreference = 'SilentlyContinue'
        try {
            $spList = az ad sp list --filter "appId eq '$AppId'" --query "[0].id" -o tsv 2>$null
            if ($LASTEXITCODE -eq 0 -and $spList -and $spList -ne "null" -and $spList.Trim() -ne "") {
                $spId = $spList.Trim()
            }
        } catch { }
        $ErrorActionPreference = $oldEAP
        if ($spId) { return $spId }
        
        # Method 3: Graph API direct query (works when az ad sp commands fail)
        $ErrorActionPreference = 'SilentlyContinue'
        try {
            $graphUrl = "https://graph.microsoft.com/v1.0/servicePrincipals?\`$filter=appId eq '$AppId'&\`$select=id"
            $graphResult = az rest --method GET --url $graphUrl 2>$null
            if ($LASTEXITCODE -eq 0 -and $graphResult) {
                $graphObj = $graphResult | ConvertFrom-Json
                if ($graphObj -and $graphObj.value -and $graphObj.value.Count -gt 0) {
                    $spId = $graphObj.value[0].id
                }
            }
        } catch { }
        $ErrorActionPreference = $oldEAP
        
        return $spId
    }
    
    # Small delay to allow Entra ID to propagate the app registration
    Start-Sleep -Seconds 3
    
    $ENTRA_APP_SP_OBJECT_ID = Get-SpObjectId -AppId $ENTRA_APP_CLIENT_ID
    
    if (-not $ENTRA_APP_SP_OBJECT_ID) {
        $oldEAP = $ErrorActionPreference
        $ErrorActionPreference = 'SilentlyContinue'
        $createResult = az ad sp create --id $ENTRA_APP_CLIENT_ID 2>&1
        $createExitCode = $LASTEXITCODE
        $ErrorActionPreference = $oldEAP
        
        if ($createExitCode -eq 0 -and $createResult) {
            try {
                $createObj = ($createResult | Out-String) | ConvertFrom-Json
                if ($createObj -and $createObj.id) {
                    $ENTRA_APP_SP_OBJECT_ID = $createObj.id
                }
            } catch { }
        }
        
        # If we didn't extract the ID from the create response, retry lookup with increasing delays
        if (-not $ENTRA_APP_SP_OBJECT_ID) {
            $retryDelays = @(5, 10, 15)
            foreach ($delay in $retryDelays) {
                Start-Sleep -Seconds $delay
                $ENTRA_APP_SP_OBJECT_ID = Get-SpObjectId -AppId $ENTRA_APP_CLIENT_ID
                if ($ENTRA_APP_SP_OBJECT_ID) { break }
            }
        }
    }
    
    if (-not $ENTRA_APP_SP_OBJECT_ID) {
        Write-Error "Failed to get or create Service Principal for Entra App"
        Write-Error ""
        Write-Error "MANUAL FIX:"
        Write-Error "1. Create the SP manually:  az ad sp create --id $ENTRA_APP_CLIENT_ID"
        Write-Error "2. Get the SP Object ID:    az ad sp show --id $ENTRA_APP_CLIENT_ID --query id -o tsv"
        Write-Error "3. Re-run this script"
        exit 1
    }
    
    Write-Info "Entra App SP Object ID: $ENTRA_APP_SP_OBJECT_ID"

    # Export variables for use in other functions
    $script:ENTRA_APP_CLIENT_ID = $ENTRA_APP_CLIENT_ID
    $script:ENTRA_APP_OBJECT_ID = $ENTRA_APP_OBJECT_ID
    $script:ENTRA_APP_ROLE_VALUE = $ENTRA_APP_ROLE_VALUE
    $script:ENTRA_APP_SP_OBJECT_ID = $ENTRA_APP_SP_OBJECT_ID

    # Ensure current user is an owner of the app
    try {
        $currentUserEmail = az account show --query "user.name" -o tsv
        $currentUserObjectId = $null
        try {
            $currentUserObjectId = az ad user show --id $currentUserEmail --query "id" -o tsv 2>&1 | Out-Null
            if ($LASTEXITCODE -ne 0) { $currentUserObjectId = $null }
        } catch { $currentUserObjectId = $null }
        
        if ($currentUserObjectId -and $currentUserObjectId -ne "null") {
            $owners = az ad app owner list --id $ENTRA_APP_CLIENT_ID --query "[].id" -o tsv 2>$null
            if ($owners -notcontains $currentUserObjectId) {
                az ad app owner add --id $ENTRA_APP_CLIENT_ID --owner-object-id $currentUserObjectId 2>$null
            }
        }
    }
    catch {
        Write-Warn "Could not ensure user is owner of Entra App: $_"
    }

    Write-Info "Entra App registration completed"
}

function Assign-Current-User-Role {
    Write-Info "Assigning Mcp.Tool.Executor role to current user..."
    
    $currentUserEmail = az account show --query "user.name" -o tsv
    
    # Get user object ID
    $userObjectId = $null
    try {
        $userObjectId = az ad user show --id $currentUserEmail --query "id" -o tsv 2>&1 | Out-Null
        if ($LASTEXITCODE -ne 0) { $userObjectId = $null }
    } catch { $userObjectId = $null }
    
    if (-not $userObjectId -or $userObjectId -eq "null" -or $userObjectId -eq "") {
        # Fallback: Graph API /me endpoint
        try {
            $meResult = az rest --method GET --url "https://graph.microsoft.com/v1.0/me" 2>&1
            if ($LASTEXITCODE -eq 0 -and $meResult) {
                $meData = $meResult | ConvertFrom-Json
                $userObjectId = $meData.id
            } else {
                throw "Graph API /me endpoint failed"
            }
        }
        catch {
            Write-Warn "Could not find user object ID. Manual role assignment required."
            Write-Warn "Get your Object ID: az rest --method GET --url `"https://graph.microsoft.com/v1.0/me`" --query id -o tsv"
            Write-Warn "See: docs/TROUBLESHOOTING-DEPLOYMENT.md"
            return
        }
    }
    
    # Check if role assignment already exists
    $existingAssignment = az rest --method GET --url "https://graph.microsoft.com/v1.0/servicePrincipals/$($script:ENTRA_APP_SP_OBJECT_ID)/appRoleAssignedTo" --query "value[?principalId=='$userObjectId' && appRoleId=='$($script:ENTRA_APP_ROLE_ID_BY_VALUE)']" | ConvertFrom-Json
    
    if ($existingAssignment -and $existingAssignment.Count -gt 0) {
        return
    }
    
    # Assign the role
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
        
        if ($LASTEXITCODE -eq 0) {
            Write-Info "Role assigned to $currentUserEmail (sign out/in for it to take effect)"
        }
        else {
            if ($output -match "Authorization_RequestDenied|Insufficient privileges") {
                Write-Warn "Insufficient permissions. Assign 'Mcp.Tool.Executor' role manually in Azure Portal > Enterprise Applications > $($script:ENTRA_APP_NAME) > Users and groups"
            }
            else {
                throw "Azure CLI command failed: $output"
            }
        }
    }
    catch {
        Write-Warn "Failed to assign role: $_. Assign 'Mcp.Tool.Executor' manually in Azure Portal."
    }
}

function Check-Prerequisites {
    if (-not (Get-Command az -ErrorAction SilentlyContinue)) {
        Write-Error "Azure CLI is not installed. Please install it from https://docs.microsoft.com/en-us/cli/azure/install-azure-cli"
        exit 1
    }
    if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
        Write-Error "Docker is not installed. Please install Docker Desktop."
        exit 1
    }
}

function Login-Azure {
    try {
        az account show | Out-Null
    }
    catch {
        Write-Info "Not logged in. Running 'az login'..."
        az login
    }
    if ($SUBSCRIPTION_ID) {
        az account set --subscription $SUBSCRIPTION_ID
    }
}

function Verify-Resource-Group {
    $rgExists = az group exists --name $ResourceGroup
    if ($rgExists -eq "false") {
        Write-Error "Resource group '$ResourceGroup' does not exist."
        exit 1
    }

    if ($script:COSMOS_RESOURCE_GROUP -ne $ResourceGroup) {
        $cosmosRgExists = az group exists --name $script:COSMOS_RESOURCE_GROUP
        if ($cosmosRgExists -eq "false") {
            Write-Error "Cosmos resource group '$($script:COSMOS_RESOURCE_GROUP)' does not exist."
            exit 1
        }
    }

    if ($script:ACR_RESOURCE_GROUP -ne $ResourceGroup) {
        $acrRgExists = az group exists --name $script:ACR_RESOURCE_GROUP
        if ($acrRgExists -eq "false") {
            Write-Error "ACR resource group '$($script:ACR_RESOURCE_GROUP)' does not exist."
            exit 1
        }
    }
}

function Deploy-Infrastructure {
    try {
        $existingApp = az containerapp show --name $ContainerAppName --resource-group $ResourceGroup 2>$null | ConvertFrom-Json
        if ($existingApp) {
            Write-Info "Container App already exists, skipping infrastructure deployment"
            $script:SKIP_INFRA = $true
            return
        }
    }
    catch {
        $script:SKIP_INFRA = $false
    }

    Write-Info "Creating Azure Container resources..."

    if ($script:USE_EXISTING_ACR) {
        az deployment group create --resource-group $ResourceGroup --template-file "infrastructure/main.bicep" --parameters "useExistingAcr=true" "existingAcrName=$($script:ACR_NAME)" "existingAcrResourceGroup=$($script:ACR_RESOURCE_GROUP)" --output table
    }
    else {
        az deployment group create --resource-group $ResourceGroup --template-file "infrastructure/main.bicep" --output table
    }

    Write-Info "Azure Container resources deployed"
}

function Get-Deployment-Outputs {
    $acrName = $script:ACR_NAME
    if ([string]::IsNullOrWhiteSpace($acrName)) {
        $acrName = az acr list --resource-group $script:ACR_RESOURCE_GROUP --query "[0].name" -o tsv
        $script:ACR_NAME = $acrName
    }
    $containerApp = az containerapp show --name $ContainerAppName --resource-group $ResourceGroup | ConvertFrom-Json
    
    $script:CONTAINER_REGISTRY = "$acrName.azurecr.io"
    $script:CONTAINER_APP_URL = "https://$($containerApp.properties.configuration.ingress.fqdn)"

    Write-Info "Registry: $script:CONTAINER_REGISTRY | App URL: $script:CONTAINER_APP_URL"
}

function Build-And-Push-Image {
    Write-Info "Building and pushing container image..."

    $ACR_NAME = $script:CONTAINER_REGISTRY -replace '\.azurecr\.io$', ''

    try {
        az acr login --name $ACR_NAME --resource-group $script:ACR_RESOURCE_GROUP
        
        if ($LASTEXITCODE -ne 0) {
            throw "ACR login failed with exit code $LASTEXITCODE"
        }

        $timestamp = Get-Date -Format "yyyyMMdd-HHmmss"
        $IMAGE_TAG = "$($script:CONTAINER_REGISTRY)/mcp-toolkit:$timestamp"

        $rootDir = Split-Path -Parent $SCRIPT_DIR
        Push-Location $rootDir
        
        try {
            dotnet publish src/AzureCosmosDB.MCP.Toolkit/AzureCosmosDB.MCP.Toolkit.csproj -c Release -o src/AzureCosmosDB.MCP.Toolkit/bin/publish

            docker build --platform linux/amd64 -t $IMAGE_TAG -f Dockerfile.runtime .
            if ($LASTEXITCODE -ne 0) { throw "Docker build failed" }

            docker push $IMAGE_TAG
            if ($LASTEXITCODE -ne 0) { throw "Docker push failed" }

            $script:IMAGE_TAG = $IMAGE_TAG
            Write-Info "Image pushed: $IMAGE_TAG"
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
    Write-Info "Updating Container App configuration..."

    $CURRENT_TENANT_ID = az account show --query "tenantId" --output tsv
    $cosmosEndpoint = az cosmosdb show --name $CosmosAccountName --resource-group $script:COSMOS_RESOURCE_GROUP --query "documentEndpoint" --output tsv
    
    # Get Container App to extract existing environment variables
    $containerApp = az containerapp show --name $ContainerAppName --resource-group $ResourceGroup | ConvertFrom-Json
    
    # Enable system-assigned managed identity if not already enabled
    $identityJustCreated = $false
    if ($containerApp.identity.type -ne "SystemAssigned") {
        Write-Info "Enabling SystemAssigned managed identity..."
        az containerapp identity assign --name $ContainerAppName --resource-group $ResourceGroup --system-assigned
        Start-Sleep -Seconds 15
        $containerApp = az containerapp show --name $ContainerAppName --resource-group $ResourceGroup | ConvertFrom-Json
        $identityJustCreated = $true
    }
    
    # Get existing environment variables to extract Azure AI Services endpoint and embedding settings
    $existingEnvVars = $containerApp.properties.template.containers[0].env
    $azureAiServiceEndpoint = ($existingEnvVars | Where-Object { $_.name -eq "OPENAI_ENDPOINT" }).value
    $embeddingDeployment = ($existingEnvVars | Where-Object { $_.name -eq "OPENAI_EMBEDDING_DEPLOYMENT" }).value
    
    if (-not $azureAiServiceEndpoint) {
        Write-Warn "OPENAI_ENDPOINT not configured. Set manually: az containerapp update --name $ContainerAppName --resource-group $ResourceGroup --set-env-vars 'OPENAI_ENDPOINT=<endpoint>'"
    } else {
        $script:OPENAI_ENDPOINT = $azureAiServiceEndpoint
    }
    
    if (-not $embeddingDeployment) {
        Write-Warn "OPENAI_EMBEDDING_DEPLOYMENT not configured."
    }

    # Build environment variables list
    $envVars = @(
        "AzureAd__ClientId=$script:ENTRA_APP_CLIENT_ID"
        "AzureAd__TenantId=$CURRENT_TENANT_ID"
        "AzureAd__Audience=$script:ENTRA_APP_CLIENT_ID"
        "COSMOS_ENDPOINT=$cosmosEndpoint"
        "ASPNETCORE_ENVIRONMENT=Production"
        "ASPNETCORE_URLS=http://+:8080"
    )

    # If a user-assigned identity exists, set AZURE_CLIENT_ID so DefaultAzureCredential resolves correctly
    $userAssigned = $containerApp.identity.userAssignedIdentities
    if ($userAssigned) {
        $uaClientId = ($userAssigned.PSObject.Properties | Select-Object -First 1).Value.clientId
        if ($uaClientId) {
            $envVars += "AZURE_CLIENT_ID=$uaClientId"
        }
    }
    
    if ($azureAiServiceEndpoint) {
        $envVars += "OPENAI_ENDPOINT=$azureAiServiceEndpoint"
    }
    
    if ($embeddingDeployment) {
        $envVars += "OPENAI_EMBEDDING_DEPLOYMENT=$embeddingDeployment"
    }

    # Ensure ingress is configured correctly for port 8080
    try {
        az containerapp ingress update --name $ContainerAppName --resource-group $ResourceGroup --target-port 8080 | Out-Null
    }
    catch {
        Write-Warn "Failed to update ingress configuration: $_"
    }
    
    # Configure CORS
    $existingCors = az containerapp ingress cors show --name $ContainerAppName --resource-group $ResourceGroup 2>$null | ConvertFrom-Json
    
    if (-not ($existingCors -and $existingCors.allowedOrigins -contains "*")) {
        try {
            Start-Sleep -Seconds 2
            $ErrorActionPreference = "Continue"
            az containerapp ingress cors enable --name $ContainerAppName --resource-group $ResourceGroup --allowed-origins "*" --allowed-methods "GET,POST,PUT,DELETE,OPTIONS" --allowed-headers "*" --expose-headers "*" --max-age 3600 --output none 2>&1 | Out-Null
            $ErrorActionPreference = "Stop"
        }
        catch {
            Write-Warn "CORS configuration may need manual setup in Azure Portal"
        }
    }
    
    # Configure ACR registry credentials
    $acrName = $script:ACR_NAME
    if ([string]::IsNullOrWhiteSpace($acrName)) {
        $acrName = az acr list --resource-group $script:ACR_RESOURCE_GROUP --query "[0].name" -o tsv
        $script:ACR_NAME = $acrName
    }
    $acrLoginServer = az acr show --name $acrName --resource-group $script:ACR_RESOURCE_GROUP --query "loginServer" -o tsv
    $acrUsername = az acr credential show --name $acrName --resource-group $script:ACR_RESOURCE_GROUP --query "username" -o tsv
    $acrPassword = az acr credential show --name $acrName --resource-group $script:ACR_RESOURCE_GROUP --query "passwords[0].value" -o tsv
    
    try {
        az containerapp registry set --name $ContainerAppName --resource-group $ResourceGroup --server $acrLoginServer --username $acrUsername --password $acrPassword --output none
    }
    catch {
        Write-Warn "Failed to set ACR credentials: $_"
    }
    
    # Update container app with image and/or env vars
    if ($script:IMAGE_TAG) {
        try {
            az containerapp update --name $ContainerAppName --resource-group $ResourceGroup --image $script:IMAGE_TAG --set-env-vars $envVars --output none
            if ($LASTEXITCODE -ne 0) { throw "Container app update failed" }
            Write-Info "Container app updated with image: $($script:IMAGE_TAG)"
        }
        catch {
            Write-Error "Container app update failed: $($_.Exception.Message)"
            exit 1
        }
    }
    else {
        Write-Warn "No new image built, updating environment variables only"
        try {
            az containerapp update --name $ContainerAppName --resource-group $ResourceGroup --set-env-vars $envVars --output none
            if ($LASTEXITCODE -ne 0) { throw "Container app update failed" }
        }
        catch {
            Write-Warn "Failed to update environment variables: $($_.Exception.Message)"
        }
    }

    $script:CURRENT_TENANT_ID = $CURRENT_TENANT_ID
}

function Configure-Entra-App-RedirectURIs {
    $containerAppFqdn = $script:CONTAINER_APP_URL -replace '^https?://', ''
    
    $redirectUris = @(
        "https://$containerAppFqdn"
        "https://$containerAppFqdn/signin-oidc"
    )
    
    $ENTRA_APP_URL = "https://graph.microsoft.com/v1.0/applications/$($script:ENTRA_APP_OBJECT_ID)"
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
        Write-Info "SPA redirect URIs configured: $($redirectUris -join ', ')"
    }
    catch {
        Write-Warn "Failed to configure redirect URIs. Add manually as SPA redirect URIs in Azure Portal."
    }
    finally {
        if (Test-Path $tempFile) { Remove-Item $tempFile -Force }
    }
}

function Assign-Cosmos-RBAC {
    Write-Info "Assigning Cosmos DB RBAC roles..."

    $containerAppIdentity = az containerapp identity show --resource-group $ResourceGroup --name $ContainerAppName | ConvertFrom-Json
    $ACA_MI_PRINCIPAL_ID = $containerAppIdentity.principalId
    
    if (-not $ACA_MI_PRINCIPAL_ID -or $ACA_MI_PRINCIPAL_ID -eq "null") {
        Write-Error "Failed to get Container App Managed Identity Principal ID"
        exit 1
    }

    # Collect all principal IDs that need Cosmos DB access
    $principalIds = @($ACA_MI_PRINCIPAL_ID)
    if ($containerAppIdentity.userAssignedIdentities) {
        foreach ($ua in $containerAppIdentity.userAssignedIdentities.PSObject.Properties) {
            $uaPrincipal = $ua.Value.principalId
            if ($uaPrincipal -and $uaPrincipal -notin $principalIds) {
                $principalIds += $uaPrincipal
            }
        }
    }
    
    $ACA_MI_DISPLAY_NAME = $ContainerAppName

    Write-Info "Principal IDs: $($principalIds -join ', ')"
    
    # Assign Cosmos DB Built-in Data Reader role at native data-plane root scope (/)
    Write-Info "Assigning Cosmos DB Data Reader role..."
    $subscriptionId = az account show --query id -o tsv
    $roleDefinitionGuid = "00000000-0000-0000-0000-000000000001"
    $roleDefinitionResourceId = "/subscriptions/$subscriptionId/resourceGroups/$($script:COSMOS_RESOURCE_GROUP)/providers/Microsoft.DocumentDB/databaseAccounts/$CosmosAccountName/sqlRoleDefinitions/$roleDefinitionGuid"
    $cosmosScope = "/"

    foreach ($principalId in $principalIds) {
        $existingAssignment = az cosmosdb sql role assignment list --account-name $CosmosAccountName --resource-group $script:COSMOS_RESOURCE_GROUP --query "[?principalId=='$principalId' && scope=='$cosmosScope' && contains(roleDefinitionId, '$roleDefinitionGuid')]" | ConvertFrom-Json

        if ($existingAssignment.Count -eq 0) {
            az cosmosdb sql role assignment create --account-name $CosmosAccountName --resource-group $script:COSMOS_RESOURCE_GROUP --role-definition-id $roleDefinitionResourceId --principal-id $principalId --scope $cosmosScope
            Write-Info "Assigned Cosmos DB Data Reader to '$principalId'"
        }
    }
    
    # Export variables for use in deployment summary and Cognitive Services RBAC
    $script:ACA_MI_PRINCIPAL_ID = $ACA_MI_PRINCIPAL_ID
    $script:ACA_MI_PRINCIPAL_IDS = $principalIds
    $script:ACA_MI_DISPLAY_NAME = $ACA_MI_DISPLAY_NAME
}

function Assign-AI-Foundry-RBAC {
    Write-Info "Assigning Azure AI Services RBAC roles..."

    # Get Container App to extract Azure AI Services endpoint
    $containerApp = az containerapp show --name $ContainerAppName --resource-group $ResourceGroup | ConvertFrom-Json
    $existingEnvVars = $containerApp.properties.template.containers[0].env
    $azureAiServiceEndpoint = ($existingEnvVars | Where-Object { $_.name -eq "OPENAI_ENDPOINT" }).value
    
    if (-not $azureAiServiceEndpoint) {
        Write-Warn "OPENAI_ENDPOINT not configured. Skipping AI Services RBAC."
        return
    }
    
    # Search for Cognitive Services accounts
    $cognitiveAccounts = az cognitiveservices account list --resource-group $ResourceGroup 2>$null | ConvertFrom-Json
    
    if (-not $cognitiveAccounts -or $cognitiveAccounts.Count -eq 0) {
        # The Cognitive Services account may be in a different resource group
        $endpointHost = ([System.Uri]$azureAiServiceEndpoint).Host
        $accountName = $endpointHost.Split('.')[0]
        $cognitiveAccounts = az cognitiveservices account list --query "[?name=='$accountName']" 2>$null | ConvertFrom-Json
        
        if (-not $cognitiveAccounts -or $cognitiveAccounts.Count -eq 0) {
            Write-Warn "No Cognitive Services accounts found matching endpoint. Assign 'Cognitive Services OpenAI User' manually."
            return
        }
    }
    
    # Match endpoint to Cognitive Services account
    $matchingAccount = $null
    
    if ($azureAiServiceEndpoint -match "\.services\.ai\.azure\.com") {
        Write-Warn "ERROR: The endpoint appears to be a Microsoft Foundry project URL."
        Write-Warn "Please use the Azure AI Services account endpoint instead."
        Write-Warn "How to get the correct endpoint:"
        Write-Warn "  1. Go to Azure Portal > Cognitive Services / AI Services resource"
        Write-Warn "  2. Copy the endpoint URL from the resource's Overview page"
        Write-Warn "  3. It should look like: https://<resource-name>.cognitiveservices.azure.com/"
        return
    }
    
    if ($azureAiServiceEndpoint -match "\.cognitiveservices\.azure\.com") {
        foreach ($account in $cognitiveAccounts) {
            if ($account.kind -eq "OpenAI" -or $account.properties.endpoint -match "openai\.cognitiveservices\.azure\.com") {
                $matchingAccount = $account
                break
            }
        }
        if (-not $matchingAccount -and $cognitiveAccounts.Count -gt 0) {
            $matchingAccount = $cognitiveAccounts[0]
        }
    }
    else {
        # Direct endpoint match for Azure AI Services
        $endpointHost = ([System.Uri]$azureAiServiceEndpoint).Host
        foreach ($account in $cognitiveAccounts) {
            $accountEndpoint = $account.properties.endpoint
            if ($accountEndpoint -and ($accountEndpoint.Contains($endpointHost) -or $endpointHost.Contains($account.name))) {
                $matchingAccount = $account
                break
            }
        }
    }
    
    if (-not $matchingAccount) {
        Write-Warn "Could not determine Cognitive Services account. Assigning to all OpenAI accounts..."
        
        $assigned = $false
        $principalIds = if ($script:ACA_MI_PRINCIPAL_IDS) { $script:ACA_MI_PRINCIPAL_IDS } else { @($script:ACA_MI_PRINCIPAL_ID) }
        foreach ($account in $cognitiveAccounts) {
            if ($account.kind -eq "OpenAI") {
                foreach ($principalId in $principalIds) {
                    $existingRoleAssignment = az role assignment list --assignee $principalId --scope $account.id --query "[?roleDefinitionName=='Cognitive Services OpenAI User'].id" -o tsv
                    if (-not $existingRoleAssignment) {
                        az role assignment create --role "Cognitive Services OpenAI User" --assignee-object-id $principalId --assignee-principal-type ServicePrincipal --scope $account.id
                        $assigned = $true
                    } else {
                        $assigned = $true
                    }
                }
            }
        }
        if (-not $assigned) { Write-Warn "No OpenAI accounts found. Assign role manually." }
        return
    }
    
    $resourceId = $matchingAccount.id
    Write-Info "Target: $($matchingAccount.name)"
    
    # Assign to all identity principals
    $principalIds = if ($script:ACA_MI_PRINCIPAL_IDS) { $script:ACA_MI_PRINCIPAL_IDS } else { @($script:ACA_MI_PRINCIPAL_ID) }
    foreach ($principalId in $principalIds) {
        $existingRoleAssignment = az role assignment list --assignee $principalId --scope $resourceId --query "[?roleDefinitionName=='Cognitive Services OpenAI User'].id" -o tsv
        if (-not $existingRoleAssignment) {
            az role assignment create --role "Cognitive Services OpenAI User" --assignee-object-id $principalId --assignee-principal-type ServicePrincipal --scope $resourceId
            Write-Info "Assigned 'Cognitive Services OpenAI User' to '$principalId'"
        }
    }
}

function Show-Container-Logs {
    Start-Sleep 10
    Write-Host ""
    Write-Info "Container App logs:"
    try {
        az containerapp logs show --name $ContainerAppName --resource-group $ResourceGroup --tail 50 --output table
    }
    catch {
        Write-Warn "Could not retrieve logs. Check later: az containerapp logs show --name $ContainerAppName --resource-group $ResourceGroup --tail 50"
    }
}

function Test-MCP-Server-Health {
    Write-Info "Verifying MCP server health (may take 1-3 minutes)..."
    
    $revision = az containerapp revision list --name $ContainerAppName --resource-group $ResourceGroup --query "[0]" | ConvertFrom-Json
    if ($revision.properties.provisioningState -ne "Provisioned") {
        Start-Sleep -Seconds 30
    }
    
    $maxRetries = 18
    $retryDelay = 10
    
    for ($i = 1; $i -le $maxRetries; $i++) {
        try {
            $response = Invoke-WebRequest -Uri "$($script:CONTAINER_APP_URL)/" -UseBasicParsing -TimeoutSec 30
            Write-Info "MCP server responding (Status: $($response.StatusCode))"
            return $true
        }
        catch {
            if ($i -eq $maxRetries) {
                Write-Error "MCP server failed to respond after $maxRetries attempts"
                return $false
            }
            Start-Sleep -Seconds $retryDelay
        }
    }
}

function Verify-Container-App-Status {
    $revision = az containerapp revision list --name $ContainerAppName --resource-group $ResourceGroup --query "[0]" | ConvertFrom-Json
    
    Write-Info "Revision: $($revision.name) | State: $($revision.properties.provisioningState) | Health: $($revision.properties.healthState)"
    
    if ($revision.properties.provisioningState -eq "Failed") {
        Write-Info "Restarting failed revision..."
        az containerapp revision restart --name $ContainerAppName --resource-group $ResourceGroup --revision $revision.name
        Start-Sleep -Seconds 30
    }
    
    return $revision.properties.provisioningState -eq "Provisioned"
}

function Show-Deployment-Summary {
    Validate-AzureAiServicesEndpoint
    
    $SUMMARY = @{
        MCP_SERVER_URI = $script:CONTAINER_APP_URL
        ENTRA_APP_CLIENT_ID = $script:ENTRA_APP_CLIENT_ID
        ENTRA_APP_OBJECT_ID = $script:ENTRA_APP_OBJECT_ID
        ENTRA_APP_SP_OBJECT_ID = $script:ENTRA_APP_SP_OBJECT_ID
        ENTRA_APP_DISPLAY_NAME = $ENTRA_APP_NAME
        ENTRA_APP_ROLE_VALUE = $script:ENTRA_APP_ROLE_VALUE
        ENTRA_APP_ROLE_ID_BY_VALUE = $script:ENTRA_APP_ROLE_ID_BY_VALUE
        ACA_MI_PRINCIPAL_ID = $script:ACA_MI_PRINCIPAL_ID
        ACA_MI_DISPLAY_NAME = $script:ACA_MI_DISPLAY_NAME
        RESOURCE_GROUP = $ResourceGroup
        COSMOS_RESOURCE_GROUP = $script:COSMOS_RESOURCE_GROUP
        ACR_RESOURCE_GROUP = $script:ACR_RESOURCE_GROUP
        ACR_NAME = $script:ACR_NAME
        SUBSCRIPTION_ID = (az account show --query id -o tsv)
        TENANT_ID = (az account show --query tenantId -o tsv)
        COSMOS_ACCOUNT_NAME = $CosmosAccountName
        LOCATION = $Location
    }
    
    $SUMMARY_JSON = $SUMMARY | ConvertTo-Json
    Write-Host $SUMMARY_JSON
    
    $DEPLOYMENT_INFO_FILE = "$SCRIPT_DIR/deployment-info.json"
    $SUMMARY_JSON | Out-File -FilePath $DEPLOYMENT_INFO_FILE -Encoding UTF8
    Write-Info "Deployment info saved to: $DEPLOYMENT_INFO_FILE"
}

function Update-Frontend-Config {
    $projectRoot = Split-Path -Parent $SCRIPT_DIR
    $htmlPath = Join-Path (Join-Path (Join-Path (Join-Path $projectRoot "src") "AzureCosmosDB.MCP.Toolkit") "wwwroot") "index.html"
    
    if (-not (Test-Path $htmlPath)) { return }
    
    try {
        $htmlContent = Get-Content $htmlPath -Raw
        $htmlContent = $htmlContent -replace 'value="https://[^"]*azurecontainerapps\.io"', "value=`"$($script:CONTAINER_APP_URL)`""
        $htmlContent | Out-File -FilePath $htmlPath -Encoding UTF8 -NoNewline
    }
    catch {
        Write-Warn "Failed to update frontend configuration: $_"
    }
}

# Main function (following PostgreSQL pattern)
function Validate-AzureAiServicesEndpoint {
    # Validate OPENAI_ENDPOINT format. The application supports three types:
    # 1. Azure AI Services (Cognitive Services): https://<resource>.cognitiveservices.azure.com/
    # 2. OpenAI Native API: https://api.openai.com/v1
    # 3. Azure AI Foundry: https://<resource>.services.ai.azure.com/api/projects/<project-name>
    if (-not $script:OPENAI_ENDPOINT) {
        return  # No endpoint configured yet is OK
    }
    
    # If endpoint is .services.ai.azure.com, it MUST be a valid Foundry project endpoint with /api/projects/
    if ($script:OPENAI_ENDPOINT -match "\.services\.ai\.azure\.com") {
        if ($script:OPENAI_ENDPOINT -notmatch "/api/projects/") {
            Write-Error @"
ERROR: Invalid Azure AI Foundry endpoint format

The OPENAI_ENDPOINT contains '.services.ai.azure.com' but is not a valid Azure AI Foundry project endpoint.

CORRECT FORMAT (Azure AI Foundry):
  https://<resource>.services.ai.azure.com/api/projects/<project-name>

INCORRECT FORMATS:
  https://<resource>.services.ai.azure.com/
  https://<resource>.services.ai.azure.com/api/projects/

TO FIX:
  1. Go to Azure Portal > AI Foundry project
  2. Copy the full project endpoint URL (must include /api/projects/<project-name>)
  3. Update OPENAI_ENDPOINT to the complete Foundry project endpoint

ALTERNATIVE (Azure AI Services / Cognitive Services):
  https://<resource>.cognitiveservices.azure.com/

For more information, see: https://aka.ms/foundry-endpoints
"@
            exit 1
        }
        # Valid Foundry endpoint, proceed
        Write-Info "Validated Azure AI Foundry endpoint: $script:OPENAI_ENDPOINT"
    }
}

function Main {
    param($Arguments)
    
    Write-Info "Starting deployment..."

    Parse-Arguments
    Check-Prerequisites
    Login-Azure
    Verify-Resource-Group
    Auto-Detect-Resources
    Create-Entra-App
    Assign-Current-User-Role
    Deploy-Infrastructure
    Get-Deployment-Outputs
    Update-Frontend-Config
    Build-And-Push-Image
    Update-Container-App
    Configure-Entra-App-RedirectURIs
    Assign-Cosmos-RBAC
    Assign-AI-Foundry-RBAC
    Show-Container-Logs

    Verify-Container-App-Status | Out-Null
    
    $mcpHealthy = Test-MCP-Server-Health
    if (-not $mcpHealthy) {
        Write-Warn "MCP server health check failed. Check logs: az containerapp logs show --name $ContainerAppName --resource-group $ResourceGroup --follow"
    }
    
    Show-Deployment-Summary
    
    Write-Info ""
    Write-Info "Deployment complete! Access: $($script:CONTAINER_APP_URL)"
    Write-Info "Sign out/in to get fresh token with Mcp.Tool.Executor role claim."
}

# Run main function
Main $args
