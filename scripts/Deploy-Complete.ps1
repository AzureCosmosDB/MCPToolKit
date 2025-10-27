# Azure MCP Toolkit - Complete Deployment Script (PowerShell)
# This script deploys the MCP toolkit container app with external Cosmos DB and Azure OpenAI

[CmdletBinding()]
param(
    [Parameter(Mandatory=$true)]
    [string]$ResourceGroupName,
    
    [Parameter(Mandatory=$true)]
    [string]$Location,
    
    [Parameter(Mandatory=$true)]
    [string]$PrincipalId,
    
    [Parameter(Mandatory=$true)]
    [string]$CosmosEndpoint,
    
    [Parameter(Mandatory=$true)]
    [string]$OpenAIEndpoint,
    
    [Parameter(Mandatory=$true)]
    [string]$OpenAIEmbeddingDeployment,
    
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
Write-Host "   Cosmos DB Endpoint: $CosmosEndpoint"
Write-Host "   Azure OpenAI Endpoint: $OpenAIEndpoint"
Write-Host "   OpenAI Embedding Deployment: $OpenAIEmbeddingDeployment"
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

# Deploy container app resources only
Write-ColoredOutput "☁️ Deploying Azure Container App resources..." "Blue"
$deploymentName = "mcp-toolkit-deployment-$(Get-Date -Format 'yyyyMMdd-HHmmss')"

$deploymentResult = az deployment group create `
    --resource-group $ResourceGroupName `
    --template-file "infrastructure/deploy-all-resources.bicep" `
    --name $deploymentName `
    --parameters `
        resourcePrefix=$ResourcePrefix `
        location=$Location `
        principalId=$PrincipalId `
        principalType=$PrincipalType `
        cosmosEndpoint=$CosmosEndpoint `
        openaiEndpoint=$OpenAIEndpoint `
        openaiEmbeddingDeployment=$OpenAIEmbeddingDeployment

if ($LASTEXITCODE -ne 0) {
    Write-ColoredOutput "❌ Container App deployment failed" "Red"
    exit 1
}

Write-ColoredOutput "✅ Container App resources deployed successfully!" "Green"

Write-ColoredOutput "📋 Important: You need to manually assign permissions for the Managed Identity to access your external resources:" "Yellow"
Write-Host "   1. Cosmos DB: Assign 'Cosmos DB Built-in Data Contributor' role to Principal ID: $PrincipalId"
Write-Host "   2. Azure OpenAI: Assign 'Cognitive Services OpenAI User' role to Principal ID: $PrincipalId"
Write-Host ""

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
Write-Host "   Using External Cosmos DB: $CosmosEndpoint"
Write-Host "   Using External Azure OpenAI: $OpenAIEndpoint"
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
Write-Host "After configuring VS Code MCP integration and setting up RBAC permissions:"
Write-Host "- 'List all databases in my Cosmos DB account'"
Write-Host "- 'Show containers in my database'"
Write-Host "- 'Get recent documents from my container'"
Write-Host "- 'Search for documents similar to [your query]'"

Write-Host ""
Write-ColoredOutput "⚠️ Next Steps Required:" "Yellow"
Write-Host "1. Grant the Managed Identity access to your external Cosmos DB"
Write-Host "2. Grant the Managed Identity access to your external Azure OpenAI"
Write-Host "3. Test the health endpoint after RBAC setup"
Write-Host ""
Write-ColoredOutput "✨ Your Azure MCP Toolkit Container App is now ready!" "Green"