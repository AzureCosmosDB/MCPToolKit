# Scripts Directory# Scripts Directory



This directory contains deployment and testing scripts for the Azure Cosmos DB MCP Toolkit.This directory contains deployment and testing scripts for the Azure Cosmos DB MCP Toolkit.



## 🚀 Deployment Scripts## 🚀 Deployment Scripts



### `Deploy-CosmosMcpServer.ps1` (Windows PowerShell)### `Deploy-CosmosMcpServer.ps1` (Windows PowerShell)

**Primary deployment script** for Windows that creates everything automatically:**Primary deployment script** for Windows that creates everything automatically:

- ✅ Entra ID App Registration with `Mcp.Tool.Executor` role- ✅ Entra ID App Registration with `Mcp.Tool.Executor` role

- ✅ Azure Container Apps infrastructure- ✅ Azure Container Apps infrastructure

- ✅ Azure Container Registry- ✅ Azure Container Registry

- ✅ Complete authentication setup- ✅ Complete authentication setup



**Usage:****Usage:**

```powershell```powershell

.\Deploy-CosmosMcpServer.ps1 -ResourceGroup "rg-mcp-demo".\Deploy-CosmosMcpServer.ps1 -ResourceGroup "rg-mcp-demo"

``````



### `deploy-cosmos-mcp-server.sh` (Bash)### `deploy-cosmos-mcp-server.sh` (Bash)

**Primary deployment script** for Linux/macOS with the same functionality:**Primary deployment script** for Linux/macOS with the same functionality:



**Usage:****Usage:**

```bash```bash

./deploy-cosmos-mcp-server.sh --resource-group "rg-mcp-demo"./deploy-cosmos-mcp-server.sh --resource-group "rg-mcp-demo"

``````



## 🧪 Testing Scripts./deploy-cosmos-mcp-server.sh --resource-group "rg-mcp-toolkit-demo"**Usage**:



### `test-deployment.sh````powershell

Validates your deployment by testing:

- Health endpoints# PowerShell.\scripts\Deploy-Complete.ps1 `

- Authentication security (401 responses)

- MCP protocol endpoints.\Deploy-CosmosMcpServer.ps1 -ResourceGroup "rg-mcp-toolkit-demo"    -ResourceGroupName "rg-mcp-toolkit" `



**Usage:**```    -Location "East US" `

```bash

./test-deployment.sh    -PrincipalId "your-user-object-id" `

```

## Testing Scripts    -CosmosEndpoint "https://yourcosmosdb.documents.azure.com:443/" `

### `validate-setup.ps1`

PowerShell validation script for Windows users.    -OpenAIEndpoint "https://youropenai.openai.azure.com/" `



## 🔑 Authentication Utilities### `test-deployment.sh`    -OpenAIEmbeddingDeployment "text-embedding-ada-002"



### `Get-AzureToken.ps1`Validates your deployment by testing:```

Gets Azure AD access tokens for testing your deployed MCP server.

- Health endpoints

**Usage:**

```powershell- Authentication security (401 responses)### `deploy-complete.sh` (Linux/macOS Bash)

.\Get-AzureToken.ps1

```- CORS configuration**Purpose**: Cross-platform equivalent of Deploy-Complete.ps1  



### `get-access-token.sh`- Provides usage instructions**Usage**:

Bash version of the token utility for Linux/macOS.

```bash

**Usage:**

```bash**Usage:**export RESOURCE_GROUP_NAME="rg-mcp-toolkit"

./get-access-token.sh

``````bashexport LOCATION="East US"  



## 🛠️ Local Developmentchmod +x test-deployment.shexport PRINCIPAL_ID="your-user-object-id"



### `setup-cosmos-cert.sh` & `Setup-CosmosCert.ps1`./test-deployment.shexport COSMOS_ENDPOINT="https://yourcosmosdb.documents.azure.com:443/"

Sets up SSL certificates for local Cosmos DB emulator development.

```export OPENAI_ENDPOINT="https://youropenai.openai.azure.com/"

### `Test-ManagedIdentityAuth.ps1` & `Test-MCPWithAAD.ps1`

Advanced testing scripts for managed identity and Azure AD authentication.export OPENAI_EMBEDDING_DEPLOYMENT="text-embedding-ada-002"



---## Utility Scripts./scripts/deploy-complete.sh



All scripts include comprehensive error handling and detailed output to guide you through the deployment and testing process.```

### Authentication Token Scripts

- `Get-AADToken.ps1` - Get Azure AD access tokens for testing## 🔍 Validation Scripts

- `Get-AzureToken.ps1` - Get Azure resource tokens

- `Test-ManagedIdentityAuth.ps1` - Test managed identity authentication### `validate-setup.ps1` (Windows PowerShell)

- `Test-MCPWithAAD.ps1` - Test MCP with Azure AD tokens**Purpose**: Pre-deployment environment validation  

**What it checks**:

### Certificate Scripts- Azure CLI installation and login status

- `setup-cosmos-cert.sh` & `Setup-CosmosCert.ps1` - Set up Cosmos DB emulator certificates for local development- Docker installation and status

- Required permissions and subscriptions

### Validation Scripts- Network connectivity to Azure

- `validate-setup.ps1` - Validate deployment configuration

**Usage**:

## Usage Examples```powershell

.\scripts\validate-setup.ps1

### Complete Deployment```

```bash

# Deploy everything## 🔐 Development Scripts

./deploy-cosmos-mcp-server.sh --resource-group "rg-mcp-demo"

### `Setup-CosmosCert.ps1` (Windows PowerShell)

# Test deployment**Purpose**: Download and install Cosmos DB emulator certificate  

./test-deployment.sh**When to use**: Docker Compose local development with SSL connections  

**Usage**:

# Get access token and test```powershell

ACCESS_TOKEN=$(az account get-access-token --resource "api://your-app-id" --query "accessToken" -o tsv).\scripts\Setup-CosmosCert.ps1

curl -H "Authorization: Bearer $ACCESS_TOKEN" https://your-app.azurecontainerapps.io/mcp```

```

### `setup-cosmos-cert.sh` (Linux/macOS Bash)

### Local Development**Purpose**: Cross-platform certificate setup for Cosmos emulator  

```bash**Usage**:

# Set up Cosmos DB emulator certificates```bash

./setup-cosmos-cert.sh./scripts/setup-cosmos-cert.sh

```

# Validate local setup

powershell -File validate-setup.ps1## 📋 Important: Post-Deployment RBAC Setup

```

After running the deployment scripts, you **must manually configure RBAC permissions** for your external resources:

All scripts include comprehensive error handling and detailed output to guide you through the deployment and testing process.
1. **Grant the Managed Identity access to your Cosmos DB**
2. **Grant the Managed Identity access to your Azure OpenAI**

See the [Deploy to Azure Guide](../docs/deploy-to-azure-guide.md) for detailed RBAC setup instructions.

## 📋 Alternative Deployment Methods

If you don't want to use these scripts, you can deploy using:

1. **Azure Portal Deploy Button**: Use the "Deploy to Azure" button in README.md
2. **Direct Bicep**: Deploy `infrastructure/deploy-all-resources.bicep` manually
3. **Azure CLI**: Deploy the Bicep template directly with `az deployment group create`

## � What Changed

**Migration from Full Infrastructure to Container-Only Deployment**:
- ✅ **Now**: Only deploys Container App infrastructure 
- ✅ **Requires**: Existing Cosmos DB and Azure OpenAI resources
- ✅ **Manual**: RBAC permissions setup required post-deployment
- ❌ **Removed**: Automatic Cosmos DB and Azure OpenAI creation
- ❌ **Removed**: Log Analytics workspace creation
- ❌ **Removed**: Automatic RBAC configuration for external resources