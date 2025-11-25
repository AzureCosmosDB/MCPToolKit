<#
.SYNOPSIS
    Create a managed identity connection in Microsoft Foundry project and assign Entra App role for Cosmos DB MCP Toolkit.

.DESCRIPTION
    This script:
    1. Reads deployment information from deployment-info.json
    2. Retrieves Microsoft Foundry project managed identity details
    3. Creates a managed identity connection in Microsoft Foundry for the Cosmos DB MCP Toolkit server
    4. Assigns the Entra App role to the Microsoft Foundry project managed identity

.PARAMETER AIFoundryProjectResourceId
    Resource ID of Microsoft Foundry project.
    Format: /subscriptions/{sub}/resourceGroups/{rg}/providers/Microsoft.CognitiveServices/accounts/{account}/projects/{project}

.PARAMETER ConnectionName
    Name for the connection in Microsoft Foundry (e.g., "cosmos-mcp-connection")

.EXAMPLE
    .\Setup-AIFoundry-Connection.ps1 -AIFoundryProjectResourceId "/subscriptions/xxxxx/resourceGroups/my-rg/providers/Microsoft.CognitiveServices/accounts/my-account/projects/my-project" -ConnectionName "cosmos-mcp-connection"

.NOTES
    Prerequisites:
    - Azure CLI installed and authenticated
    - deployment-info.json must exist in the same directory (created by Deploy-Cosmos-MCP-Toolkit.ps1)
    - Appropriate permissions to manage Microsoft Foundry projects and Entra ID app role assignments
#>

param(
    [Parameter(Mandatory=$false)]
    [string]$AIFoundryProjectResourceId,
    
    [Parameter(Mandatory=$false)]
    [string]$AIFoundryProjectName,
    
    [Parameter(Mandatory=$false)]
    [string]$AIFoundryAccountName,
    
    [Parameter(Mandatory=$false)]
    [string]$ResourceGroup,
    
    [Parameter(Mandatory=$false)]
    [string]$ConnectionName = "cosmos-mcp-toolkit-connection"
)

$ErrorActionPreference = "Stop"
$SCRIPT_DIR = Split-Path -Parent $MyInvocation.MyCommand.Path

# Helper functions
function Write-Info {
    param([string]$Message)
    Write-Host "[INFO] $Message" -ForegroundColor Green
}

function Write-Warning-Message {
    param([string]$Message)
    Write-Host "[WARN] $Message" -ForegroundColor Yellow
}

function Write-Error-Message {
    param([string]$Message)
    Write-Host "[ERROR] $Message" -ForegroundColor Red
}

function Print-Usage {
    Write-Host @"
Usage: .\Setup-AIFoundry-Connection.ps1 -ConnectionName <name> [OPTIONS]

Create a managed identity connection in Microsoft Foundry project and assign Entra App role.

REQUIRED PARAMETERS:
  -ConnectionName <name>
                          Connection name

OPTIONS (choose one):
  Option 1: Use Resource ID
    -AIFoundryProjectResourceId <resource-id>
                          Full resource ID of Microsoft Foundry project
                          Format: /subscriptions/{sub}/resourceGroups/{rg}/providers/Microsoft.CognitiveServices/accounts/{account}/projects/{project}

  Option 2: Use Project Name and Account Name
    -AIFoundryProjectName <project-name>
                          Name of the Microsoft Foundry project
    -AIFoundryAccountName <account-name>
                          Name of the Microsoft Foundry account (hub)
    -ResourceGroup <rg-name>
                          Resource group name (optional, will auto-detect if not provided)

NOTE: deployment-info.json must exist in the same directory as this script.
      This file is produced when running Deploy-Cosmos-MCP-Toolkit.ps1
      It should contain: MCP_SERVER_URI, ENTRA_APP_CLIENT_ID, ENTRA_APP_ROLE_VALUE, ENTRA_APP_ROLE_ID_BY_VALUE, ENTRA_APP_SP_OBJECT_ID
      Connection target is read from MCP_SERVER_URI
      Connection audience is constructed as {ENTRA_APP_CLIENT_ID}

EXAMPLES:
  # Option 1: Using Resource ID
  .\Setup-AIFoundry-Connection.ps1 -AIFoundryProjectResourceId "/subscriptions/xxx/resourceGroups/my-rg/providers/Microsoft.CognitiveServices/accounts/my-hub/projects/my-project" -ConnectionName "cosmos-mcp-connection"

  # Option 2: Using Project and Account Names
  .\Setup-AIFoundry-Connection.ps1 -AIFoundryProjectName "my-project" -AIFoundryAccountName "my-hub" -ConnectionName "cosmos-mcp-connection"
  
  # Option 2 with explicit resource group
  .\Setup-AIFoundry-Connection.ps1 -AIFoundryProjectName "my-project" -AIFoundryAccountName "my-hub" -ResourceGroup "my-rg" -ConnectionName "cosmos-mcp-connection"
"@
}

function Validate-AIFoundryProjectResourceId {
    param([string]$ResourceId)
    
    $pattern = "^/subscriptions/[a-fA-F0-9-]+/resourceGroups/[^/]+/providers/Microsoft\.CognitiveServices/accounts/[^/]+/projects/[^/]+$"
    if ($ResourceId -notmatch $pattern) {
        Write-Error-Message "Invalid Microsoft Foundry project resource ID format"
        Write-Error-Message "Expected format: /subscriptions/{subscriptionId}/resourceGroups/{resourceGroup}/providers/Microsoft.CognitiveServices/accounts/{accountName}/projects/{projectName}"
        Write-Error-Message "Provided: $ResourceId"
        exit 1
    }
}

function Parse-Arguments {
    # Check if using Resource ID or individual parameters
    if ($AIFoundryProjectResourceId) {
        # Option 1: Parse from Resource ID
        Write-Info "Using Microsoft Foundry Project Resource ID"
        Validate-AIFoundryProjectResourceId -ResourceId $AIFoundryProjectResourceId
        
        # Extract components from resource ID
        if ($AIFoundryProjectResourceId -match "/subscriptions/([^/]+)/") {
            $script:AI_FOUNDRY_SUBSCRIPTION_ID = $Matches[1]
        } else {
            Write-Error-Message "Failed to extract subscription ID from Microsoft Foundry project resource ID"
            exit 1
        }
        
        if ($AIFoundryProjectResourceId -match "/resourceGroups/([^/]+)/") {
            $script:AI_FOUNDRY_RESOURCE_GROUP = $Matches[1]
        } else {
            Write-Error-Message "Failed to extract resource group from Microsoft Foundry project resource ID"
            exit 1
        }
        
        if ($AIFoundryProjectResourceId -match "/accounts/([^/]+)/projects/") {
            $script:AI_FOUNDRY_ACCOUNT_NAME = $Matches[1]
        } else {
            Write-Error-Message "Failed to extract account name from Microsoft Foundry project resource ID"
            exit 1
        }
        
        if ($AIFoundryProjectResourceId -match "/projects/([^/]+)$") {
            $script:AI_FOUNDRY_PROJECT_NAME = $Matches[1]
        } else {
            Write-Error-Message "Failed to extract project name from Microsoft Foundry project resource ID"
            exit 1
        }
        
        Write-Info "[OK] Microsoft Foundry Project Resource ID: $AIFoundryProjectResourceId"
    }
    elseif ($AIFoundryProjectName -and $AIFoundryAccountName) {
        # Option 2: Use project name and account name
        Write-Info "Using Microsoft Foundry Project Name and Account Name"
        $script:AI_FOUNDRY_PROJECT_NAME = $AIFoundryProjectName
        $script:AI_FOUNDRY_ACCOUNT_NAME = $AIFoundryAccountName
        
        # Get current subscription
        $accountInfo = az account show -o json | ConvertFrom-Json
        $script:AI_FOUNDRY_SUBSCRIPTION_ID = $accountInfo.id
        
        # If resource group not provided, try to find it
        if (-not $ResourceGroup) {
            Write-Info "Resource group not provided, searching for Microsoft Foundry account..."
            $accountList = az cognitiveservices account list --query "[?name=='$AIFoundryAccountName'].{name:name, resourceGroup:resourceGroup}" -o json | ConvertFrom-Json
            
            if ($accountList -and $accountList.Count -gt 0) {
                $script:AI_FOUNDRY_RESOURCE_GROUP = $accountList[0].resourceGroup
                Write-Info "[OK] Found Microsoft Foundry account in resource group: $script:AI_FOUNDRY_RESOURCE_GROUP"
            } else {
                Write-Error-Message "Could not find Microsoft Foundry account '$AIFoundryAccountName' in subscription. Please provide -ResourceGroup parameter."
                exit 1
            }
        } else {
            $script:AI_FOUNDRY_RESOURCE_GROUP = $ResourceGroup
        }
        
        # Construct the resource ID
        $AIFoundryProjectResourceId = "/subscriptions/$($script:AI_FOUNDRY_SUBSCRIPTION_ID)/resourceGroups/$($script:AI_FOUNDRY_RESOURCE_GROUP)/providers/Microsoft.CognitiveServices/accounts/$($script:AI_FOUNDRY_ACCOUNT_NAME)/projects/$($script:AI_FOUNDRY_PROJECT_NAME)"
        Write-Info "[OK] Constructed Resource ID: $AIFoundryProjectResourceId"
    }
    else {
        Write-Error-Message "You must provide either:"
        Write-Error-Message "  1. -AIFoundryProjectResourceId, OR"
        Write-Error-Message "  2. Both -AIFoundryProjectName and -AIFoundryAccountName"
        Print-Usage
        exit 1
    }
    
    Write-Info "[OK] Connection Name: $ConnectionName"
    Write-Info "[OK] Using Azure Subscription: $script:AI_FOUNDRY_SUBSCRIPTION_ID"
    Write-Info "[OK] Using Microsoft Foundry Account: $script:AI_FOUNDRY_ACCOUNT_NAME"
    Write-Info "[OK] Using Microsoft Foundry Resource Group: $script:AI_FOUNDRY_RESOURCE_GROUP"
    Write-Info "[OK] Using Microsoft Foundry Project: $script:AI_FOUNDRY_PROJECT_NAME"
    
    # Load deployment info file from same directory as script
    $script:DEPLOYMENT_INFO_FILE = Join-Path $SCRIPT_DIR "deployment-info.json"
    if (-not (Test-Path $script:DEPLOYMENT_INFO_FILE)) {
        Write-Error-Message "Deployment info file not found: $script:DEPLOYMENT_INFO_FILE"
        exit 1
    }
    
    Write-Info "Loading deployment info from: $script:DEPLOYMENT_INFO_FILE"
    $deploymentInfo = Get-Content $script:DEPLOYMENT_INFO_FILE | ConvertFrom-Json
    
    $script:MCP_SERVER_URI = $deploymentInfo.MCP_SERVER_URI
    $script:ENTRA_APP_CLIENT_ID = $deploymentInfo.ENTRA_APP_CLIENT_ID
    $script:ENTRA_APP_ROLE_VALUE = $deploymentInfo.ENTRA_APP_ROLE_VALUE
    $script:ENTRA_APP_ROLE_ID_BY_VALUE = $deploymentInfo.ENTRA_APP_ROLE_ID_BY_VALUE
    $script:ENTRA_APP_SP_OBJECT_ID = $deploymentInfo.ENTRA_APP_SP_OBJECT_ID
    
    if (-not $script:MCP_SERVER_URI -or -not $script:ENTRA_APP_CLIENT_ID -or -not $script:ENTRA_APP_ROLE_VALUE -or -not $script:ENTRA_APP_ROLE_ID_BY_VALUE -or -not $script:ENTRA_APP_SP_OBJECT_ID) {
        Write-Error-Message "Missing required fields in deployment-info.json"
        Write-Error-Message "Required fields: MCP_SERVER_URI, ENTRA_APP_CLIENT_ID, ENTRA_APP_ROLE_VALUE, ENTRA_APP_ROLE_ID_BY_VALUE, ENTRA_APP_SP_OBJECT_ID"
        exit 1
    }
    
    # Construct connection target and audience from deployment info
    $script:CONNECTION_TARGET = $script:MCP_SERVER_URI
    $script:CONNECTION_AUDIENCE = $script:ENTRA_APP_CLIENT_ID
    
    Write-Info "[OK] Deployment info loaded successfully"
    Write-Info "[OK] Connection Target: $script:CONNECTION_TARGET"
    Write-Info "[OK] Connection Audience: $script:CONNECTION_AUDIENCE"
}

function Check-Prerequisites {
    Write-Info "Checking prerequisites (az-cli)..."
    
    try {
        $null = az version
    } catch {
        Write-Error-Message "Azure CLI is not installed. Please install it from https://docs.microsoft.com/en-us/cli/azure/install-azure-cli"
        exit 1
    }
}

function Login-Azure {
    Write-Info "Checking az cli login status..."
    
    $accountCheck = az account show 2>&1
    if ($LASTEXITCODE -ne 0) {
        Write-Info "Not logged in to az-cli. Running 'az login'..."
        az login
    }
    
    if ($script:AI_FOUNDRY_SUBSCRIPTION_ID) {
        Write-Info "Setting subscription to $script:AI_FOUNDRY_SUBSCRIPTION_ID"
        az account set --subscription $script:AI_FOUNDRY_SUBSCRIPTION_ID
    }
}

function Get-AccessToken {
    param([string]$ResourceUri)
    
    if (-not $ResourceUri) {
        Write-Error-Message "Resource URI is required"
        exit 1
    }
    
    $tokenJson = az account get-access-token --resource $ResourceUri --query accessToken -o tsv
    
    if ($LASTEXITCODE -ne 0 -or -not $tokenJson) {
        Write-Error-Message "Failed to get access token for $ResourceUri"
        exit 1
    }
    
    return $tokenJson
}

function Get-AIFoundryProjectMI {
    Write-Info "Fetching Microsoft Foundry account region..."
    
    $accountJson = az cognitiveservices account show `
        --name $script:AI_FOUNDRY_ACCOUNT_NAME `
        --resource-group $script:AI_FOUNDRY_RESOURCE_GROUP `
        -o json | ConvertFrom-Json
    
    if ($LASTEXITCODE -ne 0) {
        Write-Error-Message "Failed to get Microsoft Foundry account details"
        exit 1
    }
    
    $script:AI_FOUNDRY_REGION = $accountJson.location.ToLower() -replace '\s', ''
    
    if (-not $script:AI_FOUNDRY_REGION) {
        Write-Error-Message "Failed to extract region from Microsoft Foundry account"
        exit 1
    }
    
    $armAccessToken = Get-AccessToken -ResourceUri "https://management.azure.com"
    
    Write-Info "Fetching Microsoft Foundry project details..."
    
    $apiEndpoint = "https://$($script:AI_FOUNDRY_REGION).management.azure.com:443/subscriptions/$($script:AI_FOUNDRY_SUBSCRIPTION_ID)/resourcegroups/$($script:AI_FOUNDRY_RESOURCE_GROUP)/providers/Microsoft.CognitiveServices/accounts/$($script:AI_FOUNDRY_ACCOUNT_NAME)/projects/$($script:AI_FOUNDRY_PROJECT_NAME)?api-version=2025-04-01-preview"
    
    $headers = @{
        "Authorization" = "Bearer $armAccessToken"
        "Content-Type" = "application/json"
    }
    
    $response = Invoke-RestMethod -Uri $apiEndpoint -Method Get -Headers $headers
    
    if (-not $response) {
        Write-Error-Message "Empty response from API"
        exit 1
    }
    
    $script:AI_FOUNDRY_PROJECT_MI_PRINCIPAL_ID = $response.identity.principalId
    if (-not $script:AI_FOUNDRY_PROJECT_MI_PRINCIPAL_ID) {
        Write-Error-Message "Failed to extract project MI Principal ID from Microsoft Foundry project"
        Write-Error-Message "Response: $($response | ConvertTo-Json)"
        exit 1
    }
    
    $script:AI_FOUNDRY_PROJECT_MI_TENANT_ID = $response.identity.tenantId
    $script:AI_FOUNDRY_PROJECT_MI_TYPE = $response.identity.type
    
    Write-Info "[OK] Microsoft Foundry Project MI Principal ID: $script:AI_FOUNDRY_PROJECT_MI_PRINCIPAL_ID"
    Write-Info "[OK] Microsoft Foundry Project MI Type: $script:AI_FOUNDRY_PROJECT_MI_TYPE"
}

function Set-AIFoundryMIRoleAssignment {
    Write-Info "Assigning app role to Microsoft Foundry project MI..."
    
    $graphAccessToken = Get-AccessToken -ResourceUri "https://graph.microsoft.com"
    
    Write-Info "Checking for existing role assignment..."
    
    $headers = @{
        "Authorization" = "Bearer $graphAccessToken"
        "Content-Type" = "application/json"
    }
    
    $existingUrl = "https://graph.microsoft.com/v1.0/servicePrincipals/$($script:AI_FOUNDRY_PROJECT_MI_PRINCIPAL_ID)/appRoleAssignments"
    $existingAssignments = Invoke-RestMethod -Uri $existingUrl -Method Get -Headers $headers
    
    $existingAssignment = $existingAssignments.value | Where-Object {
        $_.resourceId -eq $script:ENTRA_APP_SP_OBJECT_ID -and $_.appRoleId -eq $script:ENTRA_APP_ROLE_ID_BY_VALUE
    }
    
    if ($existingAssignment) {
        Write-Info "App role assignment already exists for this project MI"
        Write-Info "[OK] Role Assignment ID: $($existingAssignment.id)"
        $script:ENTRA_APP_ROLE_ASSIGNMENT_ID = $existingAssignment.id
    } else {
        Write-Info "Creating app role assignment: '$script:ENTRA_APP_ROLE_VALUE' to project MI..."
        
        $roleAssignmentPayload = @{
            principalId = $script:AI_FOUNDRY_PROJECT_MI_PRINCIPAL_ID
            resourceId = $script:ENTRA_APP_SP_OBJECT_ID
            appRoleId = $script:ENTRA_APP_ROLE_ID_BY_VALUE
        } | ConvertTo-Json
        
        $createUrl = "https://graph.microsoft.com/v1.0/servicePrincipals/$($script:AI_FOUNDRY_PROJECT_MI_PRINCIPAL_ID)/appRoleAssignments"
        
        try {
            $response = Invoke-RestMethod -Uri $createUrl -Method Post -Headers $headers -Body $roleAssignmentPayload
            
            $script:ENTRA_APP_ROLE_ASSIGNMENT_ID = $response.id
            if ($script:ENTRA_APP_ROLE_ASSIGNMENT_ID) {
                Write-Info "[OK] Successfully assigned app role to project MI"
                Write-Info "[OK] Role Assignment ID: $script:ENTRA_APP_ROLE_ASSIGNMENT_ID"
            } else {
                Write-Error-Message "Failed to assign app role to project MI"
                Write-Error-Message "Response: $($response | ConvertTo-Json)"
                exit 1
            }
        } catch {
            Write-Error-Message "Failed to create app role assignment: $_"
            exit 1
        }
    }
}

function Create-AIFoundryMIConnection {
    Write-Info "Creating managed identity connection: $ConnectionName..."
    
    $armAccessToken = Get-AccessToken -ResourceUri "https://management.azure.com"
    
    $connectionPayload = @{
        name = $ConnectionName
        type = "Microsoft.CognitiveServices/accounts/projects/connections"
        properties = @{
            authType = "ProjectManagedIdentity"
            audience = $script:CONNECTION_AUDIENCE
            group = "GenericProtocol"
            category = "RemoteTool"
            target = $script:CONNECTION_TARGET
            useWorkspaceManagedIdentity = $false
            isSharedToAll = $false
            sharedUserList = @()
            metadata = @{
                type = "custom_MCP"
            }
        }
    } | ConvertTo-Json -Depth 10
    
    $apiEndpoint = "https://$($script:AI_FOUNDRY_REGION).management.azure.com:443/subscriptions/$($script:AI_FOUNDRY_SUBSCRIPTION_ID)/resourcegroups/$($script:AI_FOUNDRY_RESOURCE_GROUP)/providers/Microsoft.CognitiveServices/accounts/$($script:AI_FOUNDRY_ACCOUNT_NAME)/projects/$($script:AI_FOUNDRY_PROJECT_NAME)/connections/${ConnectionName}?api-version=2025-04-01-preview"
    
    $headers = @{
        "Authorization" = "Bearer $armAccessToken"
        "Content-Type" = "application/json"
    }
    
    try {
        $response = Invoke-RestMethod -Uri $apiEndpoint -Method Put -Headers $headers -Body $connectionPayload
        
        if (-not $response) {
            Write-Error-Message "Empty response from API"
            exit 1
        }
        
        $script:AI_FOUNDRY_PROJECT_MI_CONNECTION_NAME = $response.name
        if (-not $script:AI_FOUNDRY_PROJECT_MI_CONNECTION_NAME) {
            Write-Error-Message "Failed to read connection name from response"
            Write-Error-Message "Response: $($response | ConvertTo-Json)"
            exit 1
        }
        
        $script:AI_FOUNDRY_PROJECT_MI_CONNECTION_TARGET = $response.properties.target
        if (-not $script:AI_FOUNDRY_PROJECT_MI_CONNECTION_TARGET) {
            Write-Error-Message "Failed to read connection target from response"
            Write-Error-Message "Response: $($response | ConvertTo-Json)"
            exit 1
        }
        
        $script:AI_FOUNDRY_PROJECT_MI_CONNECTION_AUDIENCE = $response.properties.audience
        if (-not $script:AI_FOUNDRY_PROJECT_MI_CONNECTION_AUDIENCE) {
            Write-Error-Message "Failed to read connection audience from response"
            Write-Error-Message "Response: $($response | ConvertTo-Json)"
            exit 1
        }
        
        Write-Info "[OK] Connection created successfully"
        Write-Info "[OK] Connection Name: $script:AI_FOUNDRY_PROJECT_MI_CONNECTION_NAME"
        Write-Info "[OK] Connection Target: $script:AI_FOUNDRY_PROJECT_MI_CONNECTION_TARGET"
        Write-Info "[OK] Connection Audience: $script:AI_FOUNDRY_PROJECT_MI_CONNECTION_AUDIENCE"
        
    } catch {
        Write-Error-Message "Failed to create connection: $_"
        exit 1
    }
}

function Show-Results {
    Write-Host ""
    
    $results = @{
        AI_FOUNDRY_PROJECT_RESOURCE_ID = $AIFoundryProjectResourceId
        AI_FOUNDRY_SUBSCRIPTION_ID = $script:AI_FOUNDRY_SUBSCRIPTION_ID
        AI_FOUNDRY_RESOURCE_GROUP = $script:AI_FOUNDRY_RESOURCE_GROUP
        AI_FOUNDRY_ACCOUNT_NAME = $script:AI_FOUNDRY_ACCOUNT_NAME
        AI_FOUNDRY_PROJECT_NAME = $script:AI_FOUNDRY_PROJECT_NAME
        AI_FOUNDRY_REGION = $script:AI_FOUNDRY_REGION
        AI_FOUNDRY_PROJECT_MI_PRINCIPAL_ID = $script:AI_FOUNDRY_PROJECT_MI_PRINCIPAL_ID
        AI_FOUNDRY_PROJECT_MI_TYPE = $script:AI_FOUNDRY_PROJECT_MI_TYPE
        AI_FOUNDRY_PROJECT_MI_TENANT_ID = $script:AI_FOUNDRY_PROJECT_MI_TENANT_ID
        AI_FOUNDRY_PROJECT_MI_CONNECTION_NAME = $script:AI_FOUNDRY_PROJECT_MI_CONNECTION_NAME
        AI_FOUNDRY_PROJECT_MI_CONNECTION_TARGET = $script:AI_FOUNDRY_PROJECT_MI_CONNECTION_TARGET
        AI_FOUNDRY_PROJECT_MI_CONNECTION_AUDIENCE = $script:AI_FOUNDRY_PROJECT_MI_CONNECTION_AUDIENCE
    }
    
    Write-Host ($results | ConvertTo-Json -Depth 10)
    Write-Host ""
}

# Main function
function Main {
    Parse-Arguments
    Check-Prerequisites
    Login-Azure
    Get-AIFoundryProjectMI
    Create-AIFoundryMIConnection
    Set-AIFoundryMIRoleAssignment
    Show-Results
}

# Run main function
Main
