# Deploy to Azure Guide

This guide explains how to use the one-click "Deploy to Azure" button to provision all necessary resources for the Azure Cosmos DB MCP Toolkit.

## 🚀 What Gets Deployed

The Deploy to Azure button creates a complete, production-ready environment:

### Azure Resources
- **Azure Cosmos DB** (serverless tier) with sample database and container
- **Azure OpenAI** service with text-embedding-ada-002 deployment  
- **Azure Container Registry** for storing container images
- **Azure Container Apps Environment** with managed identity
- **Log Analytics Workspace** for monitoring and diagnostics

### Security & RBAC
- **Managed Identity** automatically created and configured
- **Cosmos DB RBAC** permissions for data access
- **Azure OpenAI RBAC** permissions for embedding generation
- **Container Registry RBAC** permissions for image management
- **Your user account** gets admin access to all resources

### Sample Data
- Pre-configured sample database (`SampleDB`) with container (`SampleContainer`)
- Sample documents with vector embeddings for testing
- Ready-to-use schema for immediate testing

## 📋 Prerequisites

Before clicking "Deploy to Azure":

1. **Azure Subscription** with sufficient permissions to create resources
2. **Azure CLI** (optional, for post-deployment steps)
3. **Your User Object ID** (get it by running: `az ad signed-in-user show --query id -o tsv`)

## 🎯 Deployment Steps

### Step 1: Click Deploy to Azure
[![Deploy to Azure](https://aka.ms/deploytoazurebutton)](https://portal.azure.com/#create/Microsoft.Template/uri/https%3A%2F%2Fraw.githubusercontent.com%2Fsajeetharan%2FMCPToolKit%2Fmain%2Finfrastructure%2Fdeploy-all-resources.json)

### Step 2: Fill in Parameters
- **Subscription**: Select your Azure subscription
- **Resource Group**: Create new or select existing
- **Region**: Choose your preferred Azure region
- **Resource Prefix**: Customize resource names (default: mcp-toolkit)
- **Principal Id**: Your user object ID for RBAC permissions
- **Principal Type**: "User" (unless using service principal)

### Step 3: Review and Deploy
- Review the template parameters
- Check "I agree to the terms and conditions"
- Click "Purchase" to start deployment

### Step 4: Wait for Completion
Deployment typically takes 5-10 minutes. You can monitor progress in the Azure portal.

## 🔧 Post-Deployment Steps

After successful deployment, complete these steps:

### 1. Build and Deploy Container Image

```powershell
# Clone the repository (if not already done)
git clone https://github.com/sajeetharan/MCPToolKit.git
cd MCPToolKit

# Login to Azure
az login

# Get resource names from deployment
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

### 2. Test the Deployment

```bash
# Get the container app URL
az containerapp show --name $containerAppName --resource-group $resourceGroup --query "properties.configuration.ingress.fqdn" -o tsv

# Test health endpoint
curl https://your-container-app-url.azurecontainerapps.io/health
```

### 3. Configure VS Code MCP Integration

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
@copilot Show containers in SampleDB database  
@copilot Get recent documents from SampleContainer
@copilot Search for documents similar to "sample query" in SampleContainer using contentVector property
```

## 🔍 Troubleshooting

### Common Issues

#### Deployment Fails
- **Check permissions**: Ensure you have Contributor access to the subscription
- **Region capacity**: Try a different Azure region if resources are unavailable
- **Naming conflicts**: Use a unique resource prefix

#### Container App Not Starting
- **Check image**: Verify the container image was pushed successfully
- **View logs**: Use Azure portal to check container app logs
- **Health endpoint**: Test the `/health` endpoint directly

#### Authentication Errors
- **RBAC setup**: Verify your user ID was correctly configured during deployment
- **Managed identity**: Check that the managed identity has proper permissions

### Getting Help

1. **Azure Portal**: Check deployment history and resource status
2. **Container Logs**: View real-time logs in Container Apps
3. **GitHub Issues**: Open an issue with deployment details

## 🎉 What's Next?

With your Azure MCP Toolkit deployed:

1. **Explore the sample data** to understand the data structure
2. **Add your own data** to Cosmos DB with vector embeddings
3. **Customize the deployment** by modifying the Bicep templates
4. **Set up CI/CD** using the included GitHub Actions workflows
5. **Monitor usage** through Azure Monitor and Log Analytics

## 🔒 Security Considerations

The deployed resources use:
- **Managed Identity** for secure authentication
- **RBAC permissions** with least privilege access
- **HTTPS-only ingress** for encrypted traffic
- **Private networking** between Azure services
- **No secrets** stored in container images or code

Review and audit the permissions granted to ensure they meet your organization's security requirements.

## 💰 Cost Management

The deployed resources use cost-effective configurations:
- **Cosmos DB Serverless**: Pay per request, no minimum charges
- **Container Apps**: Pay per use with scale-to-zero capability
- **Azure OpenAI**: Pay per token consumption
- **Container Registry**: Basic tier for development/testing

Monitor your Azure costs and adjust scaling settings as needed.

---

🎯 **Ready to get started?** Click the Deploy to Azure button above and have your MCP Toolkit running in minutes!