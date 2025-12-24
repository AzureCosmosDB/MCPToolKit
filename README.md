# Azure Cosmos DB MCP Toolkit

A Model Context Protocol (MCP) server that enables AI agents to interact with Azure Cosmos DB through natural language queries. Features enterprise-grade security with Azure Entra ID authentication, document operations, vector search, and schema discovery.

## Prerequisites

- Azure subscription ([Free account](https://azure.microsoft.com/free/))
- **Azure Cosmos DB account** ([Create account](https://learn.microsoft.com/azure/cosmos-db/nosql/quickstart-portal))
- **Azure OpenAI or Microsoft Foundry project** ([Create Azure OpenAI](https://learn.microsoft.com/azure/ai-services/openai/how-to/create-resource) or [Create Microsoft Foundry project](https://learn.microsoft.com/azure/ai-studio/how-to/create-projects)) (required for vector search with embeddings)
- Azure CLI ([Install](https://docs.microsoft.com/cli/azure/install-azure-cli)) installed and authenticated
- PowerShell 7+ ([Install](https://docs.microsoft.com/powershell/scripting/install/installing-powershell)) (for deployment scripts)
- **Docker Desktop** ([Install](https://www.docker.com/products/docker-desktop/)) installed and running
- .NET 9.0 SDK ([Install](https://dotnet.microsoft.com/download/dotnet/9.0)) (for local development)
- Git ([Install](https://git-scm.com/downloads))
- Azure Developer CLI ([Install](https://aka.ms/azure-dev/install)) (optional, only for `azd up` deployment method)

## What You Get

This toolkit provides:

- **Secure MCP Server**: JWT-authenticated endpoint for AI agents
- **Azure Cosmos DB Integration**: Full CRUD operations, vector search, and schema discovery
- **Microsoft Foundry Ready**: Optional one-step integration with Microsoft Foundry projects
- **Enterprise Security**: Azure Entra ID, Managed Identity, RBAC
- **Production Ready**: Container Apps hosting with auto-scaling
- **Local Development**: Docker Compose and .NET dev options

### MCP Tools Available

| Tool | Description |
|------|-------------|
| `list_databases` | List all databases in the Cosmos DB account |
| `list_collections` | List all containers in a database |
| `get_approximate_schema` | Sample documents to infer schema (top-level properties) |
| `get_recent_documents` | Get N most recent documents ordered by timestamp |
| `find_document_by_id` | Find a document by its id |
| `text_search` | Search for documents where a property contains a search phrase |
| `vector_search` | Perform vector search using Azure OpenAI embeddings |

## Project Structure

```
MCPToolKit/
├── src/AzureCosmosDB.MCP.Toolkit/    # Main .NET 9.0 MCP server
│   ├── Controllers/                   # MCP Protocol & Health endpoints
│   ├── Services/                      # Cosmos DB & Auth services
│   └── wwwroot/                       # Test UI
├── infrastructure/                    # Bicep templates
│   ├── deploy-all-resources.bicep    # Main infrastructure
│   └── modules/                       # Entra App & role assignments
├── scripts/                           # Deployment automation
│   ├── Deploy-Cosmos-MCP-Toolkit.ps1 # One-step deployment (recommended)
│   └── Setup-AIFoundry-Connection.ps1
├── client/                            # Python Microsoft Foundry client example
└── docs/                              # Additional documentation
```

## Quick Start

> Ensure all resources (Azure Cosmos DB, Microsoft Foundry Project, Container App) are created in the same resource group and that Docker is running before starting the deployment.

**First, clone the repository:**

```bash
git clone https://github.com/AzureCosmosDB/MCPToolKit.git
cd MCPToolKit
```

### Step 1: Deploy Infrastructure

Choose **ONE** of the following methods to deploy the infrastructure:

#### Option A: Deploy to Azure Button

Click the Deploy to Azure button to create all required Azure resources:

[![Deploy to Azure](https://aka.ms/deploytoazurebutton)](https://portal.azure.com/#create/Microsoft.Template/uri/https%3A%2F%2Fraw.githubusercontent.com%2FAzureCosmosDB%2FMCPToolKit%2Fmain%2Finfrastructure%2Fdeploy-all-resources.json)

**What gets deployed:**
- Azure Container Apps environment
- Azure Container Registry
- Managed Identity with RBAC assignments
- All networking and security configurations

**After deploying**, continue to **Step 2** to deploy the application.

---

#### Option B: Deploy via Azure Developer CLI (azd up)

> **Note**: Azure Developer CLI (`azd`) must be installed. If not installed, use [Option A](#option-a-deploy-to-azure-button) or install `azd`:
> - **Windows**: `winget install microsoft.azd`
> - **macOS/Linux**: `curl -fsSL https://aka.ms/install-azd.sh | bash`
> - Or download from: https://aka.ms/azure-dev/install

Deploy the complete infrastructure with a single command:

```bash
# Initialize the azd project (first time only)
azd init

# Set the environment variables to match the Cosmos DB you want to access
azd env set COSMOS_ENDPOINT "https://<your-cosmos-account>.documents.azure.com:443/"

# Set the environment variables to match the AI Foundry resource you want to use
azd env set AIF_PROJECT_ENDPOINT "https://<aifoundry-project-name>.<region>.api.azureml.ms/"
azd env set EMBEDDING_DEPLOYMENT_NAME "text-embedding-ada-002"

# Optional: Set embedding dimensions (default is 0, which uses the model's native dimensions)
# azd env set EMBEDDING_DIMENSIONS "1536"  # For text-embedding-3-large/small with specific dimensions

# Optional: Set AI Foundry project resource ID for automatic RBAC setup
azd env set AIF_PROJECT_RESOURCE_ID "/subscriptions/<subscription-id>/resourceGroups/<aifoundry-resource-group>/providers/Microsoft.MachineLearningServices/workspaces/<aifoundry-project-name>"

# Then deploy
azd up
```

**What gets deployed:**
- Azure Container Apps environment
- Azure Container Registry
- Managed Identity with RBAC assignments
- All networking and security configurations

**After deploying**, continue to **Step 2** to deploy the application.

---

### Step 2: Deploy MCP Server Application (Required for Both Options)

> **Note:** This step is required regardless of which deployment method you chose in Step 1.

**If you haven't cloned the repository yet:**

```bash
git clone https://github.com/AzureCosmosDB/MCPToolKit.git
cd MCPToolKit
```

**Run the deployment script from the repository root:**

> **Important for Windows users:** If you cloned using Git Bash, open **PowerShell** to run the deployment script (the script requires PowerShell, not Bash).

```powershell
# From the MCPToolKit directory
.\scripts\Deploy-Cosmos-MCP-Toolkit.ps1 -ResourceGroup "YOUR-RESOURCE-GROUP"

# Optional: Specify a custom Entra App name if the default name is already taken
# or if you don't have permissions to modify the existing app
.\scripts\Deploy-Cosmos-MCP-Toolkit.ps1 -ResourceGroup "YOUR-RESOURCE-GROUP" -EntraAppName "My Custom MCP App"
```

This script:
- Builds and deploys the MCP server Docker image
- Creates Entra ID app registration for authentication
- Configures all security and permissions
- Outputs configuration to `deployment-info.json`

#### Troubleshooting: Authorization Errors During Deployment

If you encounter an **"Authorization_RequestDenied"** or **"Insufficient privileges"** error when the script tries to assign the app role to your user, this is expected in certain scenarios.

**Why this happens:**

Even if you own the Entra App, assigning app roles to users requires elevated Microsoft Graph API permissions that you may not have:
- **Required permission**: `AppRoleAssignment.ReadWrite.All`
- **Your account**: May only have basic user permissions

**Solution - Manual Role Assignment:**

The deployment script will continue successfully, but you'll need to manually assign yourself the role to use the web UI:

**Quick Method - Use the Script:**

```powershell
.\scripts\Assign-Role-To-Current-User.ps1
```

This automatically assigns the role to your account (works for all account types including Visual Studio subscriptions).

**Manual Method - Via Azure Portal:**

1. Go to [Azure Portal](https://portal.azure.com) → **Enterprise Applications**
2. Search for "**Azure Cosmos DB MCP Toolkit API**" (or your custom app name)
3. Click **Users and groups** in the left menu
4. Click **+ Add user/group**
5. Under **Users**, click **None Selected**
6. Search for and select your user account
7. Under **Select a role**, click **None Selected**
8. Select the **Mcp.Tool.Executor** role
9. Click **Assign**

**To Assign Roles to Teammates:**

```powershell
.\scripts\Assign-Role-To-Users.ps1 -UserEmails "user1@company.com,user2@company.com"
```

**To Verify Role Assignments:**

```powershell
.\scripts\Verify-Role-Assignments.ps1
```

**Alternative - Use a Different App Name:**

If you don't have permissions to access the existing app, create a new one:

```powershell
.\scripts\Deploy-Cosmos-MCP-Toolkit.ps1 -ResourceGroup "YOUR-RESOURCE-GROUP" -EntraAppName "My Custom MCP App"
```

> **Note**: The Container App's managed identity roles (Cosmos DB, Azure OpenAI) are assigned automatically and don't require these elevated permissions. Only your personal web UI access requires manual role assignment if you lack Graph API permissions.

### Step 3: Test Your Deployment

Open the test UI: `https://YOUR-CONTAINER-APP.azurecontainerapps.io`

Or call the health endpoint:

```bash
curl https://YOUR-CONTAINER-APP.azurecontainerapps.io/health
```

All connection details are saved in `deployment-info.json` for reference.

## Troubleshooting

If you encounter issues during deployment or testing, see the comprehensive [Troubleshooting Guide](docs/TROUBLESHOOTING-DEPLOYMENT.md).

**Common issues:**
- ⚠️ [Invalid or expired token (HTTP 401)](docs/TROUBLESHOOTING-DEPLOYMENT.md#invalid-or-expired-token-http-401-when-testing) - Role assignment required
- ⚠️ [User not found / Visual Studio subscriptions](docs/TROUBLESHOOTING-DEPLOYMENT.md#user-not-found---visual-studio-subscriptions--personal-accounts) - Use role assignment scripts
- ⚠️ [Service management reference error](docs/TROUBLESHOOTING-DEPLOYMENT.md#1-entra-app-creation-fails---service-management-reference-required) - Manual app creation steps
- ⚠️ [ACR login fails](docs/TROUBLESHOOTING-DEPLOYMENT.md#3-acr-login-fails---resource-not-found) - Resource group mismatch
- ⚠️ [Docker push fails](docs/TROUBLESHOOTING-DEPLOYMENT.md#docker-push-fails---networkssl-errors) - Network connectivity

## Microsoft Foundry Integration  

To connect your MCP server to a Microsoft Foundry project:

**Option 1: Using Resource ID**

```powershell
.\scripts\Setup-AIFoundry-Connection.ps1 `
  -AIFoundryProjectResourceId "/subscriptions/xxx/resourceGroups/my-rg/providers/Microsoft.CognitiveServices/accounts/my-hub/projects/my-project" `
  -ConnectionName "cosmos-mcp-connection"
```

**Option 2: Using Project Name and Account Name**

```powershell
.\scripts\Setup-AIFoundry-Connection.ps1 `
  -AIFoundryProjectName "YOUR-PROJECT-NAME" `
  -AIFoundryAccountName "YOUR-ACCOUNT-NAME" `
  -ResourceGroup "YOUR-RESOURCE-GROUP"
```

> **Note**: The account name is your Microsoft Foundry hub/account name (not the project name). If you omit `-ResourceGroup`, the script will attempt to auto-detect it.

This assigns the necessary roles for Microsoft Foundry to call your MCP server.

### Use Azure Cosmos DB MCP in Microsoft Foundry

**Via Microsoft Foundry UI:**

1. Navigate to your Microsoft Foundry project
2. Go to **Build** → **Create agent**  
3. Select the **+ Add** in the tools section
4. Select the **Catalog** tab 
5. Choose **Azure Cosmos DB** as the tool and click **Create**

   ![Add Tool from Catalog](images/ai_foundry_ui_mcp_connect.png)

6. Select **Microsoft Entra** → **Project Managed Identity** as the authentication method
7. Enter your `<entra-app-client-id>` as the audience. This is the value from the deployment output.

   ![MCP Connection Configuration](images/ai_foundry_ui_add_tool.png)
   > [!TIP]
   > Find the `ENTRA_APP_CLIENT_ID` value in your `deployment-info.json` file or run:
   > ```powershell
   > Get-Content deployment-info.json | ConvertFrom-Json | Select-Object -ExpandProperty entraAppClientId
   > ```

8. Add instructions to your agent:

   ![Agent Instructions](images/ai_foundry_instructions.png)

    ```
    You are a helpful agent that can use MCP tools to assist users. Use the available MCP tools to answer questions and perform tasks.
    "parameters":      
      {
            "databaseId": "<DATABASE_NAME>",
            "containerId": "<CONTAINER_NAME>"
      },
    "learn": true
    ```

9. Test MCP server in Microsoft Foundry Playground using natural language queries:
    ```
    List all databases in my Cosmos DB account
    ```

    ```
    Show me the latest 10 documents from the products container
    ```

    ```
    What's the schema of the customers container?
    ```

    ```
    Search for documents where the name contains "Azure"
    ```

> **Note**: The MCP server provides secure access to Azure Cosmos DB data through conversational AI interfaces.

**Python Test Client:**

See the [Python Client README](client/README.md) for a complete example of using the MCP server with Microsoft Foundry agents.

## Configuration

### VS Code Configuration

To use with GitHub Copilot or other VS Code MCP clients:

#### Step 1: Get Your MCP Server URL

Find your Container App URL in `deployment-info.json`:

```powershell
Get-Content deployment-info.json | ConvertFrom-Json | Select-Object -ExpandProperty containerAppUrl
```

Or from Azure Portal: **Container Apps** → Your app → **Overview** → **Application Url**

#### Step 2: Get Your JWT Bearer Token

You need a valid Azure AD token for authentication. Use Azure CLI:

```bash
# Get the Entra App Client ID from deployment-info.json
az login

# Get a token for your MCP server
# Replace YOUR-ENTRA-APP-CLIENT-ID with the value from deployment-info.json
az account get-access-token --resource YOUR-ENTRA-APP-CLIENT-ID --query accessToken -o tsv
```

**Quick command to get Client ID:**

```powershell
# Get the Client ID
$clientId = (Get-Content deployment-info.json | ConvertFrom-Json).entraAppClientId
Write-Host "Your Entra App Client ID: $clientId"

# Get the token (copy the output)
az account get-access-token --resource $clientId --query accessToken -o tsv
```

**Alternative - Use API URI:**

```bash
# If you configured a custom API URI, you can also use that
az account get-access-token --resource "api://YOUR-ENTRA-APP-CLIENT-ID" --query accessToken -o tsv
```

> **Note**: JWT tokens typically expire after 1 hour. You'll need to refresh the token periodically by running the command again.

#### Step 3: Add to VS Code Settings

Add the configuration to your VS Code `settings.json`:

```json
{
  "mcp.servers": {
    "cosmosdb": {
      "url": "https://YOUR-CONTAINER-APP.azurecontainerapps.io/mcp",
      "headers": {
        "Authorization": "Bearer YOUR-JWT-TOKEN"
      }
    }
  }
}
```

**Complete example with real values:**

```json
{
  "mcp.servers": {
    "cosmosdb": {
      "url": "https://mcp-toolkit-app.icywave-532ba7dd.westus2.azurecontainerapps.io/mcp",
      "headers": {
        "Authorization": "Bearer eyJ0eXAiOiJKV1QiLCJhbGc..."
      }
    }
  }
}
```

#### Troubleshooting Token Issues

If you get authentication errors:

1. **Token Expired**: Get a fresh token using the `az account get-access-token` command
2. **Invalid Audience**: Ensure the `--resource` parameter matches your Entra App Client ID
3. **User Not Assigned Role**: Run `.\scripts\Assign-Role-To-Current-User.ps1` to assign the required role
4. **Wrong Client ID**: Verify the Client ID in `deployment-info.json` matches what you're using

## Security

> **⚠️ IMPORTANT**: After granting permissions, the MCP Server will have read access to all databases and containers in the associated Cosmos DB account. Any agent or application that successfully authenticates with the server can execute read operations on the Cosmos DB databases and containers. Ensure you only grant access to trusted users and applications.

### Authentication

- **JWT Bearer Tokens**: All requests require valid Microsoft Entra ID tokens
- **Audience Validation**: Tokens must be issued for your Entra App
- **Managed Identity**: Container App uses managed identity for Cosmos DB access
- **RBAC**: Least-privilege role assignments



## Additional Resources

- [Architecture Diagrams](docs/ARCHITECTURE-DIAGRAMS.md) - System architecture, component interactions, and deployment topology diagrams
- [Web Testing Guide](docs/WEB-TESTING-GUIDE.md) - Using the browser-based test UI to interact with the MCP server

## License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

## Contributing

Contributions are welcome! Please feel free to submit a Pull Request.

1. Fork the repository
2. Create your feature branch: `git checkout -b feature/amazing-feature`
3. Commit your changes: `git commit -m 'Add amazing feature'`
4. Push to the branch: `git push origin feature/amazing-feature`
5. Open a Pull Request
