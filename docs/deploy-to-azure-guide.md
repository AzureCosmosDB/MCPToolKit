# Deploy to Azure Guide

This guide explains how to deploy the Azure Cosmos DB MCP Toolkit Container App to Azure using your existing Cosmos DB and Azure OpenAI resources.

## 🚀 One-Click Deploy to Azure

[![Deploy to Azure](https://aka.ms/deploytoazurebutton)](https://portal.azure.com/#create/Microsoft.Template/uri/https%3A%2F%2Fraw.githubusercontent.com%2FAzureCosmosDB%2FMCPToolKit%2Fmain%2Finfrastructure%2Fdeploy-all-resources.json)

**Click the button above for instant deployment with guided setup in Azure Portal!**

### Required Information for One-Click Deployment
- **Resource Group** - Create new or select existing
- **Resource Prefix** - Unique name for your resources (e.g., "mcp-demo")
- **Principal ID** - Your Azure AD Object ID ([How to get this](#getting-your-principal-id))
- **Location** - Azure region for deployment
- **Cosmos Endpoint** - Your existing Cosmos DB URL (e.g., `https://mycosmosdb.documents.azure.com:443/`)
- **OpenAI Endpoint** - Your Azure OpenAI service URL (e.g., `https://myopenai.openai.azure.com/`)
- **OpenAI Embedding Deployment** - Your embedding model name (e.g., `text-embedding-ada-002`)

### Getting Your Principal ID

**Azure CLI:**
```bash
az ad signed-in-user show --query id -o tsv
```

**Azure Portal:**
1. Go to Azure Active Directory → Users
2. Search for your account → Copy "Object ID"

**PowerShell:**
```powershell
(Get-AzADUser -UserPrincipalName (Get-AzContext).Account.Id).Id
```

## 🛠️ Alternative: Script-Based Deployment

If you prefer automated scripting over the Azure Portal:

## 🚀 What Gets Deployed

The deployment creates only the necessary infrastructure for running the MCP Toolkit:

### Azure Resources Created
- **Azure Container Registry** for storing container images
- **Azure Container Apps Environment** with managed identity
- **Azure Container App** for running the MCP Toolkit
- **Managed Identity** for secure authentication

### Prerequisites (External Resources)
You must already have:
- **Azure Cosmos DB** account with appropriate databases and containers
- **Azure OpenAI** service with text-embedding-ada-002 deployment

### Security & RBAC
- **Managed Identity** automatically created and configured for Container Registry access
- **Manual RBAC setup required** for Cosmos DB and Azure OpenAI access
- **Your user account** gets admin access to deployed resources

## 📋 Prerequisites

Before deploying the MCP Toolkit:

1. **Azure Subscription** with sufficient permissions to create Container Apps resources
2. **Existing Azure Cosmos DB** account with your data
   - Note the Cosmos DB endpoint (e.g., `https://mycosmosdb.documents.azure.com:443/`)
3. **Existing Azure OpenAI** service with text-embedding-ada-002 deployment
   - Note the Azure OpenAI endpoint (e.g., `https://myopenai.openai.azure.com/`)
   - Note the embedding deployment name (usually `text-embedding-ada-002`)
4. **Azure CLI** (optional, for command-line deployment)
5. **Your User Object ID** (get it by running: `az ad signed-in-user show --query id -o tsv`)

## 🎯 Deployment Steps

Choose your preferred deployment method:

### Option 1: One-Click Azure Portal Deployment

Use the Deploy to Azure button at the top of this guide for the easiest experience.

### Option 2: Command Line Deployment

#### Using PowerShell
```powershell
# Set required parameters
$resourceGroup = "mcp-toolkit-rg"
$location = "East US"
$principalId = "your-user-object-id"
$cosmosEndpoint = "https://yourcosmosdb.documents.azure.com:443/"
$openaiEndpoint = "https://youropenai.openai.azure.com/"
$embeddingDeployment = "text-embedding-ada-002"

# Run deployment script
.\scripts\Deploy-CosmosMcpServer.ps1 `
    -ResourceGroup $resourceGroup `
    -CosmosEndpoint $cosmosEndpoint `
    -OpenAIEndpoint $openaiEndpoint `
    -OpenAIEmbeddingDeployment $embeddingDeployment
```

#### Using Bash
```bash
# Run deployment script
./scripts/deploy-cosmos-mcp-server.sh --resource-group $RESOURCE_GROUP_NAME
```

## 🔧 Post-Deployment Steps

After successful deployment, complete these steps:

### 1. Set Up RBAC Permissions

**Grant Managed Identity access to your Cosmos DB:**
```bash
# Get the managed identity principal ID from deployment outputs
MANAGED_IDENTITY_ID="your-managed-identity-principal-id"
COSMOS_ACCOUNT_NAME="your-cosmos-account-name"
RESOURCE_GROUP="your-cosmos-resource-group"

# Assign Cosmos DB Built-in Data Contributor role
az cosmosdb sql role assignment create \
    --account-name $COSMOS_ACCOUNT_NAME \
    --resource-group $RESOURCE_GROUP \
    --role-definition-id "00000000-0000-0000-0000-000000000002" \
    --principal-id $MANAGED_IDENTITY_ID \
    --scope "/dbs/YourDatabaseName"
```

**Grant Managed Identity access to your Azure OpenAI:**
```bash
# Assign Cognitive Services OpenAI User role
OPENAI_RESOURCE_GROUP="your-openai-resource-group"
OPENAI_ACCOUNT_NAME="your-openai-account-name"

az role assignment create \
    --role "Cognitive Services OpenAI User" \
    --assignee $MANAGED_IDENTITY_ID \
    --scope "/subscriptions/$(az account show --query id -o tsv)/resourceGroups/$OPENAI_RESOURCE_GROUP/providers/Microsoft.CognitiveServices/accounts/$OPENAI_ACCOUNT_NAME"
```

### 2. Build and Deploy Container Image

```powershell
# Clone the repository (if not already done)
git clone https://github.com/AzureCosmosDB/MCPToolKit.git
cd MCPToolKit

# Login to Azure
az login

# Get resource names from deployment outputs
$resourceGroup = "your-resource-group-name"
$acrName = "mcptoolkitacr12345"  # Replace with actual ACR name
$containerAppName = "mcp-toolkit-app"  # Replace with actual app name

# Build and push image
az acr login --name $acrName
docker build -t "$acrName.azurecr.io/mcp-toolkit:latest" .
docker push "$acrName.azurecr.io/mcp-toolkit:latest"

# Update container app
az containerapp update `
  --name $containerAppName `
  --resource-group $resourceGroup `
  --image "$acrName.azurecr.io/mcp-toolkit:latest"
```

### 3. Test the Deployment

```bash
# Get the container app URL
az containerapp show --name $containerAppName --resource-group $resourceGroup --query "properties.configuration.ingress.fqdn" -o tsv

# Test health endpoint
curl https://your-container-app-url.azurecontainerapps.io/health
```

### 4. Configure VS Code MCP Integration

Add to your `.vscode/mcp.json`:

```json
{
  "servers": {
    "azure-cosmos-db-mcp": {
      "type": "http",
      "url": "https://your-container-app-url.azurecontainerapps.io"
    }
  }
}
```

## 🧪 Testing Your Deployment

After configuration, test with GitHub Copilot Chat:

```
@copilot List all databases in my Cosmos DB account
@copilot Show containers in my database  
@copilot Get recent documents from my container
@copilot Search for documents similar to "sample query" using vector search
```

## 🔍 Troubleshooting

### Common Issues

#### Deployment Fails
- **Check permissions**: Ensure you have Contributor access to the subscription
- **Region capacity**: Try a different Azure region if resources are unavailable
- **Naming conflicts**: Use a unique resource prefix
- **External resource access**: Verify your Cosmos DB and Azure OpenAI endpoints are correct

#### Authentication Errors
- **RBAC setup**: Verify the managed identity has proper permissions to your external resources
- **Endpoint URLs**: Check that Cosmos DB and Azure OpenAI endpoints are correct
- **Managed identity**: Ensure the managed identity was created successfully

#### Container App Not Starting
- **Check image**: Verify the container image was pushed successfully
- **View logs**: Use Azure portal to check container app logs
- **Health endpoint**: Test the `/health` endpoint directly
- **Environment variables**: Verify external resource endpoints are configured correctly

### Getting Help

1. **Azure Portal**: Check deployment history and resource status
2. **Container Logs**: View real-time logs in Container Apps
3. **GitHub Issues**: Open an issue with deployment details

## 🎉 What's Next?

With your Azure MCP Toolkit deployed:

1. **Set up RBAC permissions** for your existing Cosmos DB and Azure OpenAI resources
2. **Explore your data** using the MCP toolkit with GitHub Copilot
3. **Customize the deployment** by modifying the Bicep templates
4. **Set up CI/CD** using the included GitHub Actions workflows
5. **Monitor usage** through Azure Monitor and Container App logs

## 🔒 Security Considerations

The deployed resources use:
- **Managed Identity** for secure authentication
- **RBAC permissions** with least privilege access (manual setup required)
- **HTTPS-only ingress** for encrypted traffic
- **Private networking** between Azure services
- **No secrets** stored in container images or code

You must manually configure RBAC permissions for your external Cosmos DB and Azure OpenAI resources to ensure security.

## 💰 Cost Management

The deployed resources use cost-effective configurations:
- **Container Apps**: Pay per use with scale-to-zero capability
- **Container Registry**: Basic tier for development/testing
- **No Cosmos DB or Azure OpenAI costs**: Uses your existing resources

Monitor your Azure costs for the container infrastructure. The external Cosmos DB and Azure OpenAI costs depend on your existing resource usage patterns.

---

🎯 **Ready to get started?** Click the Deploy to Azure button above or use the command-line scripts to deploy your MCP Toolkit Container App!