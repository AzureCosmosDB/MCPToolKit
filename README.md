# Azure Cosmos DB MCP Toolkit

A Model Context Protocol (MCP) toolkit that provides seamless integration with Azure Cosmos DB and Azure OpenAI for document querying, vector search, and schema inspection through AI agents.

## Overview

This Azure Cosmos DB MCP Toolkit is a starter sample for hosting an MCP Server to enable AI agents to interact with Azure Cosmos DB. It supports traditional document queries, full-text search, vector similarity search using Azure OpenAI embeddings, and schema discovery. All operations use Entra ID (Azure AD) authentication for secure, enterprise-grade access to Azure services.

**Key Features:**
- 🔍 Document querying and full-text search
- 🧠 AI-powered vector similarity search with Azure OpenAI embeddings
- 📊 Container schema discovery and analysis
- 🔐 Secure Entra ID authentication
- 🏷️ Model Context Protocol integration for AI agents
- ⚡ Real-time query execution with comprehensive error handling

## Todo
- 🚧 Host in Azure Container Apps (or Azure Functions)
- Expose an MCP Server endpoint from hosting platform (ACA, AF)
- Authenticate to MCP Server via EntraID/MI
- Test via Azure AI Foundry Agents Service
- Security planning / eval
- Robustness work
- Refactoring
- more (TBD)

## Supported Tools

### Database & Container Management
- **`ListDatabases`** - Lists all databases available in the Cosmos DB account
- **`ListCollections`** - Lists containers (collections) for a specified database

### Document Querying
- **`GetRecentDocuments`** - Gets the most recent N documents ordered by timestamp (_ts DESC). N must be between 1-20
- **`FindDocumentByID`** - Finds a specific document by its ID in the specified database/container
- **`TextSearch`** - Performs full-text search on a specified property using FullTextContains. N must be between 1-20

### Schema Discovery
- **`GetApproximateSchema`** - Analyzes up to 10 sample documents to infer the container's schema, including property names, data types, and frequency of occurrence

### AI-Powered Vector Search
- **`VectorSearch`** - Performs semantic vector search using Azure OpenAI embeddings. Finds documents that are semantically similar to the input text. N must be between 1-50
  - Automatically generates embeddings for search text
  - Returns results with similarity scores
  - Supports custom property projection
  - No wildcard (`*`) selection allowed - must specify explicit properties

## Security Considerations

⚠️ **IMPORTANT SECURITY NOTICE**

This MCP Toolkit uses Entra ID (Azure AD) and Managed Identities to connect securely to Azure Cosmos DB and Azure OpenAI resources. However, it's critical to understand the security implications of deploying this toolkit:

### Data Access and Exposure
- **Any data accessible to this MCP server can potentially be exposed to connected AI agents or applications**
- The MCP server can read any document in the databases and containers it has access to
- Connected agents may request and receive sensitive data through the available tools

### Access Control Requirements
- **Grant RBAC permissions ONLY to specific databases and containers** that you want AI agents to access
- Use the principle of least privilege - don't grant broad access to your entire Cosmos DB account
- Regularly review and audit the permissions granted to the MCP server's identity
- Consider creating dedicated databases/containers for AI agent access rather than sharing production data

### Network and Infrastructure Security
- **Isolate the MCP server** within your network infrastructure
- Use private endpoints for Cosmos DB when possible
- Implement proper network security groups and firewall rules
- Monitor and log all access to the MCP server endpoint

### Authentication and Authorization
- The MCP server uses `DefaultAzureCredential` which supports Managed Identity in Azure environments
- Ensure the hosting environment (Azure Container Apps, Azure Functions, etc.) has Managed Identity enabled
- Regularly rotate any service principal credentials if used
- Implement additional authentication layers for accessing the MCP server itself

### Data Classification
- **Only expose non-sensitive or properly classified data** through this toolkit
- Consider data masking or anonymization for sensitive fields
- Implement data loss prevention (DLP) policies where appropriate
- Review data retention and deletion policies for accessed data

### Monitoring and Auditing
- Enable logging and monitoring for all MCP server operations
- Set up alerts for unusual access patterns or high-volume data requests
- Regularly audit which agents and applications are connected to the MCP server
- Monitor Azure Cosmos DB access logs and metrics

**Recommendation**: Start with a dedicated, isolated Cosmos DB account containing only non-sensitive test data when first deploying this toolkit.

## Prerequisites

### Azure Resources Required
1. **Azure Cosmos DB Account** with NoSQL API
2. **Azure OpenAI Service** with an embedding model deployment
3. **Entra ID (Azure AD)** identity with appropriate permissions

### Software Requirements
- .NET 9.0 SDK
- Visual Studio Code with GitHub Copilot extension

## Setup Instructions

### 1. Azure Cosmos DB Setup

#### Configure Role-Based Access Control (RBAC)
Grant your identity the necessary permissions:

```bash
# Get your user object ID
USER_ID=$(az ad signed-in-user show --query id -o tsv)

# Assign Cosmos DB Built-in Data Contributor role
az cosmosdb sql role assignment create \
  --account-name your-cosmosdb-account \
  --resource-group your-resource-group \
  --scope "/" \
  --principal-id $USER_ID \
  --role-definition-id 00000000-0000-0000-0000-000000000002
```

**Required Permissions:**
- `Microsoft.DocumentDB/databaseAccounts/readMetadata` - List databases and containers
- `Microsoft.DocumentDB/databaseAccounts/sqlDatabases/containers/items/read` - Read documents
- `Microsoft.DocumentDB/databaseAccounts/sqlDatabases/containers/executeQuery` - Execute queries

### 2. Azure OpenAI Setup

#### Configure RBAC for OpenAI
```bash
# Assign Cognitive Services OpenAI User role
az role assignment create \
  --assignee $USER_ID \
  --role "Cognitive Services OpenAI User" \
  --scope /subscriptions/your-subscription-id/resourceGroups/your-resource-group/providers/Microsoft.CognitiveServices/accounts/your-openai-service
```

### 3. Environment Variables Configuration

Create environment variables for the MCP server:

#### Windows (PowerShell)
```powershell
$env:COSMOS_ENDPOINT = "https://your-cosmosdb-account.documents.azure.com:443/"
$env:OPENAI_ENDPOINT = "https://your-openai-service.openai.azure.com/"
$env:OPENAI_EMBEDDING_DEPLOYMENT = "text-embedding-ada-002"
```

#### macOS/Linux (Bash)
```bash
export COSMOS_ENDPOINT="https://your-cosmosdb-account.documents.azure.com:443/"
export OPENAI_ENDPOINT="https://your-openai-service.openai.azure.com/"
export OPENAI_EMBEDDING_DEPLOYMENT="text-embedding-ada-002"
```

#### Using .env file (Development)
Create a `.env` file in your project root:
```env
COSMOS_ENDPOINT=https://your-cosmosdb-account.documents.azure.com:443/
OPENAI_ENDPOINT=https://your-openai-service.openai.azure.com/
OPENAI_EMBEDDING_DEPLOYMENT=your-deployment-name
```

## Local Development Setup 
In this local setup, you can test the MCP toolkit a local dev environment such as using VSCode with GitHub Copilot.

### 1. Clone and Build
```bash
git clone <repository-url>
cd AzureCosmosDBMCP
dotnet restore
dotnet build
```

### 2. Run the MCP Server
```bash
dotnet run
```
The server will start on `http://localhost:3001`

### 3. Configure VS Code for GitHub Copilot

Create or update your local `.vscode/mcp.json` file in your VS Code project directory

```json
{
  "servers": {
    "azure-cosmos-db-mcp": {
      "type": "http",
      "url": "http://localhost:3001"
    }
  }
}
```

### 4. Restart VS Code
After creating the MCP configuration, restart VS Code to load the new MCP server.

### 5. Test the Integration
Open GitHub Copilot Chat in VS Code and try commands like:
- "List all databases in my Cosmos DB account"
- "Show me the schema for container 'products' in database 'ecommerce'"
- "Find documents similar to 'laptop computer' in the products container"
- "Get the 5 most recent orders from the orders container"

## Usage Examples

### Basic Document Queries
```
@copilot List databases in my Cosmos DB account

@copilot Show containers in the 'ecommerce' database

@copilot Get the last 10 documents from the 'orders' container in 'ecommerce' database

@copilot Find document with ID '12345' in the 'products' container
```

### Schema Discovery
```
@copilot What's the schema of the 'customers' container in 'ecommerce' database?

@copilot Analyze the structure of documents in the 'inventory' container
```

### Text Search
```
@copilot Search for documents containing 'electronics' in the 'description' property of 'products' container

@copilot Find orders where the 'status' contains 'shipped' in the last 15 results
```

### Vector Search (Semantic Search)
```
@copilot Find products similar to 'wireless headphones' and return id, name, price from the 'products' container using the 'contentVector' property

@copilot Search for documents semantically similar to 'customer service complaint' in the 'feedback' container, return id, subject, content using vector property 'embeddings'
```

## Vector Search Setup

For vector search functionality, your Cosmos DB documents need to contain vector embeddings. Here's an example document structure:

```json
{
  "id": "product-123",
  "name": "Wireless Bluetooth Headphones",
  "description": "High-quality wireless headphones with noise cancellation",
  "category": "Electronics",
  "price": 199.99,
  "contentVector": [0.1, 0.2, 0.3, ...], // 1536-dimensional embedding array
  "_ts": 1234567890
}
```

The `contentVector` field contains the embedding generated by an Azure OpenAI's embedding model for the product's text content.

## Troubleshooting

### Common Issues

#### Authentication Errors
- **Error**: `Unauthorized` or `Forbidden`
- **Solution**: Verify Entra ID permissions and ensure you're logged in with `az login`

#### Environment Variables
- **Error**: `Missing required environment variable`
- **Solution**: Double-check environment variable names and values

#### Vector Search Issues
- **Error**: Vector search returning no results
- **Solution**: Ensure documents have vector embeddings and the vectorProperty parameter matches your schema

#### Connection Issues
- **Error**: Cannot connect to Cosmos DB
- **Solution**: Verify the COSMOS_ENDPOINT URL and network connectivity

### Debug Mode
Run with verbose logging:
```bash
dotnet run --environment Development
```

### Verify Configuration
Test environment variables:
```bash
# Windows
echo $env:COSMOS_ENDPOINT
echo $env:OPENAI_ENDPOINT

# macOS/Linux  
echo $COSMOS_ENDPOINT
echo $OPENAI_ENDPOINT
```

## Support
For issues and questions:
1. Check the troubleshooting section above
2. Review Azure Cosmos DB documentation
3. Check Azure OpenAI service status
4. Open an issue in this repository