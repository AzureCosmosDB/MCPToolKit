# Azure Cosmos DB MCP Toolkit

A Model Context Protocol (MCP) server that enables AI agents to interact with Azure Cosmos DB through natural language queries. Features enterprise-grade security with Azure Entra ID authentication, document operations, vector search, and schema discovery.

> **✨ NEW: Simplified AI Foundry Integration**  
> For AI Foundry projects, use the new **one-step deployment** with `scripts/Deploy-All.ps1` which automatically configures authentication and permissions. See [AI Foundry Integration](#ai-foundry-integration) below.

## 🚀 Quick Start Guide

Follow these steps to get your MCP Toolkit running:

### Step 1: Deploy Infrastructure (5 minutes)

Click the Deploy to Azure button to create all required Azure resources:

[![Deploy to Azure](https://aka.ms/deploytoazurebutton)](https://portal.azure.com/#create/Microsoft.Template/uri/https%3A%2F%2Fraw.githubusercontent.com%2FAzureCosmosDB%2FMCPToolKit%2Fmain%2Finfrastructure%2Fdeploy-all-resources.json)

This creates:
- Container App for hosting the MCP server
- Container Registry for your app images  
- Managed Identity for secure resource access
- All necessary networking and security

**Note:** The Entra ID app will be created in Step 2 for better reliability.

### Step 2: Configure Permissions (2 minutes)

Run the automated setup script to create the Entra ID app and configure all permissions:

```powershell
.\scripts\Setup-Permissions.ps1 -ResourceGroup "your-resource-group-name"
```

This automatically:
- ✅ Creates the Entra ID app with MCP Tool Executor role
- ✅ Assigns you to the MCP role
- ✅ Configures Cosmos DB read permissions
- ✅ Configures Azure OpenAI permissions

### Step 3: Deploy Application (3 minutes)

Build and deploy your application:

```powershell
# Replace ALL values with your actual resource names from Step 1
.\scripts\Quick-Deploy.ps1 `
    -ResourceGroup "your-resource-group-name" `
    -ContainerAppName "your-container-app-name" `
    -RegistryName "your-registry-name"
```

**Example:**
```powershell
.\scripts\Quick-Deploy.ps1 `
    -ResourceGroup "rg-myproject-mcp" `
    -ContainerAppName "mcp-toolkit-xyz123" `
    -RegistryName "mcpregistryabc456"
```

> 💡 **Tip:** Find your resource names in the Azure Portal or by running:
> ```powershell
> az containerapp list --resource-group "your-resource-group-name" --query "[].{Name:name, Registry:properties.configuration.registries[0].server}" --output table
> ```

### Step 4: Get Configuration Values (1 minute)

After deployment, get the values you'll need for testing and configuration:

```powershell
# Get your Tenant ID
$tenantId = az account show --query "tenantId" --output tsv
Write-Host "Tenant ID: $tenantId" -ForegroundColor Green

# Get your App Client ID
$clientId = az ad app list --display-name "*Azure Cosmos DB MCP Toolkit API*" --query "[0].appId" --output tsv
Write-Host "App Client ID: $clientId" -ForegroundColor Green

# Get your Container App URL
$appUrl = az containerapp show --name "your-container-app-name" --resource-group "your-resource-group-name" --query "properties.configuration.ingress.fqdn" --output tsv
Write-Host "App URL: https://$appUrl" -ForegroundColor Green
```

**Save these values** - you'll need them for testing and VS Code integration.

### Step 5: Test Your Setup

#### Option A: Test via Web UI (Easiest)

1. Open your Container App URL in a browser: `https://your-app-url.azurecontainerapps.io`
2. The UI will auto-detect your Tenant ID and App Client ID
3. Click **"Sign In"** to authenticate
4. Once signed in, try the available tools from the UI

#### Option B: Test via PowerShell

```powershell
# Replace with your actual resource names
$resourceGroup = "your-resource-group-name"
$containerAppName = "your-container-app-name"

# Get App Client ID and URL
$clientId = az ad app list --display-name "*Azure Cosmos DB MCP Toolkit API*" --query "[0].appId" --output tsv
$appUrl = az containerapp show --name $containerAppName --resource-group $resourceGroup --query "properties.configuration.ingress.fqdn" --output tsv

# Get access token
$token = az account get-access-token --resource "api://$clientId" --query "accessToken" --output tsv

# Test MCP tools
$headers = @{ "Authorization" = "Bearer $token"; "Content-Type" = "application/json" }
$body = '{"jsonrpc":"2.0","method":"tools/list","id":1}'
Invoke-RestMethod -Uri "https://$appUrl/mcp" -Method Post -Headers $headers -Body $body
```

**Expected result:** You should see a JSON response with a list of available MCP tools like:
```json
{
  "jsonrpc": "2.0",
  "id": 1,
  "result": {
    "tools": [
      {"name": "list_databases", "description": "Lists databases available in the Cosmos DB account"},
      {"name": "list_collections", "description": "Lists containers (collections) for the specified database"},
      ...
    ]
  }
}
```

---

## Prerequisites

Before starting, make sure you have:
- Azure subscription with Contributor access
- Azure Cosmos DB account (existing)
- Azure OpenAI service (for vector search, optional)
- Docker Desktop installed
- Azure CLI installed and logged in (`az login`)

## What You Get

### Features
- 🔍 **Document Operations** - Query documents, full-text search, schema discovery
- 🧠 **AI-Powered Vector Search** - Semantic search using Azure OpenAI embeddings  
- 🔐 **Enterprise Security** - Azure Entra ID authentication with role-based access control
- 🐳 **Production Ready** - Containerized deployment to Azure Container Apps

### MCP Tools Available

| Tool | Description | Parameters |
|------|-------------|------------|
| **list_databases** | Lists all databases | None |
| **list_collections** | Lists containers in database | `databaseId` |
| **get_recent_documents** | Gets recent documents (1-20) | `databaseId`, `containerId`, `n` |
| **find_document_by_id** | Finds document by ID | `databaseId`, `containerId`, `id` |
| **text_search** | Full-text search on properties | `databaseId`, `containerId`, `property`, `searchPhrase`, `n` |
| **vector_search** | Semantic search with AI embeddings | `databaseId`, `containerId`, `searchText`, `vectorProperty`, `selectProperties`, `topN` |
| **get_approximate_schema** | Analyzes document structure | `databaseId`, `containerId` |

---

## Local Development

For development and testing on your local machine:

```powershell
git clone https://github.com/AzureCosmosDB/MCPToolKit.git
cd MCPToolKit

# Set bypass mode for development (no authentication required)
$env:DEV_BYPASS_AUTH = "true"

# Run with Docker Compose (includes Cosmos DB emulator)
docker-compose up -d

# Or run directly
cd src/AzureCosmosDB.MCP.Toolkit
dotnet run
```

### Test Locally
```powershell
# Health check
Invoke-RestMethod http://localhost:8080/api/health

# List tools (no auth required with bypass mode)
$body = '{"jsonrpc":"2.0","method":"tools/list","id":1}'
Invoke-RestMethod -Uri http://localhost:8080/mcp -Method Post -ContentType "application/json" -Body $body
```

---

## Configuration

### Environment Variables
| Variable | Description | Example |
|----------|-------------|---------|
| `COSMOS_ENDPOINT` | Cosmos DB endpoint | `https://myaccount.documents.azure.com:443/` |
| `OPENAI_ENDPOINT` | Azure OpenAI endpoint | `https://myopenai.openai.azure.com/` |
| `OPENAI_EMBEDDING_DEPLOYMENT` | Embedding model deployment | `text-embedding-ada-002` |
| `DEV_BYPASS_AUTH` | Bypass auth for development | `true` or `false` |

### VS Code Integration

To use your deployed MCP server with VS Code, you need to configure it with your actual values:

1. **Get your configuration values** (from Step 4 above):
   ```powershell
   $tenantId = az account show --query "tenantId" --output tsv
   $clientId = az ad app list --display-name "*Azure Cosmos DB MCP Toolkit API*" --query "[0].appId" --output tsv
   $appUrl = az containerapp show --name "your-container-app-name" --resource-group "your-resource-group-name" --query "properties.configuration.ingress.fqdn" --output tsv
   
   Write-Host "Tenant ID: $tenantId"
   Write-Host "Client ID: $clientId"
   Write-Host "App URL: https://$appUrl"
   ```

2. **Create or update `.vscode/mcp.json`** in your workspace with your actual values:
   ```json
   {
     "servers": {
       "azure-cosmos-db-mcp": {
         "type": "http",
         "url": "https://your-app-url.azurecontainerapps.io",
         "auth": {
           "type": "oauth2",
           "tenantId": "your-tenant-id",
           "clientId": "your-client-id"
         }
       }
     }
   }
   ```

3. **Reload VS Code** and test with Copilot.

### Azure AI Foundry Integration

#### One-Step Deployment (RECOMMENDED)

The new `Deploy-All.ps1` script handles everything automatically:

```powershell
cd scripts

# Deploy with AI Foundry integration
./Deploy-All.ps1 `
    -ResourceGroup "cosmos-mcp-toolkit-final" `
    -AIFoundryProjectResourceId "/subscriptions/<sub-id>/resourceGroups/<rg>/providers/Microsoft.MachineLearningServices/workspaces/<hub>/projects/<project>"
```

This script automatically:
- ✅ Builds and deploys the MCP server
- ✅ Creates Entra app with proper authentication
- ✅ Assigns Cosmos DB permissions
- ✅ Configures AI Foundry role assignments
- ✅ Displays connection configuration

After the script completes, create the MCP connection in AI Foundry:

1. Navigate to AI Foundry project → **Connections**
2. Click **"New Connection"** → **"Model Context Protocol"**
3. Configure with values from script output:
   - **Name**: `cosmos-mcp-toolkit` (or your preferred name)
   - **MCP Server URL**: From script output
   - **Authentication**: Connection (Managed Identity)
   - **Audience/Client ID**: From script output

See `scripts/README.md` for detailed step-by-step instructions.

#### Manual Setup (Alternative)

<details>
<summary>Click to expand manual setup steps</summary>

1. **Navigate to AI Foundry Portal**
   - Go to [Azure AI Foundry](https://ai.azure.com)
   - Select your project: `/build/tools`

2. **Connect a Tool**
   - Click **"Connect a tool"**
   - Select the **"Custom"** tab
   - Choose **"MCP"** as the protocol type

3. **Configure Connection**
   - **Connection Name**: `cosmos-mcp-toolkit`
   - **Target URL**: Your Container App URL
   - **Authentication**: Select **"Project Managed Identity"**
   - **Audience**: `api://your-client-id` (Client ID from deployment)

4. **Assign Permissions**
   ```powershell
   # Assign Mcp.Tool.Executor role to AI Foundry MI
   ./scripts/Setup-AIFoundry-RoleAssignment.ps1 `
       -ResourceGroup "your-resource-group" `
       -AIFoundryProjectResourceId "/subscriptions/.../projects/your-project"
   ```

5. **Save and Test** - Your AI agents can now use Cosmos DB MCP tools!

</details>
```

**What these scripts do:**
- ✅ Auto-discovers your MCP Toolkit deployment details (Container App URL, Entra App, etc.)
- ✅ Creates a managed identity connection in AI Foundry (manual UI step still required)
- ✅ Assigns the `Mcp.Tool.Executor` role to the AI Foundry project's managed identity
- ✅ Configures authentication with your Entra app

**Expected Output:**
The scripts will validate your deployment and provide the necessary configuration details for manual connection setup in the AI Foundry UI.

### Example Queries
```
@copilot List all databases in my Cosmos DB account
@copilot Show the last 10 documents from the 'orders' container
@copilot What's the schema of the 'customers' container?
@copilot Search for products similar to 'wireless headphones'
```

---

## Advanced Configuration

<details>
<summary>Manual Permission Setup (if automated script doesn't work)</summary>

### Azure Resource Permissions

The MCP Toolkit requires specific Azure roles for accessing Cosmos DB and OpenAI services:

#### Cosmos DB Permissions (Choose One)

**Option 1: Cosmos DB Built-in Data Reader (Recommended)**
```powershell
# Get managed identity ID
$managedIdentityId = az containerapp show --name "mcp-toolkit-app" --resource-group "your-rg" --query "identity.principalId" --output tsv

# Assign to Cosmos DB
az cosmosdb sql role assignment create --account-name "your-cosmos-account" --resource-group "cosmos-rg" --scope "/" --principal-id $managedIdentityId --role-definition-name "Cosmos DB Built-in Data Reader"
```

#### Azure OpenAI Permissions (For Vector Search)

**Required Role: Cognitive Services OpenAI User**
```powershell
# Get subscription ID
$subscriptionId = az account show --query "id" --output tsv

# Assign to Managed Identity
az role assignment create --assignee $managedIdentityId --role "Cognitive Services OpenAI User" --scope "/subscriptions/$subscriptionId/resourceGroups/openai-rg/providers/Microsoft.CognitiveServices/accounts/openai-account"
```

### Manual Authentication Setup

1. **Get Your Entra App Client ID**
```powershell
az ad app list --display-name "*mcp*" --query "[].{Name:displayName, ClientId:appId}" --output table
```

2. **Assign MCP Role to Users**
```powershell
az ad app role assignment create --id "your-entra-app-client-id" --principal "user@domain.com" --role "Mcp.Tool.Executor"
```

</details>

## Security

- **JWT Bearer Authentication** - Azure Entra ID token validation
- **Role-Based Access** - `Mcp.Tool.Executor` role required
- **Managed Identity** - No stored credentials in production
- **Read-Only Access** - Cannot modify data

## Troubleshooting

### Common Issues

**"403 Forbidden" when testing tools**
- Run the permissions setup script: `.\scripts\Setup-Permissions.ps1 -ResourceGroup "your-rg"`
- Make sure your Cosmos DB account exists and is accessible

**"401 Unauthorized" when testing**
- Make sure you have the `Mcp.Tool.Executor` role assigned
- Check that your access token is valid and not expired

**"App shows old version after deployment"**
- The deployment script now uses `--no-cache` to force a fresh build
- Clear browser cache or use incognito mode
- Check that the new revision is active: `az containerapp revision list --name "your-container-app-name" --resource-group "your-resource-group-name"`
- If the UI still doesn't show, verify wwwroot/index.html exists in your source: `Test-Path "src/AzureCosmosDB.MCP.Toolkit/wwwroot/index.html"`

**"Docker build fails"**
- Make sure Docker Desktop is running
- Make sure you're in the correct directory (MCPToolKit root)

### Get Help

For detailed troubleshooting and advanced configuration:
- [Authentication Setup Guide](docs/AUTHENTICATION-SETUP.md)
- [Testing Guide](TESTING_GUIDE.md)
- Create an issue in this repository

---

## Quick Reference

### Get Your Configuration Values

```powershell
# Get Tenant ID
az account show --query "tenantId" --output tsv

# Get App Client ID
az ad app list --display-name "*Azure Cosmos DB MCP Toolkit API*" --query "[0].appId" --output tsv

# Get Container App URL
az containerapp show --name "your-container-app-name" --resource-group "your-resource-group-name" --query "properties.configuration.ingress.fqdn" --output tsv

# Get all resource names in your resource group
az resource list --resource-group "your-resource-group-name" --query "[].{Name:name, Type:type}" --output table
```

### Quick Test Commands

```powershell
# Health check
$appUrl = az containerapp show --name "your-container-app-name" --resource-group "your-resource-group-name" --query "properties.configuration.ingress.fqdn" --output tsv
Invoke-RestMethod -Uri "https://$appUrl/api/health"

# Test MCP tools
$clientId = az ad app list --display-name "*Azure Cosmos DB MCP Toolkit API*" --query "[0].appId" --output tsv
$token = az account get-access-token --resource "api://$clientId" --query "accessToken" --output tsv
$headers = @{ "Authorization" = "Bearer $token"; "Content-Type" = "application/json" }
$body = '{"jsonrpc":"2.0","method":"tools/list","id":1}'
Invoke-RestMethod -Uri "https://$appUrl/mcp" -Method Post -Headers $headers -Body $body
```

### AI Foundry Integration Commands

```bash
# Connect to AI Foundry (Discovery + Role Assignment)
chmod +x scripts/create-aif-mi-connection-assign-role.sh
./scripts/create-aif-mi-connection-assign-role.sh \
  --ai-foundry-project-resource-id "/subscriptions/{sub}/resourceGroups/{rg}/providers/Microsoft.CognitiveServices/accounts/{account}/projects/{project}" \
  --connection-name "cosmos-mcp-toolkit"

.\scripts\Setup-AIFoundry-RoleAssignment.ps1 \
  -ResourceGroup "your-resource-group-name" \
  -AIFoundryProjectResourceId "/subscriptions/{sub}/resourceGroups/{rg}/providers/Microsoft.CognitiveServices/accounts/{account}/projects/{project}"
```

---

## Project Structure

```
MCPToolKit/
├── src/AzureCosmosDB.MCP.Toolkit/     # Main application (.NET 9.0)
├── infrastructure/                    # Bicep templates for Azure deployment
├── scripts/                          # Deployment and testing scripts
├── Dockerfile                        # Container configuration
└── docker-compose.yml               # Local development environment
```

## License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

## Contributing

Contributions are welcome! Please read our contributing guidelines and submit pull requests to the main branch.