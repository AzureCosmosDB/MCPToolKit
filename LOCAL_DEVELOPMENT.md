# Local Development Guide

This guide covers setting up and running the Azure Cosmos DB MCP Toolkit on your local machine for development and testing.

## Prerequisites

- Git
- Docker Desktop
- .NET 9.0 SDK
- Azure CLI (for testing with Azure resources)

## Setup

### 1. Clone the Repository

```powershell
git clone https://github.com/AzureCosmosDB/MCPToolKit.git
cd MCPToolKit
```

### 2. Configure Development Mode

Set bypass mode to disable authentication for local development:

```powershell
$env:DEV_BYPASS_AUTH = "true"
```

## Running Locally

### Option 1: Docker Compose (Recommended)

Runs the MCP server with a local Cosmos DB emulator:

```powershell
docker-compose up -d
```

This starts:
- MCP Toolkit server on `http://localhost:8080`
- Cosmos DB Emulator (if configured in docker-compose.yml)

### Option 2: Direct .NET Run

Run the application directly with .NET:

```powershell
cd src/AzureCosmosDB.MCP.Toolkit
dotnet run
```

The server will start on `http://localhost:8080` (or port specified in launchSettings.json).

## Testing Locally

### Health Check

```powershell
Invoke-RestMethod http://localhost:8080/api/health
```

### List Available MCP Tools

```powershell
$body = '{"jsonrpc":"2.0","method":"tools/list","id":1}'
Invoke-RestMethod -Uri http://localhost:8080/mcp `
    -Method Post `
    -ContentType "application/json" `
    -Body $body
```

### Test a Specific Tool

```powershell
# Example: List databases
$body = '{
  "jsonrpc": "2.0",
  "method": "tools/call",
  "id": 1,
  "params": {
    "name": "list_databases",
    "arguments": {}
  }
}'

Invoke-RestMethod -Uri http://localhost:8080/mcp `
    -Method Post `
    -ContentType "application/json" `
    -Body $body
```

## Environment Variables

The MCP server uses these environment variables for both local development and production:

### Cosmos DB Configuration

**For Local Development (Emulator):**
- `COSMOS_CONNECTION_STRING` - Connection string for Cosmos DB emulator
  - Example: `AccountEndpoint=https://localhost:8081/;AccountKey=C2y6yDjf5/R+ob0N8A7Cgv30VRDJIWEHLM+4QDU5DE2nQ9nDuVTqobD4b8mGGyPMbIZnqyMsEcaGQy67XIw/Jw==;`
  - Takes priority if set; skips Azure credential authentication

**For Cloud Production:**
- `COSMOS_ENDPOINT` - Cosmos DB account endpoint URL
  - Example: `https://myaccount.documents.azure.com:443/`
  - Uses DefaultAzureCredential (no additional configuration needed)

### Embeddings/OpenAI Configuration

The toolkit supports three types of embedding endpoints with automatic detection:

**Azure AI Services (Cognitive Services):**
- `OPENAI_ENDPOINT` - https://<resource>.cognitiveservices.azure.com/
- Uses DefaultAzureCredential or `OPENAI_API_KEY` if set
- Example: `https://my-ai-service.cognitiveservices.azure.com/`

**Azure AI Foundry:**
- `OPENAI_ENDPOINT` - https://<resource>.services.ai.azure.com/api/projects/<project-name>
- Uses DefaultAzureCredential or `OPENAI_API_KEY` if set
- Example: `https://my-project.services.ai.azure.com/api/projects/my-project-123`

**OpenAI Native API:**
- `OPENAI_ENDPOINT` - https://api.openai.com/v1
- **Requires:** `OPENAI_API_KEY` (mandatory for OpenAI)
- Example: `https://api.openai.com/v1`

**Common Configuration:**
- `OPENAI_API_KEY` - API key for authentication (optional for Azure endpoints, required for OpenAI)
  - Example: `sk-...` (OpenAI) or Azure API key
- `OPENAI_EMBEDDING_DEPLOYMENT` - Model/deployment name
  - Examples: `text-embedding-3-small`, `text-embedding-3-large`, `gpt-4o-mini`

### Other Configuration

| Variable | Description | Local Example |
|----------|-------------|---------------|
| `DEV_BYPASS_AUTH` | Bypass authentication | `true` |
| `OPENAI_EMBEDDING_DEPLOYMENT` | Embedding model name | `text-embedding-3-small` |
| `OPENAI_EMBEDDING_DIMENSIONS` | Embedding dimensions | `1536` |
| `ENTRA_CLIENTID` | Entra App Client ID | Yes (production) |
| `ENTRA_AUTHORITY` | Entra authority URL | Yes (production) |

### Complete Local Development Example

```powershell
# Cosmos DB Emulator (local)
$env:COSMOS_CONNECTION_STRING = "AccountEndpoint=https://localhost:8081/;AccountKey=C2y6yDjf5/R+ob0N8A7Cgv30VRDJIWEHLM+4QDU5DE2nQ9nDuVTqobD4b8mGGyPMbIZnqyMsEcaGQy67XIw/Jw==;"

# Choose ONE of the following embedding providers:

# Option 1: OpenAI Native API
$env:OPENAI_ENDPOINT = "https://api.openai.com/v1"
$env:OPENAI_API_KEY = "sk-your-openai-key"
$env:OPENAI_EMBEDDING_DEPLOYMENT = "text-embedding-3-small"

# Option 2: Azure AI Services (with API key)
# $env:OPENAI_ENDPOINT = "https://my-ai-service.cognitiveservices.azure.com/"
# $env:OPENAI_API_KEY = "your-azure-key"
# $env:OPENAI_EMBEDDING_DEPLOYMENT = "text-embedding-3-small"

# Option 3: Local/Azure AI Foundry with API key
# $env:OPENAI_ENDPOINT = "http://localhost:8000"  # or Azure Foundry URL
# $env:OPENAI_API_KEY = "your-api-key"
# $env:OPENAI_EMBEDDING_DEPLOYMENT = "text-embedding-3-small"

# Development
$env:DEV_BYPASS_AUTH = "true"
```

### Complete Cloud Production Example

```powershell
# Cosmos DB (cloud)
$env:COSMOS_ENDPOINT = "https://myaccount.documents.azure.com:443/"
# Azure credentials via DefaultAzureCredential (az login)

# Choose ONE of the following embedding providers:

# Option 1: Azure AI Services (cloud) with Managed Identity
$env:OPENAI_ENDPOINT = "https://my-openai.cognitiveservices.azure.com/"
$env:OPENAI_EMBEDDING_DEPLOYMENT = "text-embedding-3-small"
# Uses DefaultAzureCredential (Managed Identity)

# Option 2: Azure AI Foundry (cloud) with Managed Identity
# $env:OPENAI_ENDPOINT = "https://my-project.services.ai.azure.com/api/projects/my-project-123"
# $env:OPENAI_EMBEDDING_DEPLOYMENT = "text-embedding-3-small"
# Uses DefaultAzureCredential (Managed Identity)

# Option 3: OpenAI Native API
# $env:OPENAI_ENDPOINT = "https://api.openai.com/v1"
# $env:OPENAI_API_KEY = "sk-your-openai-key"
# $env:OPENAI_EMBEDDING_DEPLOYMENT = "text-embedding-3-small"
```

### Private Cosmos via proxy (Gateway)

Direct mode opens replica TCP ports and cannot use an outbound proxy. For private
accounts (Bastion SOCKS) or corporate HTTP CONNECT proxies, set a proxy so the Toolkit
uses **Gateway** and dials `*.documents.azure.com:443` through the proxy (TLS still
terminates on Cosmos).

**Precedence:** `COSMOS_SOCKS5_PROXY` → `ALL_PROXY` → `HTTPS_PROXY` → `HTTP_PROXY`.

Bastion SOCKS5:

```powershell
$env:COSMOS_ENDPOINT = "https://myaccount.documents.azure.com:443/"
$env:COSMOS_SOCKS5_PROXY = "socks5://127.0.0.1:51080"   # Bastion tunnel local port
# Optional explicit mode (any proxy already forces Gateway):
# $env:COSMOS_CONNECTION_MODE = "Gateway"
$env:DEV_BYPASS_AUTH = "true"
```

Corporate HTTP CONNECT:

```powershell
$env:HTTPS_PROXY = "http://corp-proxy:3128"
# or: $env:HTTP_PROXY = "http://corp-proxy:3128"
# or: $env:ALL_PROXY = "http://corp-proxy:3128"
```

`COSMOS_CONNECTION_MODE=Direct` with any configured proxy fails closed. Bastion is
SOCKS5 (`socks5://…`); do not point `HTTPS_PROXY` at a Bastion SOCKS port.

## Using Cosmos DB Emulator

The MCP Toolkit now supports local development with the Cosmos DB emulator via connection strings, so you don't need Azure credentials for local testing.

### Option 1: Docker Compose (Easiest)

The `docker-compose.yml` includes both the MCP Toolkit and Cosmos DB emulator:

```powershell
docker-compose up
```

This automatically configures:
- Cosmos DB Emulator at `https://localhost:8081`
- MCP Toolkit at `http://localhost:8080/mcp`
- Pre-configured connection string for emulator

### Option 2: Local Emulator + .NET Runtime

#### Install Cosmos DB Emulator

Download and install from: https://aka.ms/cosmosdb-emulator

#### Configure Connection String

Set the connection string environment variable instead of endpoint:

```powershell
$env:COSMOS_CONNECTION_STRING = "AccountEndpoint=https://localhost:8081/;AccountKey=C2y6yDjf5/R+ob0N8A7Cgv30VRDJIWEHLM+4QDU5DE2nQ9nDuVTqobD4b8mGGyPMbIZnqyMsEcaGQy67XIw/Jw==;"
```

Or for cloud production, use:

```powershell
$env:COSMOS_ENDPOINT = "https://myaccount.documents.azure.com:443/"
# Uses DefaultAzureCredential automatically
```

The connection string takes priority; if it's set, cloud credentials are not used.

## Debugging in Visual Studio / VS Code

### Visual Studio

1. Open `AzureCosmosDB.MCP.Toolkit.sln`
2. Set `AzureCosmosDB.MCP.Toolkit` as startup project
3. Press F5 to start debugging

### VS Code

1. Open the repository folder
2. Install C# Dev Kit extension
3. Press F5 or use "Run and Debug" panel
4. Select ".NET Core Launch (web)" configuration

## Hot Reload

The application supports hot reload for development:

```powershell
dotnet watch run --project src/AzureCosmosDB.MCP.Toolkit
```

Changes to C# files will automatically trigger a rebuild and restart.

## Running Tests

### Unit Tests

```powershell
dotnet test tests/AzureCosmosDB.MCP.Toolkit.Tests
```

### Integration Tests

Integration tests require a running Cosmos DB instance (emulator or Azure):

```powershell
# Set test environment variables
$env:COSMOS_ENDPOINT = "your-cosmos-endpoint"
$env:COSMOS_KEY = "your-cosmos-key"

# Run tests
dotnet test tests/AzureCosmosDB.MCP.Toolkit.Tests --filter "Category=Integration"
```

## Building Docker Image Locally

```powershell
# Build
docker build -t mcp-toolkit:local -f Dockerfile .

# Run
docker run -p 8080:8080 `
    -e DEV_BYPASS_AUTH=true `
    -e COSMOS_ENDPOINT="your-endpoint" `
    mcp-toolkit:local
```

## Common Development Issues

### Port Already in Use

If port 8080 is occupied:

```powershell
# Find process using port 8080
netstat -ano | findstr :8080

# Kill the process (replace PID)
taskkill /PID <process-id> /F
```

### Cosmos DB Emulator Connection Issues

1. Ensure Cosmos DB Emulator is running
2. Trust the emulator's SSL certificate:
   ```powershell
   # Export certificate from emulator
   # Import to Trusted Root Certification Authorities
   ```
3. Or disable SSL validation (development only):
   ```powershell
   $env:COSMOS_DISABLE_SSL_VERIFICATION = "true"
   ```

## Next Steps

- Review [README.md](README.md) for deployment to Azure
- Check [TESTING_GUIDE.md](TESTING_GUIDE.md) for comprehensive testing strategies
- See [Configuration](README.md#configuration) for production environment setup

## Additional Resources

- [.NET 9.0 Documentation](https://docs.microsoft.com/dotnet/core/)
- [Azure Cosmos DB Emulator](https://docs.microsoft.com/azure/cosmos-db/local-emulator)
- [Model Context Protocol Specification](https://modelcontextprotocol.io)
