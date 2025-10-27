# Infrastructure Deployment

This directory contains the infrastructure templates for deploying the Azure MCP Toolkit Container App.

## What Gets Deployed

The infrastructure templates create only the necessary resources for running the MCP Toolkit:

- **Azure Container Registry** for storing container images
- **Azure Container Apps Environment** with managed identity
- **Azure Container App** for running the MCP Toolkit
- **Managed Identity** for secure authentication

## Prerequisites

You must already have:
- **Azure Cosmos DB** account with your data
- **Azure OpenAI** service with text-embedding-ada-002 deployment

## Deployment Options

### Option 1: PowerShell Script (Recommended)

```powershell
# Navigate to the scripts directory
cd scripts

# Run the deployment script
./Deploy-Complete.ps1 `
    -ResourceGroupName "mcp-toolkit-rg" `
    -Location "East US" `
    -PrincipalId "your-user-object-id" `
    -CosmosEndpoint "https://yourcosmosdb.documents.azure.com:443/" `
    -OpenAIEndpoint "https://youropenai.openai.azure.com/" `
    -OpenAIEmbeddingDeployment "text-embedding-ada-002"
```

### Option 2: Bash Script

```bash
# Set environment variables
export RESOURCE_GROUP_NAME="mcp-toolkit-rg"
export LOCATION="East US"
export PRINCIPAL_ID="your-user-object-id"
export COSMOS_ENDPOINT="https://yourcosmosdb.documents.azure.com:443/"
export OPENAI_ENDPOINT="https://youropenai.openai.azure.com/"
export OPENAI_EMBEDDING_DEPLOYMENT="text-embedding-ada-002"

# Run deployment script
./scripts/deploy-complete.sh
```

### Option 3: Manual Bicep Deployment

```powershell
# Get your user object ID
$principalId = az ad signed-in-user show --query id -o tsv

# Create resource group
az group create --name "mcp-toolkit-rg" --location "East US"

# Deploy using Bicep template
az deployment group create \
  --resource-group "mcp-toolkit-rg" \
  --template-file "deploy-all-resources.bicep" \
  --parameters \
    "principalId=$principalId" \
    "cosmosEndpoint=https://yourcosmosdb.documents.azure.com:443/" \
    "openaiEndpoint=https://youropenai.openai.azure.com/" \
    "openaiEmbeddingDeployment=text-embedding-ada-002"
```

## Post-Deployment Steps

After deployment, you need to:

1. **Set up RBAC permissions** for your external resources
2. **Build and deploy the container image**
3. **Test the deployment**

See the [Deploy to Azure Guide](../docs/deploy-to-azure-guide.md) for detailed post-deployment instructions.

## Azure Policy Owner Tag Support

The Bicep template includes an `ownerTag` parameter for organizations that require owner tags on all resources. If you encounter policy errors, make sure to provide the `ownerTag` parameter during deployment.

## Files

- `deploy-all-resources.bicep` - Main Bicep template for all resources
- `deploy-all-resources.json` - ARM template (auto-generated from Bicep)
- `deploy-all-resources.parameters.template.json` - Parameter template file
- `main.bicep` - Simplified template for existing deployments
- `deploy-with-owner-tag.ps1` - PowerShell script for organizations with owner tag policies