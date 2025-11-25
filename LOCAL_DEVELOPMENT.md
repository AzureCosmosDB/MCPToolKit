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

### Production Environment Variables

| Variable | Description | Required |
|----------|-------------|----------|
| `COSMOS_ENDPOINT` | Cosmos DB account endpoint | Yes |
| `OPENAI_ENDPOINT` | Azure OpenAI endpoint (for vector search) | Optional |
| `OPENAI_EMBEDDING_DEPLOYMENT` | Embedding model deployment name | Optional |
| `ENTRA_CLIENTID` | Entra App Client ID for JWT validation | Yes (production) |
| `ENTRA_AUTHORITY` | Entra authority URL | Yes (production) |

### Local Development Variables

Create a `.env` file or set these additional environment variables for local development:

| Variable | Description | Local Example |
|----------|-------------|---------------|
| `DEV_BYPASS_AUTH` | Bypass authentication | `true` |
| `COSMOS_ENDPOINT` | Cosmos DB endpoint | `https://localhost:8081/` (emulator) |
| `COSMOS_KEY` | Cosmos DB key (emulator only) | Emulator default key |
| `OPENAI_ENDPOINT` | Microsoft Foundry/OpenAI endpoint | Your Azure OpenAI endpoint |
| `OPENAI_EMBEDDING_DEPLOYMENT` | Embedding model name | `text-embedding-ada-002` |

## Using Cosmos DB Emulator

### Install Cosmos DB Emulator

Download and install from: https://aka.ms/cosmosdb-emulator

### Configure Connection

When using the emulator, set:

```powershell
$env:COSMOS_ENDPOINT = "https://localhost:8081/"
$env:COSMOS_KEY = "C2y6yDjf5/R+ob0N8A7Cgv30VRDJIWEHLM+4QDU5DE2nQ9nDuVTqobD4b8mGGyPMbIZnqyMsEcaGQy67XIw/Jw=="
```

> **Note**: The Cosmos DB emulator uses a well-known authentication key for local development.

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
