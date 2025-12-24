# Azure Cosmos DB MCP Server - Web Testing Guide

This guide shows you how to test your Azure Cosmos DB MCP Server using the secure web interface with enterprise-grade Microsoft Entra authentication.

## 🌐 Web Interface Overview

The Azure Cosmos DB MCP Toolkit includes an enhanced web interface that provides:

- ✅ **Secure Microsoft Entra Authentication** - No token copy/paste required
- ✅ **Interactive MCP Tool Testing** - Forms for all Cosmos DB operations  
- ✅ **Real-time JSON-RPC Calls** - Direct protocol testing
- ✅ **Auto-generated cURL Examples** - For automation and scripting
- ✅ **Role-based Security** - Validates `Mcp.Tool.Executor` permissions
- ✅ **Enterprise Compliance** - Uses Microsoft Authentication Library (MSAL)

## 📥 Getting Started

### Option 1: Use the Deployed Web Interface (Recommended)

The web interface is **automatically deployed** with your Container App:

1. **Find your Container App URL** from deployment output or `scripts/deployment-info.json`
2. **Open in browser**: `https://your-container-app-url.azurecontainerapps.io/`
3. **Start testing** - No additional setup required!

Example:
```
https://mcp-toolkit-app.icywave-532ba7dd.westus2.azurecontainerapps.io/
```

### Option 2: Test Locally (Development)

If you want to test against your local development server:

```bash
# Clone the repository
git clone https://github.com/AzureCosmosDB/MCPToolKit.git
cd MCPToolKit

# Run the application locally
cd src/AzureCosmosDB.MCP.Toolkit
dotnet run

# Open browser to local URL
# http://localhost:8080/
```

### Option 3: Standalone HTML File

To use the web interface without running the full application:

```bash
# Copy the HTML file from the repository
cp src/AzureCosmosDB.MCP.Toolkit/wwwroot/index.html cosmos-mcp-client.html

# Start a simple HTTP server
python -m http.server 3000

# Open browser
# http://localhost:3000/cosmos-mcp-client.html
```

## 🔐 Authentication Setup

### Get Your Client ID

Your Client ID is created automatically during deployment. Find it in:

1. **From deployment output**: Check `scripts/deployment-info.json`
2. **From Azure Portal**: Go to Azure Active Directory > App Registrations
3. **From Azure CLI**:
   ```bash
   az ad app list --display-name "*cosmos*" --query "[].{Name:displayName, ClientId:appId}"
   ```

### Configure the Web Interface

1. **Enter Client ID**: Paste your Entra ID app's Client ID
2. **Tenant ID**: Leave empty to use your default tenant (or specify if needed)
3. **Server URL**: Your deployed MCP server URL (from deployment-info.json)

### Secure Login Process

1. **Click "🔑 Sign In with Microsoft Entra"**
2. **Microsoft login popup appears** - standard OAuth flow
3. **Use your corporate/personal Microsoft account**
4. **Grant permissions** if prompted
5. **Success**: Shows ✅ Authenticated with your user info

## 🧪 Testing MCP Tools

### Available Cosmos DB Tools

1. **`list_databases`** - List all databases in your Cosmos DB account
2. **`list_collections`** - List containers in a specific database
3. **`get_recent_documents`** - Get recent documents from a container
4. **`find_document_by_id`** - Find a specific document by ID
5. **`text_search`** - Full-text search within documents
6. **`vector_search`** - Semantic search using AI embeddings
7. **`get_approximate_schema`** - Analyze document structure

### Interactive Testing

1. **List Tools**: Click to see all available MCP tools
2. **Expand "Test Cosmos DB Tools"** section
3. **Fill in parameters**:
   - Database ID: Your Cosmos DB database name
   - Container ID: Your container name
   - Tool-specific parameters (document ID, search terms, etc.)
4. **Select tool** from dropdown
5. **Click "Invoke Selected Tool"**

### Example Test Scenarios

#### Basic Database Exploration
```
1. Click "List Tools" - See all available tools
2. Select "list_databases" - No parameters needed
3. Click "Invoke Selected Tool" - See your databases
4. Enter a database name
5. Select "list_collections" - See containers in that database
```

#### Document Querying
```
1. Enter Database ID: "your-db-name"
2. Enter Container ID: "your-container-name" 
3. Select "get_recent_documents"
4. Set result count: 5
5. Click "Invoke Selected Tool" - See recent documents
```

#### Advanced Search
```
1. Configure database and container
2. Select "text_search"
3. Property: "name" (or any property in your documents)
4. Search Phrase: "Azure" (or relevant search term)
5. Result count: 10
6. Click "Invoke Selected Tool" - See matching documents
```

## 🔧 Troubleshooting

### Common Issues

#### "Authentication Failed"
- **Check**: Client ID is correct
- **Check**: User has `Mcp.Tool.Executor` role assigned
- **Solution**: Assign role with:
  ```bash
  az ad app role assignment create \
    --id "your-client-id" \
    --principal "user@domain.com" \
    --role "Mcp.Tool.Executor"
  ```

#### "CORS Error" 
- **Expected**: Browser security prevents direct calls
- **Solution**: Use the generated cURL commands instead
- **Alternative**: Test from command line or deployed frontend

#### "404 Not Found"
- **Check**: Server URL is correct and accessible
- **Check**: MCP server is running and healthy
- **Test**: Visit `https://your-server-url/health`

#### "No Databases/Containers Found"
- **Check**: MCP server has access to Cosmos DB
- **Check**: Cosmos DB account has data
- **Verify**: Connection strings and permissions

### Security Validation

The interface automatically validates:
- ✅ Valid Microsoft Entra token
- ✅ Correct audience (`api://your-client-id`)
- ✅ Required role claims (`Mcp.Tool.Executor`)
- ✅ Token expiration and refresh

## 📋 Using Generated cURL Commands

The interface generates ready-to-use cURL commands:

```bash
# Copy from the "Equivalent cURL Commands" section
curl -X POST "https://your-app.azurecontainerapps.io/mcp" \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer eyJ0eXAiOiJKV1Q..." \
  -d '{"jsonrpc":"2.0","method":"tools/list","id":1}'
```

Use these for:
- **Automation scripts**
- **CI/CD pipelines** 
- **Command line testing**
- **Integration with other tools**

## 🚀 Next Steps

After successful web testing:

1. **Integrate with Microsoft Foundry** - Connect as MCP server
2. **Automate with scripts** - Use generated cURL commands
3. **Deploy to production** - Scale your MCP server
4. **Monitor usage** - Check Microsoft Entra logs and Container App metrics

## 📞 Support

- **Health Endpoint**: `GET /health` - Check server status
- **GitHub Issues**: Report problems with detailed logs
- **Azure Logs**: Check Container App logs for server-side issues
- **Authentication Logs**: Review Microsoft Entra sign-in logs

The web interface provides the same professional testing experience as the PostgreSQL MCP demo, with enterprise-grade security that your IT team will approve! 🛡️