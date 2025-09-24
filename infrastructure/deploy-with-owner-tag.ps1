#!/usr/bin/env pwsh
# Deploy MCP Toolkit with Owner Tag for Azure Policy compliance

param(
    [Parameter(Mandatory=$true)]
    [string]$ResourceGroupName,
    
    [Parameter(Mandatory=$true)]
    [string]$Location,
    
    [Parameter(Mandatory=$true)]
    [string]$PrincipalId,
    
    [Parameter(Mandatory=$true)]
    [string]$OwnerTag,
    
    [Parameter(Mandatory=$false)]
    [string]$PrincipalType = "User",
    
    [Parameter(Mandatory=$false)]
    [string]$ResourcePrefix = "mcp-toolkit"
)

Write-Host "🚀 Deploying Azure Cosmos DB MCP Toolkit with Owner Tag..." -ForegroundColor Green
Write-Host "Resource Group: $ResourceGroupName" -ForegroundColor Cyan
Write-Host "Location: $Location" -ForegroundColor Cyan
Write-Host "Owner Tag: $OwnerTag" -ForegroundColor Cyan

# Check if resource group exists, create if not
$resourceGroup = az group show --name $ResourceGroupName --query name -o tsv 2>$null
if (-not $resourceGroup) {
    Write-Host "Creating resource group: $ResourceGroupName" -ForegroundColor Yellow
    az group create --name $ResourceGroupName --location $Location --tags owner=$OwnerTag
} else {
    Write-Host "Using existing resource group: $ResourceGroupName" -ForegroundColor Yellow
}

# Deploy using Bicep template (which includes the owner tag parameter)
Write-Host "Deploying resources..." -ForegroundColor Yellow

$deploymentName = "mcp-toolkit-deployment-$(Get-Date -Format 'yyyyMMdd-HHmmss')"

try {
    $result = az deployment group create `
        --resource-group $ResourceGroupName `
        --name $deploymentName `
        --template-file "deploy-all-resources.bicep" `
        --parameters `
            "resourcePrefix=$ResourcePrefix" `
            "location=$Location" `
            "principalId=$PrincipalId" `
            "principalType=$PrincipalType" `
            "ownerTag=$OwnerTag" `
        --output json | ConvertFrom-Json

    if ($LASTEXITCODE -eq 0) {
        Write-Host "✅ Deployment completed successfully!" -ForegroundColor Green
        Write-Host ""
        Write-Host "📊 Deployment Summary:" -ForegroundColor Cyan
        Write-Host "Cosmos DB Endpoint: $($result.properties.outputs.cosmosEndpoint.value)" -ForegroundColor White
        Write-Host "OpenAI Endpoint: $($result.properties.outputs.openAIEndpoint.value)" -ForegroundColor White
        Write-Host "Container App URL: $($result.properties.outputs.containerAppUrl.value)" -ForegroundColor White
        Write-Host "Container Registry: $($result.properties.outputs.containerRegistryName.value)" -ForegroundColor White
        Write-Host ""
        Write-Host "🔑 Next Steps:" -ForegroundColor Yellow
        Write-Host "1. Build and push your container image to the registry"
        Write-Host "2. Update the Container App with your custom image"
        Write-Host "3. Test the MCP server endpoints"
        Write-Host ""
        Write-Host "For detailed next steps, see: https://github.com/AzureCosmosDB/MCPToolKit/blob/main/docs/deploy-to-azure-guide.md" -ForegroundColor Cyan
    } else {
        throw "Deployment failed with exit code $LASTEXITCODE"
    }
} catch {
    Write-Error "❌ Deployment failed: $_"
    Write-Host ""
    Write-Host "🔍 Troubleshooting Tips:" -ForegroundColor Yellow
    Write-Host "1. Check Azure CLI authentication: az account show"
    Write-Host "2. Verify permissions: You need Contributor access to the subscription"
    Write-Host "3. Check deployment logs in Azure Portal"
    Write-Host "4. Try a different location if resources are unavailable"
    exit 1
}