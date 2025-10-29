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

### Step 2: Deploy Everything (5 minutes)

Run the complete deployment script - it builds, deploys, and configures everything:

```powershell
.\scripts\Deploy-All.ps1 -ResourceGroup "your-resource-group-name"
```

This automatically:
- ✅ Builds and pushes the Docker image
- ✅ Creates the Entra ID app with MCP Tool Executor role
- ✅ Assigns you to the MCP role (you can use it immediately!)
- ✅ Configures Cosmos DB and Azure Container Registry permissions
- ✅ Deploys and configures the Container App
- ✅ Displays all configuration values you need

**Example:**
```powershell
.\scripts\Deploy-All.ps1 -ResourceGroup "rg-myproject-mcp"
```

**With AI Foundry integration:**
```powershell
.\scripts\Deploy-All.ps1 `
    -ResourceGroup "rg-myproject-mcp" `
    -AIFoundryProjectResourceId "/subscriptions/<sub-id>/resourceGroups/<rg>/providers/Microsoft.CognitiveServices/accounts/<account-name>"
```

**What Deploy-All.ps1 does for you:**
- ✅ Builds and pushes Docker image to Azure Container Registry
- ✅ Creates Entra App with authentication configuration
- ✅ Creates Service Principal and configures redirect URIs
- ✅ Assigns your user account to the MCP role (you can use it immediately!)
- ✅ Configures all Azure permissions (Cosmos DB, ACR)
- ✅ Deploys and configures the Container App

> � **That's it!** One script does everything. No need to run multiple scripts or configure permissions separately.

> 💡 **Tip:** Find your resource names in the Azure Portal or by running:
> ```powershell
> az containerapp list --resource-group "your-resource-group-name" --query "[].{Name:name, Registry:properties.configuration.registries[0].server}" --output table
> ```

### Step 3: Get Configuration Values (1 minute)

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

---

## 🧪 Step 4: Test Your Deployment

Now that everything is deployed, test that it works:

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

## 🤖 AI Foundry Integration

To use the MCP Toolkit with Azure AI Foundry (for AI Agents):

### Step 1: Create AI Foundry Connection

1. Go to [AI Foundry Studio](https://ai.azure.com)
2. Open your AI Foundry project
3. Navigate to **Settings** → **Connections**
4. Click **+ New connection** → **Model Context Protocol tool**
5. Configure the connection:
   - **Name**: Give it a descriptive name (e.g., `cosmosdb-mcp`)
   - **Remote MCP Server endpoint**: Your Container App URL + `/mcp` (e.g., `https://mcp-toolkit-app.mangostone-b2cd48c2.eastus.azurecontainerapps.io/mcp`)
   - **Authentication**: Select **Microsoft Entra**
   - **Type**: Select **Project Managed Identity**
   - **Audience**: Your Entra App Client ID (e.g., `8386065d-82c4-4103-987b-e64256e2de2f`)
6. Click **Connect**

### Step 2: Assign AI Foundry Managed Identity to MCP Role

Run Deploy-All.ps1 with your AI Foundry project resource ID to automatically assign the role:

```powershell
.\scripts\Deploy-All.ps1 `
    -ResourceGroup "your-resource-group-name" `
    -AIFoundryProjectResourceId "/subscriptions/<sub-id>/resourceGroups/<rg>/providers/Microsoft.CognitiveServices/accounts/<account-name>"
```

**Or** run the standalone script:

```powershell
.\scripts\Setup-AIFoundry-RoleAssignment.ps1 `
    -AIFoundryProjectResourceId "/subscriptions/<sub-id>/resourceGroups/<rg>/providers/Microsoft.CognitiveServices/accounts/<account-name>" `
    -EntraAppClientId "your-client-id"
```

### ⚠️ Important: Token Propagation Delay

After assigning the AI Foundry managed identity to the MCP role, **Entra ID tokens can take 15-60 minutes to include the new role claims**. 

**If you get authentication errors immediately after setup:**
- ✅ **Wait 15-60 minutes** for token cache to refresh with new role assignments
- ✅ **Or recreate the AI Foundry connection** to force a fresh token
- ✅ Verify the role assignment was successful in Azure Portal → Entra ID → App Registrations

This is normal Entra ID behavior and not a bug in the toolkit.

### Step 3: Test with Python Client

Once the token has updated (15-60 minutes), test the integration:

```powershell
cd client
python agents_cosmosdb_mcp.py
```

---

## 📋 How to Get Your Configuration Values

After deployment, you'll need these values for testing and AI Foundry integration:

### Quick Commands to Get All Values

```powershell
# Navigate to your project directory
cd C:\Cosmos\MCPToolKit

# Set your resource group name
$resourceGroup = "your-resource-group-name"

# Get all configuration values
Write-Host "`n=== MCP Toolkit Configuration Values ===" -ForegroundColor Cyan

# 1. MCP Server Endpoint
$containerAppName = az containerapp list --resource-group $resourceGroup --query "[0].name" -o tsv
$mcpEndpoint = az containerapp show --name $containerAppName --resource-group $resourceGroup --query "properties.configuration.ingress.fqdn" -o tsv
Write-Host "`nMCP Server Endpoint:" -ForegroundColor Yellow
Write-Host "  https://$mcpEndpoint/mcp" -ForegroundColor Green

# 2. Audience / Client ID
$clientId = az ad app list --display-name "*Azure Cosmos DB MCP Toolkit API*" --query "[0].appId" -o tsv
Write-Host "`nAudience / Client ID:" -ForegroundColor Yellow
Write-Host "  $clientId" -ForegroundColor Green

# 3. Tenant ID
$tenantId = az account show --query "tenantId" -o tsv
Write-Host "`nTenant ID:" -ForegroundColor Yellow
Write-Host "  $tenantId" -ForegroundColor Green

# 4. Managed Identity Principal ID (for AI Foundry)
$identityId = az containerapp show --name $containerAppName --resource-group $resourceGroup --query "identity.userAssignedIdentities" -o json | ConvertFrom-Json
$principalId = ($identityId.PSObject.Properties.Value)[0].principalId
Write-Host "`nManaged Identity Principal ID:" -ForegroundColor Yellow
Write-Host "  $principalId" -ForegroundColor Green

Write-Host "`n========================================" -ForegroundColor Cyan
```

### Individual Commands

#### 1. Get MCP Server Endpoint

```powershell
# Get your Container App URL
$appUrl = az containerapp show `
    --name "your-container-app-name" `
    --resource-group "your-resource-group-name" `
    --query "properties.configuration.ingress.fqdn" `
    --output tsv

Write-Host "MCP Server Endpoint: https://$appUrl/mcp" -ForegroundColor Green
```

**Example output:** `https://mcp-toolkit-app.mangostone-b2cd48c2.eastus.azurecontainerapps.io/mcp`

#### 2. Get Audience / Client ID

```powershell
# Get your Entra App Client ID (Audience)
$clientId = az ad app list `
    --display-name "*Azure Cosmos DB MCP Toolkit API*" `
    --query "[0].appId" `
    --output tsv

Write-Host "Audience / Client ID: $clientId" -ForegroundColor Green
```

**Example output:** `a1b2c3d4-e5f6-7890-abcd-ef1234567890`

**What this is used for:**
- Bearer token audience when calling the MCP API
- AI Foundry connection configuration
- VS Code MCP client configuration

#### 3. Get Tenant ID

```powershell
# Get your Azure AD Tenant ID
$tenantId = az account show --query "tenantId" --output tsv

Write-Host "Tenant ID: $tenantId" -ForegroundColor Green
```

**Example output:** `72f988bf-86f1-41af-91ab-2d7cd011db47`

#### 4. Get Managed Identity Principal ID

```powershell
# Get Container App Managed Identity (for AI Foundry role assignments)
$containerApp = az containerapp show `
    --name "your-container-app-name" `
    --resource-group "your-resource-group-name" | ConvertFrom-Json

$identityId = ($containerApp.identity.userAssignedIdentities.PSObject.Properties.Name)[0]
$identity = az identity show --ids $identityId | ConvertFrom-Json

Write-Host "Managed Identity Principal ID: $($identity.principalId)" -ForegroundColor Green
```

**Example output:** `12345678-90ab-cdef-1234-567890abcdef`

---

## 🤖 Configuring AI Foundry MCP Connection

After deployment, configure your AI Foundry project to use the MCP Toolkit:

### Step 1: Navigate to AI Foundry

1. Go to [Azure AI Foundry Portal](https://ai.azure.com)
2. Select your project
3. Navigate to **Tools** → **Connections**

### Step 2: Create MCP Connection

1. Click **"New Connection"** or **"Connect a tool"**
2. Select **"Model Context Protocol (MCP)"** or **"Custom"** tab
3. Fill in the configuration:

| Field | Value | How to Get |
|-------|-------|------------|
| **Connection Name** | `cosmos-mcp-toolkit` | Your choice (any name) |
| **MCP Server URL** | `https://your-app.azurecontainerapps.io/mcp` | Run command above to get endpoint |
| **Authentication Method** | **Connection (Managed Identity)** | Select from dropdown |
| **Audience / Client ID** | `a1b2c3d4-e5f6-...` | Run command above to get Client ID |

### Step 3: Test the Connection

1. Click **"Test Connection"** in AI Foundry
2. You should see: ✅ Connection successful
3. View available tools: `list_databases`, `list_collections`, `get_recent_documents`, etc.

### Step 4: Use in AI Agents

Once connected, your AI agents can use natural language to query Cosmos DB:

**Example prompts:**
- "Show me the databases in Cosmos DB"
- "List collections in the 'customers' database"
- "Find documents in the 'orders' container that match 'premium customer'"
- "Search for products similar to 'wireless headphones'"

### Troubleshooting AI Foundry Connection

If the connection fails:

1. **Verify Managed Identity has permissions:**
```powershell
# Check if MI has the Mcp.Tool.Executor role
$appId = az ad app list --display-name "*Azure Cosmos DB MCP Toolkit API*" --query "[0].appId" -o tsv
$spId = az ad sp list --filter "appId eq '$appId'" --query "[0].id" -o tsv

# Get AI Foundry project MI
$aifProject = "/subscriptions/<sub-id>/resourceGroups/<rg>/providers/Microsoft.MachineLearningServices/workspaces/<project-name>"
$aifMI = az ml workspace show --ids $aifProject --query "identity.principalId" -o tsv

# List role assignments
az rest --method GET --uri "https://graph.microsoft.com/v1.0/servicePrincipals/$aifMI/appRoleAssignments"
```

2. **Assign the role manually if needed:**
```powershell
.\scripts\Setup-AIFoundry-RoleAssignment.ps1 `
    -AIFoundryProjectResourceId "<your-aif-project-resource-id>" `
    -EntraAppClientId "<your-client-id>"
```

3. **Verify the MCP endpoint is accessible:**
```powershell
# Test health endpoint
Invoke-RestMethod -Uri "https://your-app.azurecontainerapps.io/health"
```

---

## Prerequisites

Before starting, make sure you have:
- Azure subscription with Contributor access
- Azure Cosmos DB account (existing)
- AI Foundry project with embedding model deployed (for vector search, optional)
- Docker Desktop installed
- Azure CLI installed and logged in (`az login`)

> **Note**: This toolkit works with **AI Foundry** (Azure's modern AI platform). Legacy standalone Azure OpenAI resources are also supported but AI Foundry is recommended.

## What You Get

### Features
- 🔍 **Document Operations** - Query documents, full-text search, schema discovery
- 🧠 **AI-Powered Vector Search** - Semantic search using AI Foundry embeddings  
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
| `COSMOS_ENDPOINT` | Cosmos DB account endpoint | `https://myaccount.documents.azure.com:443/` |
| `OPENAI_ENDPOINT` | AI Foundry project endpoint (or legacy Azure OpenAI) | `https://myproject.openai.azure.com/` |
| `OPENAI_EMBEDDING_DEPLOYMENT` | Embedding model deployment name | `text-embedding-ada-002` |

> **Note**: `OPENAI_ENDPOINT` refers to your **AI Foundry project endpoint** (recommended) or legacy Azure OpenAI endpoint. AI Foundry projects expose OpenAI-compatible endpoints that work seamlessly with the Azure.AI.OpenAI SDK.
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
    -ResourceGroup "<your-resource-group-name>" `
    -AIFoundryProjectResourceId "/subscriptions/<subscription-id>/resourceGroups/<resource-group>/providers/Microsoft.MachineLearningServices/workspaces/<hub-name>/projects/<project-name>"
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

The MCP Toolkit requires specific Azure roles for accessing Cosmos DB and AI Foundry services:

#### Cosmos DB Permissions (Choose One)

**Option 1: Cosmos DB Built-in Data Reader (Recommended)**
```powershell
# Get managed identity ID
$managedIdentityId = az containerapp show --name "<your-container-app-name>" --resource-group "<your-resource-group-name>" --query "identity.principalId" --output tsv

# Assign to Cosmos DB
az cosmosdb sql role assignment create --account-name "<your-cosmos-account-name>" --resource-group "<your-resource-group-name>" --scope "/" --principal-id $managedIdentityId --role-definition-name "Cosmos DB Built-in Data Reader"
```

#### AI Foundry Permissions (For Vector Search)

**Required Role: Cognitive Services OpenAI User**
```powershell
# Get subscription ID
$subscriptionId = az account show --query "id" --output tsv

# Assign to Managed Identity
az role assignment create --assignee $managedIdentityId --role "Cognitive Services OpenAI User" --scope "/subscriptions/$subscriptionId/resourceGroups/<your-resource-group-name>/providers/Microsoft.MachineLearningServices/workspaces/<hub-name>/projects/<project-name>"
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
- Verify your user is assigned to the MCP role: Run Deploy-All.ps1 which automatically assigns you
- Make sure your Cosmos DB account exists and is accessible
- Check the deployment output showed your user was assigned successfully

**"401 Unauthorized" when testing**
- Make sure you have the `Mcp.Tool.Executor` role assigned
- Check that your access token is valid and not expired
- Re-run Deploy-All.ps1 to ensure all permissions are configured

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