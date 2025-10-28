# Azure Cosmos DB MCP Toolkit# Azure Cosmos DB MCP Toolkit



A Model Context Protocol (MCP) server that enables AI agents to interact with Azure Cosmos DB through natural language queries. Features enterprise-grade security with Azure Entra ID authentication, document operations, vector search, and schema discovery.A Model Context Protocol (MCP) server that enables AI agents to interact with Azure Cosmos DB through natural language queries. Features enterprise-grade security with Azure Entra ID authentication, document operations, vector search, and schema discovery.



## 🚀 Quick Start Guide## � Quick Start Guide



### PrerequisitesFollow these 3 simple steps to get your MCP Toolkit running:



- Azure subscription with Contributor access### Step 1: Deploy Infrastructure (5 minutes)

- Existing Azure Cosmos DB account

- Azure OpenAI service (optional, for vector search)Click the Deploy to Azure button to create all required Azure resources:

- Docker Desktop installed and running

- Azure CLI installed (`az login` completed)[![Deploy to Azure](https://aka.ms/deploytoazurebutton)](https://portal.azure.com/#create/Microsoft.Template/uri/https%3A%2F%2Fraw.githubusercontent.com%2FAzureCosmosDB%2FMCPToolKit%2Fmain%2Finfrastructure%2Fdeploy-all-resources.json)

- PowerShell 5.1 or higher

This creates:

### Deployment Steps- Container App for hosting the MCP server

- Container Registry for your app images  

#### 1. Deploy Infrastructure (5 minutes)- Managed Identity for secure resource access

- All necessary networking and security

```powershell

cd infrastructure**Note:** The Entra ID app will be created in Step 2 for better reliability.



az deployment group create `### Step 2: Configure Permissions (2 minutes)

    --resource-group "rg-mcp-toolkit" `

    --template-file "main.bicep" `Run the automated setup script to create the Entra ID app and configure all permissions:

    --parameters `

        containerAppName="mcp-toolkit-app" ````powershell

        environmentName="mcp-toolkit-env" `cd ..

        location="eastus" `.\scripts\Setup-Permissions.ps1 -ResourceGroup "your-resource-group-name"

        cosmosDbAccountName="your-cosmos-account"```

```

This automatically:

Creates: Container App, Container Registry, Managed Identity, Container Environment, Entra ID App with `Mcp.Tool.Executor` role- ✅ Creates the Entra ID app with MCP Tool Executor role

- ✅ Assigns you to the MCP role

#### 2. Assign Cosmos DB Permissions (2 minutes)- ✅ Configures Cosmos DB read permissions

- ✅ Configures Azure OpenAI permissions

```powershell

$principalId = az containerapp show --name "mcp-toolkit-app" --resource-group "rg-mcp-toolkit" --query "identity.principalId" -o tsv### Step 3: Deploy Application (3 minutes)



az cosmosdb sql role assignment create `Build and deploy your application:

    --account-name "your-cosmos-account" `

    --resource-group "your-cosmos-rg" ````powershell

    --scope "/" `# Deploy application (replace with your actual resource names from Step 1)

    --principal-id $principalId `.\scripts\Quick-Deploy.ps1 `

    --role-definition-name "Cosmos DB Built-in Data Reader"    -ResourceGroup "your-resource-group-name" `

```    -ContainerAppName "mcp-toolkit-app" `

    -RegistryName "your-registry-name"

#### 3. Assign Yourself the MCP Role (1 minute)```



Azure Portal: **Azure AD** → **App registrations** → Find your MCP app → **App roles** → Assign **Mcp.Tool.Executor** to yourself### ✅ Test Your Setup



#### 4. Build and Deploy (3 minutes)```powershell

# Get access token

```powershell$clientId = az ad app list --display-name "*mcp*" --query "[0].appId" --output tsv

cd ..$token = az account get-access-token --resource "api://$clientId" --query "accessToken" --output tsv



.\scripts\Quick-Deploy.ps1 `# Test MCP tools

    -ResourceGroup "rg-mcp-toolkit" `$headers = @{ "Authorization" = "Bearer $token"; "Content-Type" = "application/json" }

    -ContainerAppName "mcp-toolkit-app" `$body = '{"jsonrpc":"2.0","method":"tools/list","id":1}'

    -RegistryName "your-registry-name"$appUrl = az containerapp show --name "mcp-toolkit-app" --resource-group "rg-your-resource-group" --query "properties.configuration.ingress.fqdn" --output tsv

```Invoke-RestMethod -Uri "https://$appUrl/mcp" -Method Post -Headers $headers -Body $body

```

#### 5. Test

**Expected result:** You should see a list of available MCP tools.

Open `https://<your-app>.azurecontainerapps.io` → Login → List Tools

---

---

## Prerequisites

## Features

Before starting, make sure you have:

- 🔍 Document operations (query, search, schema discovery)- Azure subscription with Contributor access

- 🧠 AI-powered vector search with Azure OpenAI- Azure Cosmos DB account (existing)

- 🔐 Azure Entra ID authentication with RBAC- Azure OpenAI service (for vector search, optional)

- 🌐 Interactive web UI with MSAL.js- Docker Desktop installed

- 🐳 Production-ready containerized deployment- Azure CLI installed and logged in (`az login`)



### MCP Tools## What You Get



| Tool | Description |### Features

|------|-------------|- 🔍 **Document Operations** - Query documents, full-text search, schema discovery

| `list_databases` | Lists all databases |- 🧠 **AI-Powered Vector Search** - Semantic search using Azure OpenAI embeddings  

| `list_collections` | Lists containers in database |- 🔐 **Enterprise Security** - Azure Entra ID authentication with role-based access control

| `get_recent_documents` | Gets recent documents (1-20) |- 🐳 **Production Ready** - Containerized deployment to Azure Container Apps

| `find_document_by_id` | Finds document by ID |

| `text_search` | Full-text search on properties |### MCP Tools Available

| `vector_search` | Semantic search with embeddings |

| `get_approximate_schema` | Analyzes document structure || Tool | Description | Parameters |

|------|-------------|------------|

---| **list_databases** | Lists all databases | None |

| **list_collections** | Lists containers in database | `databaseId` |

## Configuration| **get_recent_documents** | Gets recent documents (1-20) | `databaseId`, `containerId`, `n` |

| **find_document_by_id** | Finds document by ID | `databaseId`, `containerId`, `id` |

All configuration managed through:| **text_search** | Full-text search on properties | `databaseId`, `containerId`, `property`, `searchPhrase`, `n` |

- **Bicep** (`infrastructure/main.bicep`) - Azure resources| **vector_search** | Semantic search with AI embeddings | `databaseId`, `containerId`, `searchText`, `vectorProperty`, `selectProperties`, `topN` |

- **Quick-Deploy script** (`scripts/Quick-Deploy.ps1`) - Build & deploy| **get_approximate_schema** | Analyzes document structure | `databaseId`, `containerId` |

- **Environment variables** - Set in Bicep or via `az containerapp update`

---

### Key Environment Variables

## Local Development

Auto-configured by Bicep:

- `AZURE_CLIENT_ID` - Managed IdentityFor development and testing on your local machine:

- `AzureAd__TenantId` - Tenant ID

- `AzureAd__ClientId` - Entra App ID```powershell

- `ASPNETCORE_ENVIRONMENT` - Production/Developmentgit clone https://github.com/AzureCosmosDB/MCPToolKit.git

cd MCPToolKit

Optional (add manually):

```powershell# Set bypass mode for development (no authentication required)

az containerapp update --name "mcp-toolkit-app" --resource-group "rg-mcp-toolkit" `$env:DEV_BYPASS_AUTH = "true"

    --set-env-vars "COSMOS_ENDPOINT=https://your-cosmos.documents.azure.com:443/" `

                   "OPENAI_ENDPOINT=https://your-openai.openai.azure.com/"# Run with Docker Compose (includes Cosmos DB emulator)

```docker-compose up -d



---# Or run directly

cd src/AzureCosmosDB.MCP.Toolkit

## Local Developmentdotnet run

```

```powershell

git clone https://github.com/AzureCosmosDB/MCPToolKit.git### Test Locally

cd MCPToolKit```powershell

# Health check

# With Docker Compose (includes Cosmos emulator)Invoke-RestMethod http://localhost:8080/api/health

docker-compose up -d

# List tools (no auth required with bypass mode)

# Or run directly$body = '{"jsonrpc":"2.0","method":"tools/list","id":1}'

cd src/AzureCosmosDB.MCP.ToolkitInvoke-RestMethod -Uri http://localhost:8080/mcp -Method Post -ContentType "application/json" -Body $body

dotnet run```

```

---

Test locally:

```powershell## Configuration

Invoke-RestMethod http://localhost:8080/health

$body = '{"jsonrpc":"2.0","method":"tools/list","id":1}'### Environment Variables

Invoke-RestMethod -Uri http://localhost:8080/mcp -Method Post -ContentType "application/json" -Body $body| Variable | Description | Example |

```|----------|-------------|---------|

| `COSMOS_ENDPOINT` | Cosmos DB endpoint | `https://myaccount.documents.azure.com:443/` |

---| `OPENAI_ENDPOINT` | Azure OpenAI endpoint | `https://myopenai.openai.azure.com/` |

| `OPENAI_EMBEDDING_DEPLOYMENT` | Embedding model deployment | `text-embedding-ada-002` |

## Troubleshooting| `DEV_BYPASS_AUTH` | Bypass auth for development | `true` or `false` |



**Page won't load**### VS Code Integration

```powershell

az containerapp logs show --name "mcp-toolkit-app" --resource-group "rg-mcp-toolkit" --tail 50Add to your VS Code configuration:

``````json

// .vscode/mcp.json

**401 Unauthorized**{

- Verify `Mcp.Tool.Executor` role assigned in Azure Portal  "servers": {

- Clear browser cache and re-login    "azure-cosmos-db-mcp": {

      "type": "http",

**403 Forbidden (Cosmos DB)**      "url": "https://your-mcp-server.azurecontainerapps.io"

- Re-run step 2 to assign Cosmos DB permissions    }

  }

**Old version showing**}

- Clear browser cache (Ctrl+Shift+Delete)```

- Use incognito mode

### Example Queries

---```

@copilot List all databases in my Cosmos DB account

## Project Structure@copilot Show the last 10 documents from the 'orders' container

@copilot What's the schema of the 'customers' container?

```@copilot Search for products similar to 'wireless headphones'

MCPToolKit/```

├── src/AzureCosmosDB.MCP.Toolkit/   # .NET 9.0 application

│   ├── Controllers/                  # MCP & Auth controllers---

│   ├── Services/                     # Cosmos DB & Auth services

│   └── wwwroot/                      # Web UI (MSAL)## Advanced Configuration

├── infrastructure/main.bicep         # Infrastructure as Code

├── scripts/Quick-Deploy.ps1          # Build & deploy automation<details>

├── Dockerfile                        # Production container<summary>Manual Permission Setup (if automated script doesn't work)</summary>

└── docker-compose.yml                # Local dev environment

```### Azure Resource Permissions



---The MCP Toolkit requires specific Azure roles for accessing Cosmos DB and OpenAI services:



## Security#### Cosmos DB Permissions (Choose One)



- JWT Bearer token validation**Option 1: Cosmos DB Built-in Data Reader (Recommended)**

- Role-based access (`Mcp.Tool.Executor`)```powershell

- Managed Identity (no secrets)# Get managed identity ID

- Read-only Cosmos DB access$managedIdentityId = az containerapp show --name "mcp-toolkit-app" --resource-group "your-rg" --query "identity.principalId" --output tsv

- HTTPS only in production

# Assign to Cosmos DB

---az cosmosdb sql role assignment create --account-name "your-cosmos-account" --resource-group "cosmos-rg" --scope "/" --principal-id $managedIdentityId --role-definition-name "Cosmos DB Built-in Data Reader"

```

## License

#### Azure OpenAI Permissions (For Vector Search)

MIT License - see [LICENSE](LICENSE)

**Required Role: Cognitive Services OpenAI User**

## Support```powershell

# Get subscription ID

- Issues: [GitHub Issues](https://github.com/AzureCosmosDB/MCPToolKit/issues)$subscriptionId = az account show --query "id" --output tsv

- Docs: See `docs/` folder

- Testing: See `TESTING_GUIDE.md`# Assign to Managed Identity

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
- **Standard OAuth Flow** - Uses `.default` scope with app role assignments (no custom OAuth2 scopes needed)

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