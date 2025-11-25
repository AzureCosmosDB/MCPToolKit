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
- **Microsoft Foundry project** with an embedding model deployment (e.g., text-embedding-ada-002 or text-embedding-3-small)

> **Note**: The Microsoft Foundry project endpoint follows the format: `https://<your-project-name>.<region>.api.azureml.ms/` or the inference endpoint from your Microsoft Foundry project settings. You can find this in the Microsoft Foundry portal under your project's Settings → Endpoints.

## Deployment Options

### Option 1: PowerShell Script (Recommended)

```powershell
# Navigate to the scripts directory
cd scripts

# Run the deployment script
.\Deploy-Cosmos-MCP-Toolkit.ps1 -ResourceGroup "mcp-toolkit-rg"
```

### Option 3: Manual Bicep Deployment

```powershell
# Create resource group
az group create --name "mcp-toolkit-rg" --location "East US"

# Deploy using Bicep template
az deployment group create \
  --resource-group "mcp-toolkit-rg" \
  --template-file "deploy-all-resources.bicep" \
  --parameters \
    "cosmosEndpoint=https://yourcosmosdb.documents.azure.com:443/" \
    "aifProjectEndpoint=https://your-aif-project.openai.azure.com/" \
    "embeddingDeploymentName=text-embedding-ada-002" \
    "embeddingDimensions=1536"  # Optional: defaults to 1536 if not specified
```

## Post-Deployment Steps

After deployment, you need to:

1. **Set up RBAC permissions** for your external resources
2. **Build and deploy the container image**
3. **Test the deployment**

See the [Deploy to Azure Guide](../docs/deploy-to-azure-guide.md) for detailed post-deployment instructions.

## Files

- `deploy-all-resources.bicep` - Main Bicep template for all resources
- `deploy-all-resources.json` - ARM template (auto-generated from Bicep)
- `deploy-all-resources.parameters.template.json` - Parameter template file
- `main.bicep` - Simplified template for existing deployments
