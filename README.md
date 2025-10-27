# Azure Cosmos DB MCP Toolkit

A Model Context Protocol (MCP) server that enables AI agents to interact with Azure Cosmos DB through natural language queries. Features enterprise-grade security with Azure Entra ID authentication, document operations, vector search, and schema discovery.

## 🚀 Deploy to Azure

### Quick 2-Step Deployment

**Step 1: Deploy Infrastructure** [![Deploy to Azure](https://aka.ms/deploytoazurebutton)](https://portal.azure.com/#create/Microsoft.Template/uri/https%3A%2F%2Fraw.githubusercontent.com%2FAzureCosmosDB%2FMCPToolKit%2Fmain%2Finfrastructure%2Fdeploy-all-resources.json)

**Step 2: Deploy Application**
```powershell
# Clone repository
git clone https://github.com/AzureCosmosDB/MCPToolKit.git
cd MCPToolKit

# Get your resource names from Azure Portal after Step 1
# Then run these commands with your actual resource names:

az acr login --name "your-registry-name"
docker build -t "your-registry-name.azurecr.io/mcp-toolkit:latest" .
docker push "your-registry-name.azurecr.io/mcp-toolkit:latest"
az containerapp update --name "mcp-toolkit-app" --resource-group "your-rg" --image "your-registry-name.azurecr.io/mcp-toolkit:latest"
```

**Total time**: ~10 minutes

> **Why 2 steps?** ARM templates deploy infrastructure but can't build applications from source code. This follows Azure security best practices.

### Verify Deployment
```powershell
# Test health endpoint
Invoke-RestMethod "https://your-app-url/api/health"
```

### Prerequisites
- Azure subscription with Contributor access
- Existing Azure Cosmos DB account
- Existing Azure OpenAI service (for vector search)
- Docker Desktop installed
- Azure CLI installed

## Features

- 🔍 **Document Operations** - Query documents, full-text search, schema discovery
- 🧠 **AI-Powered Vector Search** - Semantic search using Azure OpenAI embeddings  
- 🔐 **Enterprise Security** - Azure Entra ID authentication with role-based access control
- 🐳 **Production Ready** - Containerized deployment to Azure Container Apps

### Find Your Resource Names

After Step 1, get these from Azure Portal → Your Resource Group:
- **Container App**: Usually `mcp-toolkit-app`
- **Container Registry**: Starts with `mcptoolkitacr` + random string
## Local Development

### Quick Start
```powershell
git clone https://github.com/AzureCosmosDB/MCPToolKit.git
cd MCPToolKit

# Set bypass mode for development
$env:DEV_BYPASS_AUTH = "true"

# Run with Docker Compose (includes Cosmos DB emulator)
docker-compose up -d

# Or run directly
cd src/AzureCosmosDB.MCP.Toolkit
dotnet run
```

**Test locally:**
```powershell
# Health check
Invoke-RestMethod http://localhost:8080/api/health

# List tools (no auth required with bypass)
$body = '{"jsonrpc":"2.0","method":"tools/list","id":1}'
Invoke-RestMethod -Uri http://localhost:8080/mcp -Method Post -ContentType "application/json" -Body $body
```

**Option A: PowerShell Script (Recommended)**
```powershell
# Clone the repository (if you haven't already)
git clone https://github.com/AzureCosmosDB/MCPToolKit.git
cd MCPToolKit

# Run quick deployment script with your actual resource names
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

# Script will:
# ✅ Login to your Azure Container Registry
# ✅ Build Docker image from latest code  
# ✅ Push image to your registry
# ✅ Update Container App with new image
# ✅ Test deployment automatically
```

**Option B: Manual Commands**
```powershell
# Prerequisites: Make sure Docker is running and you're logged into Azure CLI
az login
docker version

# Login to your container registry
az acr login --name mcptoolkitacr57c4u6r4dcvto

# Build and push Docker image
docker build -t mcptoolkitacr57c4u6r4dcvto.azurecr.io/mcp-toolkit:latest .
docker push mcptoolkitacr57c4u6r4dcvto.azurecr.io/mcp-toolkit:latest

# Update Container App to use your image
az containerapp update \
  --name mcp-toolkit-app \
  --resource-group rg-sajee-cosmos-mcp-kit \
  --image mcptoolkitacr57c4u6r4dcvto.azurecr.io/mcp-toolkit:latest \
  --revision-suffix $(Get-Date -Format "MMdd-HHmm")
```

**Option C: GitHub Actions (For Teams)**
1. Fork this repository to your GitHub account
2. Go to Actions → "Update Deployed App" 
3. Click "Run workflow" and enter your resource details
4. Automatic build and deployment from latest code

### 📊 Test Your Deployment

#### **� Health Check (No Authentication Required)**
```powershell
# Test basic connectivity
Invoke-RestMethod "https://mcp-toolkit-app.proudwave-e0461bc6.eastus.azurecontainerapps.io/api/health"

# Expected response: {"status":"Healthy","version":"1.0.0"}
```

#### **🔧 MCP Tools Test (Authentication Required)**
```powershell
# First, get an access token (requires role assignment - see Authentication section)
$clientId = "your-entra-app-client-id"  # From deployment-info.json
$token = az account get-access-token --resource "api://$clientId" --query "accessToken" -o tsv

# Test MCP tools
$headers = @{
    "Authorization" = "Bearer $token"
    "Content-Type" = "application/json"
}
$body = '{"jsonrpc":"2.0","method":"tools/list","id":1}'
Invoke-RestMethod -Uri "https://mcp-toolkit-app.proudwave-e0461bc6.eastus.azurecontainerapps.io/mcp" -Method Post -Headers $headers -Body $body
```

#### **🌐 Web Interface Testing**
Your deployed app includes a built-in web interface:
```
https://mcp-toolkit-app.proudwave-e0461bc6.eastus.azurecontainerapps.io/
```

For **enhanced secure testing** with Azure AD authentication:
```powershell
# Download enhanced web client (optional)
Invoke-WebRequest "https://raw.githubusercontent.com/AzureCosmosDB/MCPToolKit/main/test-ui.html" -OutFile "test-ui.html"

# Start local server and open in browser
python -m http.server 3000
# Then open: http://localhost:3000/test-ui.html
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

### 🔧 Deployment Issues

**"Deploy to Azure button doesn't work completely"**
- ✅ **This is expected!** ARM templates can only create infrastructure, not build applications
- ✅ **Solution**: Follow our 2-step process above (Deploy → Build & Deploy)
- ✅ **Why?** Building code requires GitHub Actions, Docker, or similar CI/CD tools

**"Container App shows hello world page"**
- ✅ **Expected initially** - ARM templates deploy a placeholder container
- ✅ **Solution**: Run Step 2 (Quick-Deploy.ps1 or manual deployment)
- ✅ **Check**: Your app should show "Azure Cosmos DB MCP Toolkit" title after Step 2

**"Quick-Deploy.ps1 authentication errors"**
```powershell
# Make sure you're logged into Azure CLI
az login
az account set --subscription "your-subscription-id"

# Verify access to your resource group  
az group show --name "rg-sajee-cosmos-mcp-kit"

# Test container registry access
az acr login --name "mcptoolkitacr57c4u6r4dcvto"
```

**"Docker build/push fails"**
```powershell
# Ensure Docker Desktop is running
docker version

# Test Docker build locally
docker build -t test-build .

# If registry push fails, re-login
az acr login --name "mcptoolkitacr57c4u6r4dcvto"
```

**"404 or timeout errors on Container App URL"**
- ✅ **Wait 2-3 minutes** after deployment for container to start
- ✅ **Check revision status**: Go to Azure Portal → Container App → Revisions
- ✅ **View logs**: Azure Portal → Container App → Log stream

### 🏥 Health Check
```powershell
# Local development
Invoke-RestMethod "http://localhost:8080/api/health"

# Azure deployment (replace with your actual URL)
Invoke-RestMethod "https://mcp-toolkit-app.proudwave-e0461bc6.eastus.azurecontainerapps.io/api/health"

# Expected response: {"status":"Healthy","version":"1.0.0"}
```

### 🎯 Common Issues

**"Authentication required errors"**
- ✅ Verify role assignment: User needs `Mcp.Tool.Executor` role
- ✅ Check token scope: Should be `api://your-app-id`
- ✅ For local development: Set `DEV_BYPASS_AUTH=true`

### 📊 Verify Deployment Success

**1. Check Container App is running:**
```powershell
# Health check should return status 200
Invoke-RestMethod "https://mcp-toolkit-app.proudwave-e0461bc6.eastus.azurecontainerapps.io/api/health"

# Expected response: {"status":"Healthy","version":"1.0.0"}
```

**2. Test MCP endpoint (requires authentication):**
```powershell
# Get access token (replace with your client ID from deployment-info.json)
$clientId = "your-entra-app-client-id"
$token = az account get-access-token --resource "api://$clientId" --query "accessToken" -o tsv

# Test tools list
$headers = @{
    "Authorization" = "Bearer $token"
    "Content-Type" = "application/json"  
}
$body = '{"jsonrpc":"2.0","method":"tools/list","id":1}'
Invoke-RestMethod -Uri "https://mcp-toolkit-app.proudwave-e0461bc6.eastus.azurecontainerapps.io/mcp" -Method Post -Headers $headers -Body $body
```

**3. Expected successful response:**
```json
{
  "jsonrpc": "2.0",
  "id": 1,
  "result": {
    "tools": [
      {"name": "list_databases", "description": "Lists all databases"},
      {"name": "list_collections", "description": "Lists containers in database"},
      {"name": "get_recent_documents", "description": "Gets recent documents"},
      {"name": "text_search", "description": "Full-text search on properties"},
      {"name": "vector_search", "description": "Semantic search with AI embeddings"},
      {"name": "find_document_by_id", "description": "Finds document by ID"},
      {"name": "get_approximate_schema", "description": "Analyzes document structure"}
    ]
  }
}
}
```

### 🎯 Common Issues

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