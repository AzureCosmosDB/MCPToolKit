# Azure MCP Toolkit - Complete Deployment Script (PowerShell)
# This script deploys all resources and configures the MCP toolkit

[CmdletBinding()]
param(
    [Parameter(Mandatory=$true)]
    [string]$ResourceGroupName,
    
    [Parameter(Mandatory=$true)]
    [string]$Location,
    
    [Parameter(Mandatory=$true)]
    [string]$PrincipalId,
    
    [Parameter(Mandatory=$false)]
    [ValidateSet("User", "ServicePrincipal")]
    [string]$PrincipalType = "User",
    
    [Parameter(Mandatory=$false)]
    [string]$ResourcePrefix = "mcp-toolkit"
)

# Function to write colored output
function Write-ColoredOutput {
    param(
        [string]$Message,
        [string]$Color = "White"
    )
    
    $colorCode = switch ($Color) {
        "Red" { [System.ConsoleColor]::Red }
        "Green" { [System.ConsoleColor]::Green }
        "Yellow" { [System.ConsoleColor]::Yellow }
        "Blue" { [System.ConsoleColor]::Blue }
        "Cyan" { [System.ConsoleColor]::Cyan }
        default { [System.ConsoleColor]::White }
    }
    
    Write-Host $Message -ForegroundColor $colorCode
}

Write-ColoredOutput "🚀 Azure MCP Toolkit - Complete Deployment" "Green"
Write-ColoredOutput "══════════════════════════════════════════════════════════════" "Green"

Write-ColoredOutput "📋 Deployment Configuration:" "Blue"
Write-Host "   Resource Group: $ResourceGroupName"
Write-Host "   Location: $Location"
Write-Host "   Principal ID: $PrincipalId"
Write-Host "   Principal Type: $PrincipalType"
Write-Host "   Resource Prefix: $ResourcePrefix"
Write-Host ""

# Check if Azure CLI is logged in
Write-ColoredOutput "🔍 Checking Azure CLI authentication..." "Blue"
try {
    $accountInfo = az account show --query "{name:name, user:user.name}" -o json | ConvertFrom-Json
    Write-ColoredOutput "✅ Logged in to Azure" "Green"
    Write-Host "   Account: $($accountInfo.name)"
    Write-Host "   User: $($accountInfo.user)"
}
catch {
    Write-ColoredOutput "❌ Not logged in to Azure CLI. Please run 'az login' first." "Red"
    exit 1
}

# Create resource group
Write-ColoredOutput "📦 Creating resource group..." "Blue"
az group create --name $ResourceGroupName --location $Location --tags Environment=Production Application=MCP-Toolkit

# Deploy all resources
Write-ColoredOutput "☁️ Deploying Azure resources..." "Blue"
$deploymentName = "mcp-toolkit-deployment-$(Get-Date -Format 'yyyyMMdd-HHmmss')"

$deploymentResult = az deployment group create `
    --resource-group $ResourceGroupName `
    --template-file "infrastructure/deploy-all-resources.bicep" `
    --name $deploymentName `
    --parameters `
        resourcePrefix=$ResourcePrefix `
        location=$Location `
        principalId=$PrincipalId `
        principalType=$PrincipalType

if ($LASTEXITCODE -ne 0) {
    Write-ColoredOutput "❌ Resource deployment failed" "Red"
    exit 1
}

Write-ColoredOutput "✅ Resources deployed successfully!" "Green"

# Get deployment outputs
Write-ColoredOutput "📋 Getting deployment outputs..." "Blue"
$outputs = az deployment group show --resource-group $ResourceGroupName --name $deploymentName --query "properties.outputs" -o json | ConvertFrom-Json

$containerRegistryName = $outputs.containerRegistryName.value
$containerAppName = $outputs.postDeploymentInfo.value.containerApp
$acrLoginServer = $outputs.containerRegistryLoginServer.value
$containerAppUrl = $outputs.containerAppUrl.value

Write-Host "   Container Registry: $containerRegistryName"
Write-Host "   Container App: $containerAppName"
Write-Host "   Container App URL: $containerAppUrl"

# Check if Docker is available for building the image
$dockerAvailable = Get-Command docker -ErrorAction SilentlyContinue
if ($dockerAvailable) {
    Write-ColoredOutput "🐳 Building and deploying container image..." "Blue"
    
    # Login to ACR
    az acr login --name $containerRegistryName
    
    # Build image
    $imageName = "$acrLoginServer/mcp-toolkit:latest"
    docker build -t $imageName .
    
    if ($LASTEXITCODE -ne 0) {
        Write-ColoredOutput "❌ Docker build failed" "Red"
        exit 1
    }
    
    # Push image
    docker push $imageName
    
    if ($LASTEXITCODE -ne 0) {
        Write-ColoredOutput "❌ Docker push failed" "Red"
        exit 1
    }
    
    Write-ColoredOutput "✅ Image pushed: $imageName" "Green"
    
    # Update container app
    Write-ColoredOutput "🚀 Updating container app..." "Blue"
    az containerapp update `
        --name $containerAppName `
        --resource-group $ResourceGroupName `
        --image $imageName
    
    if ($LASTEXITCODE -ne 0) {
        Write-ColoredOutput "❌ Container app update failed" "Red"
        exit 1
    }
    
    Write-ColoredOutput "✅ Container app updated successfully!" "Green"
    $dockerDeployed = $true
} else {
    Write-ColoredOutput "⚠️ Docker not found. You'll need to build and deploy the container image manually." "Yellow"
    Write-Host "   1. Build: docker build -t $acrLoginServer/mcp-toolkit:latest ."
    Write-Host "   2. Login: az acr login --name $containerRegistryName"
    Write-Host "   3. Push: docker push $acrLoginServer/mcp-toolkit:latest"
    Write-Host "   4. Update: az containerapp update --name $containerAppName --resource-group $ResourceGroupName --image $acrLoginServer/mcp-toolkit:latest"
    $dockerDeployed = $false
}

# Display summary
Write-Host ""
Write-ColoredOutput "🎉 Deployment Complete!" "Green"
Write-ColoredOutput "══════════════════════════════════════════════════════════════" "Green"
Write-ColoredOutput "📊 Resource Summary:" "Blue"
Write-Host "   Resource Group: $ResourceGroupName"
Write-Host "   Container App URL: $containerAppUrl"
Write-Host "   Health Check: $containerAppUrl/health"
Write-Host ""

# Test health endpoint if Docker was available
if ($dockerDeployed) {
    Write-ColoredOutput "🔍 Testing health endpoint (waiting 30 seconds for startup)..." "Blue"
    Start-Sleep -Seconds 30
    
    try {
        $healthResponse = Invoke-WebRequest -Uri "$containerAppUrl/health" -UseBasicParsing -TimeoutSec 10
        if ($healthResponse.StatusCode -eq 200) {
            Write-ColoredOutput "✅ Health check passed!" "Green"
        } else {
            Write-ColoredOutput "⚠️ Health check returned status: $($healthResponse.StatusCode)" "Yellow"
        }
    } catch {
        Write-ColoredOutput "⚠️ Health check failed (container may still be starting)" "Yellow"
        Write-Host "   Try again in a few minutes: $containerAppUrl/health"
    }
}

Write-Host ""
Write-ColoredOutput "📋 VS Code MCP Configuration:" "Yellow"
Write-Host "Add this to your .vscode/mcp.json file:"
Write-Host ""

$mcpConfig = @"
{
  "servers": {
    "azure-cosmos-db-mcp": {
      "type": "http",
      "url": "$containerAppUrl"
    }
  }
}
"@

Write-Host $mcpConfig

Write-Host ""
Write-ColoredOutput "🧪 Test Commands for GitHub Copilot:" "Yellow"
Write-Host "After configuring VS Code MCP integration:"
Write-Host "- 'List all databases in my Cosmos DB account'"
Write-Host "- 'Show containers in SampleDB database'"
Write-Host "- 'Get recent documents from SampleContainer'"
Write-Host "- 'Search for documents similar to [your query]'"

Write-Host ""
Write-ColoredOutput "✨ Your Azure MCP Toolkit is now ready to use!" "Green"