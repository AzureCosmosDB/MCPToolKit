# Azure Cosmos DB MCP Toolkit Deployment Script
param(
    [Parameter(Mandatory=$true)]
    [string]$ResourceGroup,
    
    [Parameter(Mandatory=$false)]
    [string]$Location = "eastus"
)

$ErrorActionPreference = "Stop"

# Configuration
$AppName = "mcp-demo-app"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path

# Entra App Configuration
$EntraAppName = "Azure Cosmos DB MCP Toolkit API"

function Write-Info {
    param([string]$Message)
    Write-Host "[INFO] $Message" -ForegroundColor Green
}

function Write-Warn {
    param([string]$Message)
    Write-Host "[WARN] $Message" -ForegroundColor Yellow
}

function Write-Error {
    param([string]$Message)
    Write-Host "[ERROR] $Message" -ForegroundColor Red
}

function Show-Usage {
    Write-Host "Usage: .\Deploy-CosmosMcpServer.ps1 -ResourceGroup <resource_group> [-Location <location>]"
    Write-Host ""
    Write-Host "Parameters:"
    Write-Host "  -ResourceGroup <name>     Resource group name for the deployment"
    Write-Host "  -Location <location>      Azure region (default: eastus)"
    Write-Host ""
    Write-Host "Example:"
    Write-Host "  .\Deploy-CosmosMcpServer.ps1 -ResourceGroup 'rg-mcp-toolkit-demo' -Location 'eastus'"
    Write-Host ""
}

function Test-Prerequisites {
    Write-Info "Checking prerequisites..."

    # Check Azure CLI
    try {
        az --version | Out-Null
    }
    catch {
        Write-Error "Azure CLI is not installed. Please install it from https://docs.microsoft.com/en-us/cli/azure/install-azure-cli"
        exit 1
    }

    # Check Docker
    try {
        docker --version | Out-Null
    }
    catch {
        Write-Error "Docker is not installed. Please install Docker to continue."
        exit 1
    }

    Write-Info "Prerequisites check passed"
}

function Connect-Azure {
    Write-Info "Checking Azure CLI login status..."

    try {
        $account = az account show --query "id" --output tsv 2>$null
        if (-not $account) {
            throw "Not logged in"
        }
    }
    catch {
        Write-Info "Not logged in to Azure CLI. Running 'az login'..."
        az login
    }

    # Get current subscription details
    $script:SubscriptionId = az account show --query "id" --output tsv
    $script:TenantId = az account show --query "tenantId" --output tsv
    
    Write-Info "Using subscription: $SubscriptionId"
    Write-Info "Using tenant: $TenantId"
}

function New-ResourceGroup {
    Write-Info "Creating resource group: $ResourceGroup"

    az group create `
        --name $ResourceGroup `
        --location $Location `
        --output table
}

function Deploy-Infrastructure {
    Write-Info "Deploying Azure Container Apps and Entra App..."

    $DeploymentName = "mcp-deployment-$(Get-Date -Format 'yyyyMMddHHmmss')"
    $TemplateFile = Join-Path $ScriptDir "..\infrastructure\main.bicep"
    
    az deployment group create `
        --resource-group $ResourceGroup `
        --template-file $TemplateFile `
        --name $DeploymentName `
        --output table

    $script:DeploymentName = $DeploymentName
    Write-Info "Infrastructure deployment completed!"
}

function Get-DeploymentOutputs {
    Write-Info "Getting deployment outputs..."

    # Get outputs
    $script:ContainerRegistry = az deployment group show `
        --resource-group $ResourceGroup `
        --name $DeploymentName `
        --query "properties.outputs.CONTAINER_REGISTRY_LOGIN_SERVER.value" `
        --output tsv

    $script:ContainerAppUrl = az deployment group show `
        --resource-group $ResourceGroup `
        --name $DeploymentName `
        --query "properties.outputs.CONTAINER_APP_URL.value" `
        --output tsv

    $script:EntraAppClientId = az deployment group show `
        --resource-group $ResourceGroup `
        --name $DeploymentName `
        --query "properties.outputs.ENTRA_APP_CLIENT_ID.value" `
        --output tsv

    $script:EntraAppObjectId = az deployment group show `
        --resource-group $ResourceGroup `
        --name $DeploymentName `
        --query "properties.outputs.ENTRA_APP_OBJECT_ID.value" `
        --output tsv

    $script:EntraAppSpObjectId = az deployment group show `
        --resource-group $ResourceGroup `
        --name $DeploymentName `
        --query "properties.outputs.ENTRA_APP_SERVICE_PRINCIPAL_ID.value" `
        --output tsv

    $script:EntraAppRoleId = az deployment group show `
        --resource-group $ResourceGroup `
        --name $DeploymentName `
        --query "properties.outputs.ENTRA_APP_ROLE_ID.value" `
        --output tsv

    $script:ContainerAppPrincipalId = az deployment group show `
        --resource-group $ResourceGroup `
        --name $DeploymentName `
        --query "properties.outputs.CONTAINER_APP_PRINCIPAL_ID.value" `
        --output tsv

    Write-Info "Container Registry: $ContainerRegistry"
    Write-Info "Container App URL: $ContainerAppUrl"
    Write-Info "Entra App Client ID: $EntraAppClientId"
}

function Build-PushImage {
    Write-Info "Building and pushing container image..."

    # Get the container registry name (without .azurecr.io)
    $RegistryName = $ContainerRegistry.Split('.')[0]
    
    # Build and push using ACR build
    $SourcePath = Join-Path $ScriptDir ".."
    $DockerfilePath = Join-Path $SourcePath "Dockerfile"
    
    az acr build `
        --registry $RegistryName `
        --image "mcp-toolkit:latest" `
        --file $DockerfilePath `
        $SourcePath

    Write-Info "Container image built and pushed successfully!"
}

function Update-ContainerApp {
    Write-Info "Updating container app with new image..."

    az containerapp update `
        --name $AppName `
        --resource-group $ResourceGroup `
        --image "$ContainerRegistry/mcp-toolkit:latest"

    Write-Info "Container app updated successfully!"
}

function Show-ContainerLogs {
    Write-Info "Waiting 10 seconds for Azure Container App to initialize then fetching logs..."
    Start-Sleep -Seconds 10

    Write-Host ""
    Write-Info "Azure Container App logs:"
    Write-Host "Begin_Azure_Container_App_Logs ---->"
    
    try {
        az containerapp logs show `
            --name $AppName `
            --resource-group $ResourceGroup `
            --tail 20 `
            --output table
        Write-Host "<---- End_Azure_Container_App_Logs"
        Write-Host ""
    }
    catch {
        Write-Warn "Could not retrieve logs. The Azure Container App might still be starting up."
        Write-Info "Check logs later with: az containerapp logs show --name $AppName --resource-group $ResourceGroup --tail 20"
    }
}

function Show-DeploymentSummary {
    Write-Info "Deployment Summary:"
    
    # Create summary object
    $summary = @{
        MCP_SERVER_URI = $ContainerAppUrl
        ENTRA_APP_CLIENT_ID = $EntraAppClientId
        ENTRA_APP_OBJECT_ID = $EntraAppObjectId
        ENTRA_APP_SP_OBJECT_ID = $EntraAppSpObjectId
        ENTRA_APP_ROLE_VALUE = "Mcp.Tool.Executor"
        ENTRA_APP_ROLE_ID = $EntraAppRoleId
        ACA_MI_PRINCIPAL_ID = $ContainerAppPrincipalId
        RESOURCE_GROUP = $ResourceGroup
        SUBSCRIPTION_ID = $SubscriptionId
        TENANT_ID = $TenantId
        LOCATION = $Location
    }
    
    $summaryJson = $summary | ConvertTo-Json -Depth 10
    Write-Host $summaryJson
    
    $DeploymentInfoFile = Join-Path $ScriptDir "deployment-info.json"
    $summaryJson | Out-File -FilePath $DeploymentInfoFile -Encoding UTF8
    Write-Info "Deployment information written to: $DeploymentInfoFile"
    
    Write-Host ""
    Write-Info "🎉 Deployment completed successfully!"
    Write-Info "📱 Test your MCP server at: $ContainerAppUrl"
    Write-Info "🔐 Entra App Client ID: $EntraAppClientId"
    Write-Info "📄 Full deployment details: $DeploymentInfoFile"
}

# Main execution
try {
    Write-Info "Starting Azure Cosmos DB MCP Toolkit deployment..."

    Write-Info "Using Resource Group: $ResourceGroup"
    Write-Info "Using Location: $Location"

    Test-Prerequisites
    Connect-Azure
    New-ResourceGroup
    Deploy-Infrastructure
    Get-DeploymentOutputs
    Build-PushImage
    Update-ContainerApp
    Show-ContainerLogs
    Show-DeploymentSummary

    Write-Info "Deployment completed successfully!"
}
catch {
    Write-Error "Deployment failed: $($_.Exception.Message)"
    exit 1
}