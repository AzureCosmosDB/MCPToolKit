# Azure Cosmos DB MCP Toolkit

A Model Context Protocol (MCP) server that enables AI agents to interact with Azure Cosmos DB through natural language queries. Features enterprise-grade security with Azure Entra ID authentication, document operations, vector search, and schema discovery.

## 🚀 Deploy to Azure

[![Deploy to Azure](https://aka.ms/deploytoazurebutton)](https://portal.azure.com/#create/Microsoft.Template/uri/https%3A%2F%2Fraw.githubusercontent.com%2FAzureCosmosDB%2FMCPToolKit%2Fmain%2Finfrastructure%2Fdeploy-all-resources.json)

**One-click deployment with complete infrastructure setup!** No manual configuration required.

> **💡 Note**: The deployment requires existing Azure Cosmos DB and Azure OpenAI services. The toolkit connects to your existing resources without creating new ones, keeping costs predictable.

### Prerequisites for Deploy to Azure
- **Azure Subscription** with Contributor or Owner access
- **Existing Azure Cosmos DB account** with databases and containers containing data
- **Existing Azure OpenAI service** with text embedding deployment (for vector search)
- **Azure AD permissions** for app registration (automatic during deployment)
- **Principal ID** (your Azure AD Object ID) - see instructions below

## Features

- 🔍 **Document Operations** - Query documents, full-text search, schema discovery
- 🧠 **AI-Powered Vector Search** - Semantic search using Azure OpenAI embeddings  
- 🔐 **Enterprise Security** - Azure Entra ID authentication with role-based access control
- 🐳 **Production Ready** - Containerized deployment to Azure Container Apps
- 🚀 **Easy Deployment** - Automated deployment with complete infrastructure setup
- 🛡️ **Authentication Modes** - Production Entra ID auth + development bypass mode

## Quick Start

### 🌟 Deploy to Azure (One-Click)

[![Deploy to Azure](https://aka.ms/deploytoazurebutton)](https://portal.azure.com/#create/Microsoft.Template/uri/https%3A%2F%2Fraw.githubusercontent.com%2FAzureCosmosDB%2FMCPToolKit%2Fmain%2Finfrastructure%2Fdeploy-all-resources.json)

Click the button above to deploy directly to Azure Portal with guided setup!

**What gets deployed automatically:**
- ✅ Azure Container Apps with managed identity
- ✅ Azure Container Registry  
- ✅ Entra ID App Registration with `Mcp.Tool.Executor` role
- ✅ Complete authentication and authorization setup
- ✅ Container app with proper environment configuration

**Required inputs during deployment:**
- **Resource Group** - Create new or select existing
- **Resource Prefix** - Unique identifier for your resources
- **Principal ID** - Your Azure AD user/service principal Object ID
- **Cosmos Endpoint** - Your existing Cosmos DB account URL (e.g., `https://mycosmosdb.documents.azure.com:443/`)
- **OpenAI Endpoint** - Your Azure OpenAI service URL (e.g., `https://myopenai.openai.azure.com/`)
- **OpenAI Embedding Deployment** - Your embedding model deployment name (e.g., `text-embedding-ada-002`)

**Deployment takes 5-10 minutes** and creates all necessary Azure resources with proper security configuration.

#### 🔑 How to Get Your Principal ID (Object ID)

**Option 1: Azure Portal**
1. Go to [Azure Portal](https://portal.azure.com) → Azure Active Directory → Users
2. Search for your username → Copy the "Object ID"

**Option 2: Azure CLI**
```bash
# Get your own Object ID
az ad signed-in-user show --query id -o tsv

# Or get Object ID by email
az ad user show --id "your-email@domain.com" --query id -o tsv
```

**Option 3: PowerShell**
```powershell
# Get your own Object ID
(Get-AzADUser -UserPrincipalName (Get-AzContext).Account.Id).Id
```

### 🚀 Alternative: Command Line Deployment

For developers who prefer automated scripting:

#### PowerShell (Windows)
```powershell
git clone https://github.com/AzureCosmosDB/MCPToolKit.git
cd MCPToolKit
.\scripts\Deploy-CosmosMcpServer.ps1 -ResourceGroup "rg-mcp-toolkit-demo"
```

#### Bash (Linux/macOS)  
```bash
git clone https://github.com/AzureCosmosDB/MCPToolKit.git
cd MCPToolKit
chmod +x scripts/deploy-cosmos-mcp-server.sh
./scripts/deploy-cosmos-mcp-server.sh --resource-group "rg-mcp-toolkit-demo"
```
- ✅ Complete authentication and authorization setup
- ✅ Container app with proper environment configuration

### 📊 Test Your Deployment

#### **🌐 Secure Web Testing (Recommended)**
```bash
# Download the enhanced web client
curl -O https://raw.githubusercontent.com/AzureCosmosDB/MCPToolKit/main/cosmos-mcp-client.html

# Start local server  
python -m http.server 3000

# Open: http://localhost:3000/cosmos-mcp-client.html
# Use your deployed server URL and Client ID for secure testing
```

#### **⚡ Quick Command Line Test**
```bash
# Run the automated test script
chmod +x scripts/test-deployment.sh
./scripts/test-deployment.sh
```

```bash
# Run the automated test script
chmod +x scripts/test-deployment.sh
./scripts/test-deployment.sh
```

### 🌐 Web Interface Testing

**🌟 NEW: Enterprise-Grade Secure Web Testing**

Test using our enhanced browser interface with enterprise-approved Azure AD authentication:

#### **Quick Start Guide**
```bash
# Download the enhanced web client
curl -O https://raw.githubusercontent.com/AzureCosmosDB/MCPToolKit/main/cosmos-mcp-client.html

# Start local server
python -m http.server 3000

# Open in browser: http://localhost:3000/cosmos-mcp-client.html
```

#### **Key Features**
- ✅ **No token copy/paste** - Security team approved OAuth flow
- ✅ **Interactive tool testing** - Forms for all Cosmos DB operations
- ✅ **Auto-generated cURL commands** - Ready for automation
- ✅ **Enterprise compliance** - Microsoft Authentication Library (MSAL)
- ✅ **Role validation** - Automatic `Mcp.Tool.Executor` verification
- ✅ **Secure login flow** - Standard Azure AD authentication

#### **🎯 Complete Testing Instructions**
📖 **[Web Testing Guide](docs/WEB-TESTING-GUIDE.md)** - Comprehensive guide with:
- Step-by-step setup instructions
- Authentication configuration
- Interactive testing scenarios  
- Troubleshooting common issues
- Security validation steps
- cURL command generation

#### **Alternative: Basic Web Interface**
Your deployed MCP server includes a basic interface at:
```
https://your-app.azurecontainerapps.io/
```

### 🔑 Using the MCP Server

#### **Option A: Secure Web Interface (Recommended)**
```bash
# Download enhanced web client
curl -O https://raw.githubusercontent.com/AzureCosmosDB/MCPToolKit/main/cosmos-mcp-client.html

# Start local server
python -m http.server 3000

# Open: http://localhost:3000/cosmos-mcp-client.html
# 1. Enter your Client ID (from deployment-info.json)
# 2. Click "🔑 Sign In with Azure AD"
# 3. Use standard Microsoft login - no token copy/paste!
# 4. Test all MCP tools with secure authentication
```

#### **Option B: Command Line Testing**

1. **Assign Role to Users**
```bash
# Get app ID from deployment-info.json
az ad app role assignment create \
  --id "your-entra-app-client-id" \
  --principal "user@domain.com" \
  --role "Mcp.Tool.Executor"
```

2. **Get Access Token**
```bash
# Using our utility scripts
./scripts/get-access-token.sh

# Or manually with Azure CLI
az account get-access-token \
  --resource "api://your-client-id" \
  --query "accessToken" \
  --output tsv
```

3. **Test MCP Calls**
```bash
curl -X POST "https://your-app.azurecontainerapps.io/mcp" \
  -H "Authorization: Bearer $ACCESS_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"jsonrpc":"2.0","method":"tools/list","id":1}'
```

#### 2. Get Access Token and Test
```bash
# Get token
ACCESS_TOKEN=$(az account get-access-token \
  --resource "api://your-entra-app-client-id" \
  --query "accessToken" --output tsv)

# Test MCP tools
curl -X POST "https://your-mcp-server.azurecontainerapps.io/mcp" \
  -H "Authorization: Bearer $ACCESS_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"jsonrpc":"2.0","method":"tools/list","id":1}'
```

## Local Development

### Quick Start with Authentication Bypass
```bash
git clone https://github.com/AzureCosmosDB/MCPToolKit.git
cd MCPToolKit

# Set bypass mode for development
export DEV_BYPASS_AUTH=true  # Linux/Mac
$env:DEV_BYPASS_AUTH = "true"  # PowerShell

# Run with Docker Compose (includes Cosmos DB emulator)
docker-compose up -d

# Or run directly
cd src/AzureCosmosDB.MCP.Toolkit
dotnet run
```

**Test locally:**
```bash
# Health check
curl http://localhost:8080/health

# List tools (no auth required with bypass)
curl -X POST http://localhost:8080/mcp \
  -H "Content-Type: application/json" \
  -d '{"jsonrpc":"2.0","method":"tools/list","id":1}'
```

## MCP Tools

| Tool | Description | Parameters |
|------|-------------|------------|
| **list_databases** | Lists all databases | None |
| **list_collections** | Lists containers in database | `databaseId` |
| **get_recent_documents** | Gets recent documents (1-20) | `databaseId`, `containerId`, `n` |
| **find_document_by_id** | Finds document by ID | `databaseId`, `containerId`, `id` |
| **text_search** | Full-text search on properties | `databaseId`, `containerId`, `property`, `searchPhrase`, `n` |
| **vector_search** | Semantic search with AI embeddings | `databaseId`, `containerId`, `searchText`, `vectorProperty`, `selectProperties`, `topN` |
| **get_approximate_schema** | Analyzes document structure | `databaseId`, `containerId` |

## Configuration

### Required Environment Variables
| Variable | Description | Example |
|----------|-------------|---------|
| `COSMOS_ENDPOINT` | Cosmos DB endpoint | `https://myaccount.documents.azure.com:443/` |
| `OPENAI_ENDPOINT` | Azure OpenAI endpoint (for vector search) | `https://myopenai.openai.azure.com/` |
| `OPENAI_EMBEDDING_DEPLOYMENT` | Embedding model deployment | `text-embedding-ada-002` |

### Authentication Configuration
```json
// appsettings.json
{
  "AzureAd": {
    "TenantId": "your-tenant-id",
    "ClientId": "your-client-id"
  },
  "DevelopmentMode": {
    "BypassAuthentication": false  // Set to true for local development
  }
}
```

## Security

### Production Security Features
- **JWT Bearer Authentication** - Azure Entra ID token validation
- **Role-Based Access** - `Mcp.Tool.Executor` role required
- **Managed Identity** - No stored credentials
- **Read-Only Access** - Cannot modify data

### Development Mode
- **Authentication Bypass** - Set `DEV_BYPASS_AUTH=true` or configure in appsettings
- **Local Testing** - No tokens required for development

## VS Code Integration

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
@copilot Show the last 10 documents from the 'orders' container in 'ecommerce' database
@copilot What's the schema of the 'customers' container?
@copilot Search for products similar to 'wireless headphones' using vector search
```

## Troubleshooting

### Health Check
```bash
# Local
curl http://localhost:8080/health

# Azure
curl https://your-app.azurecontainerapps.io/health
```

### Common Issues

**Authentication Errors**
- Verify role assignment: User needs `Mcp.Tool.Executor` role
- Check token scope: Should be `api://your-app-id`
- For local development: Set `DEV_BYPASS_AUTH=true`

**Container Logs**
```bash
# Azure Container Apps
az containerapp logs show --name mcp-demo-app --resource-group your-rg --tail 20

# Local Docker
docker-compose logs mcp-toolkit
```

## Project Structure

```
MCPToolKit/
├── src/AzureCosmosDB.MCP.Toolkit/     # Main application (.NET 9.0)
├── infrastructure/                    # Bicep templates for Azure deployment
├── scripts/                          # Deployment and testing scripts
├── docs/                             # Additional documentation
├── Dockerfile                        # Container configuration
└── docker-compose.yml               # Local development environment
```

## Additional Resources

- **[Deploy to Azure Guide](docs/deploy-to-azure-guide.md)** - Comprehensive one-click deployment instructions
- **[Web Testing Guide](docs/WEB-TESTING-GUIDE.md)** - Secure browser testing with Azure AD authentication
- **[Testing Guide](TESTING_GUIDE.md)** - Testing scenarios and examples
- **[MCP Specification](https://spec.modelcontextprotocol.io/)** - Model Context Protocol documentation