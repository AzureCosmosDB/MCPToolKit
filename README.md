# Azure Cosmos DB MCP Toolkit

A Model Context Protocol (MCP) server that enables AI agents to interact with Azure Cosmos DB through natural language queries. Features enterprise-grade security with Azure Entra ID authentication, document operations, vector search, and schema discovery.

## � Quick Start Guide

Follow these 3 simple steps to get your MCP Toolkit running:

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
cd ..
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
# Deploy application (replace with your actual resource names from Step 1)
.\scripts\Quick-Deploy.ps1 `
    -ResourceGroup "your-resource-group-name" `
    -ContainerAppName "mcp-toolkit-app" `
    -RegistryName "your-registry-name"
```

### ✅ Test Your Setup

```powershell
# Get access token
$clientId = az ad app list --display-name "*mcp*" --query "[0].appId" --output tsv
$token = az account get-access-token --resource "api://$clientId" --query "accessToken" --output tsv

# Test MCP tools
$headers = @{ "Authorization" = "Bearer $token"; "Content-Type" = "application/json" }
$body = '{"jsonrpc":"2.0","method":"tools/list","id":1}'
$appUrl = az containerapp show --name "mcp-toolkit-app" --resource-group "rg-your-resource-group" --query "properties.configuration.ingress.fqdn" --output tsv
Invoke-RestMethod -Uri "https://$appUrl/mcp" -Method Post -Headers $headers -Body $body
```

**Expected result:** You should see a list of available MCP tools.

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

Add to your VS Code configuration:
```json
// .vscode/mcp.json
{
  "servers": {
    "azure-cosmos-db-mcp": {
      "type": "http",
      "url": "https://your-mcp-server.azurecontainerapps.io"
    }
  }
}
```

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
- Clear browser cache or use incognito mode
- Check that the new revision is active: `az containerapp revision list --name "mcp-toolkit-app" --resource-group "your-rg"`

**"Docker build fails"**
- Make sure Docker Desktop is running
- Make sure you're in the correct directory (MCPToolKit root)

### Get Help

For detailed troubleshooting and advanced configuration:
- [Authentication Setup Guide](docs/AUTHENTICATION-SETUP.md)
- [Testing Guide](TESTING_GUIDE.md)
- Create an issue in this repository

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