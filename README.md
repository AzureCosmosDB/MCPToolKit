# Azure Cosmos DB MCP Toolkit

A Model Context Protocol (MCP) server that enables AI agents to interact with Azure Cosmos DB through natural language queries. Features enterprise-grade security with Azure Entra ID authentication, document operations, vector search, and schema discovery.

## Features

- 🔍 **Document Operations** - Query documents, full-text search, schema discovery
- 🧠 **AI-Powered Vector Search** - Semantic search using Azure OpenAI embeddings  
- 🔐 **Enterprise Security** - Azure Entra ID authentication with role-based access control
- 🐳 **Production Ready** - Containerized deployment to Azure Container Apps

## Prerequisites

- Azure subscription with Contributor access
- Azure Cosmos DB account
- Azure OpenAI service (for vector search)
- Docker Desktop installed
- Azure CLI installed

## Quick Start

### Deploy to Azure

**Step 1: Deploy Infrastructure**
[![Deploy to Azure](https://aka.ms/deploytoazurebutton)](https://portal.azure.com/#create/Microsoft.Template/uri/https%3A%2F%2Fraw.githubusercontent.com%2FAzureCosmosDB%2FMCPToolKit%2Fmain%2Finfrastructure%2Fdeploy-all-resources.json)

**Step 2: Deploy Application**
```powershell
# Clone repository
git clone https://github.com/AzureCosmosDB/MCPToolKit.git
cd MCPToolKit

# Use the deployment script with your resource names from Step 1
.\scripts\Quick-Deploy.ps1 -ResourceGroup "your-rg" -ContainerAppName "mcp-toolkit-app" -RegistryName "your-registry-name"
```

**Total deployment time**: ~10 minutes

### Verify Deployment
```powershell
# Test health endpoint
Invoke-RestMethod "https://your-app-url/api/health"
```

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

### Test Locally
```powershell
# Health check
Invoke-RestMethod http://localhost:8080/api/health

# List tools (no auth required with bypass)
$body = '{"jsonrpc":"2.0","method":"tools/list","id":1}'
Invoke-RestMethod -Uri http://localhost:8080/mcp -Method Post -ContentType "application/json" -Body $body
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

### Environment Variables
| Variable | Description | Example |
|----------|-------------|---------|
| `COSMOS_ENDPOINT` | Cosmos DB endpoint | `https://myaccount.documents.azure.com:443/` |
| `OPENAI_ENDPOINT` | Azure OpenAI endpoint | `https://myopenai.openai.azure.com/` |
| `OPENAI_EMBEDDING_DEPLOYMENT` | Embedding model deployment | `text-embedding-ada-002` |
| `DEV_BYPASS_AUTH` | Bypass auth for development | `true` or `false` |

### Authentication Setup
1. **Assign Role to Users**
```powershell
az ad app role assignment create --id "your-entra-app-client-id" --principal "user@domain.com" --role "Mcp.Tool.Executor"
```

2. **Get Access Token**
```powershell
$token = az account get-access-token --resource "api://your-client-id" --query "accessToken" --output tsv
```

3. **Test MCP Calls**
```powershell
$headers = @{ "Authorization" = "Bearer $token"; "Content-Type" = "application/json" }
$body = '{"jsonrpc":"2.0","method":"tools/list","id":1}'
Invoke-RestMethod -Uri "https://your-app-url/mcp" -Method Post -Headers $headers -Body $body
```

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
@copilot Show the last 10 documents from the 'orders' container
@copilot What's the schema of the 'customers' container?
@copilot Search for products similar to 'wireless headphones'
```

## Security

- **JWT Bearer Authentication** - Azure Entra ID token validation
- **Role-Based Access** - `Mcp.Tool.Executor` role required
- **Managed Identity** - No stored credentials in production
- **Read-Only Access** - Cannot modify data

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

## Support

For issues and questions:
- Create an issue in this repository
- Review the [Testing Guide](TESTING_GUIDE.md) for common scenarios