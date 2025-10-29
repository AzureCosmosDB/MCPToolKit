# Azure Cosmos DB MCP Toolkit - Deployment Scripts# Azure Cosmos DB MCP Toolkit - Deployment Scripts# Scripts Directory



This directory contains deployment scripts for the Azure Cosmos DB MCP Toolkit with AI Foundry integration.



## PrerequisitesThis directory contains deployment scripts for the Azure Cosmos DB MCP Toolkit with AI Foundry integration.This directory contains deployment and testing scripts for the Azure Cosmos DB MCP Toolkit.



Before running the deployment, ensure you have:



1. **Azure CLI** installed and authenticated (`az login`)## Prerequisites# Scripts Directory

2. **Docker** installed and running

3. **.NET 9.0 SDK** installed

4. **PowerShell 7+** (or Windows PowerShell 5.1)

5. **Azure Subscription** with permissions to:Before running the deployment, ensure you have:This directory contains deployment and testing scripts for the Azure Cosmos DB MCP Toolkit.

   - Create/manage resource groups

   - Deploy Container Apps, Cosmos DB, Azure OpenAI

   - Create Entra ID applications

   - Assign roles and permissions1. **Azure CLI** installed and authenticated (`az login`)## 🚀 Deployment Scripts

6. **(Optional)** AI Foundry project for MCP integration

2. **Docker** installed and running

## Quick Start - One-Step Deployment

3. **.NET 9.0 SDK** installed### `Quick-Deploy.ps1` ⭐ **RECOMMENDED**

### Step 1: Deploy Infrastructure

4. **PowerShell 7+** (or Windows PowerShell 5.1)

First, deploy the Azure resources using Bicep:

5. **Azure Subscription** with permissions to:**Fast deployment script** for updating existing Azure resources after "Deploy to Azure" button:

```powershell

cd infrastructure   - Create/manage resource groups



# Create resource group   - Deploy Container Apps, Cosmos DB, Azure OpenAI- ✅ Works with existing Azure infrastructure 

az group create --name "cosmos-mcp-toolkit-final" --location "eastus"

   - Create Entra ID applications- ✅ Builds and deploys latest application code

# Deploy all resources

az deployment group create `   - Assign roles and permissions- ✅ Updates Container App with new revision

    --resource-group "cosmos-mcp-toolkit-final" `

    --template-file deploy-all-resources.bicep `6. **(Optional)** AI Foundry project for MCP integration- ✅ Tests deployment automatically

    --parameters deploy-all-resources.parameters.json

```- ✅ Takes 2-3 minutes



This creates:## Quick Start - One-Step Deployment

- Azure Container Apps environment

- Azure Container Registry**Usage:**

- Azure Cosmos DB account

- Azure OpenAI service### Step 1: Deploy Infrastructure```powershell

- Managed Identity

- Necessary networking and security.\Quick-Deploy.ps1 -ResourceGroup "rg-sajee-cosmos-mcp-kit" -ContainerAppName "mcp-toolkit-app" -RegistryName "mcptoolkitacr57c4u6r4dcvto"



### Step 2: Deploy MCP Server and Configure AuthenticationFirst, deploy the Azure resources using Bicep:```



Run the comprehensive deployment script:



```powershell```powershell### `Deploy-CosmosMcpServer.ps1` (Full Setup)

cd ../scripts

cd infrastructure

# Basic deployment (without AI Foundry)

./Deploy-All.ps1 -ResourceGroup "cosmos-mcp-toolkit-final"**Complete deployment script** for Windows that creates everything from scratch:



# With AI Foundry integration# Create resource group

./Deploy-All.ps1 `

    -ResourceGroup "cosmos-mcp-toolkit-final" `az group create --name "cosmos-mcp-toolkit-final" --location "eastus"- ✅ Entra ID App Registration with `Mcp.Tool.Executor` role

    -AIFoundryProjectResourceId "/subscriptions/<sub-id>/resourceGroups/<rg>/providers/Microsoft.MachineLearningServices/workspaces/<hub>/projects/<project>"

```- ✅ Azure Container Apps infrastructure  



The script automatically:# Deploy all resources- ✅ Azure Container Registry

1. Builds and pushes Docker image to ACR

2. Creates Entra app with Mcp.Tool.Executor roleaz deployment group create `- ✅ Complete authentication setup

3. Assigns Cosmos DB Data Reader permissions

4. Updates container app with authentication settings    --resource-group "cosmos-mcp-toolkit-final" `

5. (If AI Foundry provided) Assigns roles to AI Foundry managed identity

    --template-file deploy-all-resources.bicep `**Usage:**

### Step 3: Create AI Foundry Connection (If Using AI Foundry)

    --parameters deploy-all-resources.parameters.json```powershell

After deployment completes, it will display:

- MCP Server endpoint URL```.\Deploy-CosmosMcpServer.ps1 -ResourceGroup "rg-mcp-demo"

- Entra App Client ID

- Connection configuration details```



Create an MCP connection in AI Foundry:This creates:

1. Navigate to AI Foundry project → **Connections**

2. Click **"New Connection"** → **"Model Context Protocol"**- Azure Container Apps environment### `deploy-cosmos-mcp-server.sh` (Full Setup)

3. Configure:

   - **Name**: Give it a descriptive name (e.g., `mcp-cosmos-connection`)- Azure Container Registry

   - **MCP Server URL**: Use the endpoint from deployment output

   - **Authentication**: Select "Connection (Managed Identity)"- Azure Cosmos DB account**Complete deployment script** for Linux/macOS with the same functionality.

   - **Audience/Client ID**: Use the Client ID from deployment output

- Azure OpenAI service

### Step 4: Test the Integration

- Managed Identity**Usage:**

Test using the Python client:

- Necessary networking and security```bash

```powershell

cd ../client./deploy-cosmos-mcp-server.sh --resource-group "rg-mcp-demo"



# Create .env file### Step 2: Deploy MCP Server and Configure Authentication```

@"

PROJECT_CONNECTION_STRING=<your-ai-foundry-project-connection-string>

MCP_CONNECTION_NAME=mcp-cosmos-connection

MODEL_DEPLOYMENT_NAME=gpt-4.1-miniRun the comprehensive deployment script:## 🧪 Testing Scripts

"@ | Out-File -FilePath .env -Encoding utf8



# Install dependencies

pip install -r requirements.txt```powershell### `test-deployment.sh`



# Run testcd ../scripts

python agents_cosmosdb_mcp.py

```Validates your deployment by testing:



## Available Scripts# Basic deployment (without AI Foundry)- Health endpoints



### Deploy-All.ps1 (MAIN DEPLOYMENT SCRIPT)./Deploy-All.ps1 -ResourceGroup "cosmos-mcp-toolkit-final"- Authentication security (401 responses)



**Purpose**: Complete end-to-end deployment in one command- MCP protocol endpoints



**What it does**:# With AI Foundry integration

1. Validates resource group exists

2. Builds .NET application and Docker image./Deploy-All.ps1 `**Usage:**

3. Pushes image to Azure Container Registry

4. Creates Entra app with proper configuration:    -ResourceGroup "cosmos-mcp-toolkit-final" ````bash

   - Adds Mcp.Tool.Executor app role

   - Exposes API with user consent scope (no admin consent needed)    -AIFoundryProjectResourceId "/subscriptions/<sub-id>/resourceGroups/<rg>/providers/Microsoft.MachineLearningServices/workspaces/<hub>/projects/<project>"./test-deployment.sh

   - Configures for managed identity authentication

5. Retrieves container app managed identity``````

6. Assigns Cosmos DB Data Reader role to managed identity

7. Updates container app with authentication environment variables

8. (Optional) Assigns Mcp.Tool.Executor role to AI Foundry project MI

9. Displays complete configuration summaryThe script automatically:### `validate-setup.ps1`



**Parameters**:1. Builds and pushes Docker image to ACR

- `ResourceGroup` (required): Name of Azure resource group

- `Location` (optional): Azure region (default: eastus)2. Creates Entra app with Mcp.Tool.Executor rolePowerShell validation script for Windows users.

- `CosmosAccountName` (optional): Cosmos DB account name (default: cosmosmcpkit)

- `ContainerAppName` (optional): Container app name (default: mcp-toolkit-app)3. Assigns Cosmos DB Data Reader permissions

- `AIFoundryProjectResourceId` (optional): Full resource ID of AI Foundry project

4. Updates container app with authentication settings## 🔑 Authentication Utilities

**Example**:

```powershell5. (If AI Foundry provided) Assigns roles to AI Foundry managed identity

./Deploy-All.ps1 -ResourceGroup "my-rg" -AIFoundryProjectResourceId "/subscriptions/.../projects/my-project"

```### `Get-AzureToken.ps1`



### Setup-Permissions.ps1 (STANDALONE UTILITY)### Step 3: Create AI Foundry Connection (If Using AI Foundry)



**Purpose**: Create Entra app only (if you need to create additional auth apps)Gets Azure AD access tokens for testing your deployed MCP server.



**When to use**: After deployment completes, it will display:

- Need a separate Entra app for different environment

- Want to recreate auth configuration- MCP Server endpoint URL**Usage:**

- Testing different authentication scenarios

- Entra App Client ID```powershell

**What it does**:

- Creates Entra app with unique name- Connection configuration details.\Get-AzureToken.ps1

- Adds Mcp.Tool.Executor role with User+Application member types

- Exposes API scope for user consent```

- Optionally updates container app environment variables

Create an MCP connection in AI Foundry:

### Setup-AIFoundry-RoleAssignment.ps1 (STANDALONE UTILITY)

1. Navigate to AI Foundry project → Connections### `get-access-token.sh`

**Purpose**: Assign role to AI Foundry project (if not done in Deploy-All)

2. Click "New Connection" → "Model Context Protocol"

**When to use**:

- Need to grant access to additional AI Foundry projects3. Configure:Bash version of the token utility for Linux/macOS.

- Role assignment failed during Deploy-All

- Changing AI Foundry project   - **Name**: Give it a descriptive name (e.g., `mcp-cosmos-connection`)



**What it does**:   - **MCP Server URL**: Use the endpoint from deployment output**Usage:**

- Gets AI Foundry project managed identity

- Validates Entra app exists   - **Authentication**: Select "Connection (Managed Identity)"```bash

- Assigns Mcp.Tool.Executor application role

   - **Audience/Client ID**: Use the Client ID from deployment output./get-access-token.sh

## Troubleshooting

```

### Build Fails

- Ensure .NET 9.0 SDK is installed: `dotnet --version`### Step 4: Test the Integration

- Clean build: `dotnet clean` then retry

## 🛠️ Local Development

### Docker Push Fails

- Verify Docker is running: `docker ps`Test using the Python client:

- Check ACR credentials are configured

- Script uses ACR admin credentials automatically### `setup-cosmos-cert.sh` & `Setup-CosmosCert.ps1`



### Authentication Errors (401/403)```powershell

- Wait 5-10 minutes for role assignments to propagate

- Verify Entra app Client ID matches container configurationcd ../clientSets up SSL certificates for local Cosmos DB emulator development.

- Check AI Foundry connection uses correct audience



### "No databases found" or Empty Results

- Verify Cosmos DB role assignment: Check Azure Portal → Cosmos DB → Access Control (IAM)# Create .env file### `Test-ManagedIdentityAuth.ps1` & `Test-MCPWithAAD.ps1`

- Role propagation can take 5-10 minutes

- Ensure Cosmos DB account has at least one database created@"



### AI Foundry Agent Fails to Call ToolsPROJECT_CONNECTION_STRING=<your-ai-foundry-project-connection-string>Advanced testing scripts for managed identity and Azure AD authentication.

- Verify MCP connection created with correct endpoint and audience

- Check connection status in AI Foundry portalMCP_CONNECTION_NAME=mcp-cosmos-connection

- Ensure AI Foundry MI has Mcp.Tool.Executor role

MODEL_DEPLOYMENT_NAME=gpt-4.1-mini---

## Architecture

"@ | Out-File -FilePath .env -Encoding utf8

```

AI Foundry Project (Managed Identity)All scripts include comprehensive error handling and detailed output to guide you through the deployment and testing process.

    ↓ (Bearer token with audience = Entra App Client ID)# Install dependencies

Container App (MCP Server)pip install -r requirements.txt

    ↓ (Uses managed identity)

Cosmos DB Account# Run test

```python agents_cosmosdb_mcp.py

```

**Authentication Flow**:

1. AI Foundry MI requests token for Entra App audience## What Each Script Does

2. Token sent as Bearer in Authorization header to MCP server

3. MCP server validates token (tenant, audience, signature)### Deploy-All.ps1 (MAIN DEPLOYMENT SCRIPT)

4. MCP server uses its managed identity to access Cosmos DB**Purpose**: Complete end-to-end deployment in one command

5. Results returned to AI Foundry agent

**What it does**:

## Additional Resources1. Validates resource group exists

2. Builds .NET application and Docker image

- **Main README**: ../README.md3. Pushes image to Azure Container Registry

- **Authentication Setup**: ../docs/AUTHENTICATION-SETUP.md4. Creates Entra app with proper configuration:

- **Troubleshooting Guide**: ../docs/TROUBLESHOOTING.md   - Adds Mcp.Tool.Executor app role

- **Testing Guide**: ../TESTING_GUIDE.md   - Exposes API with user consent scope (no admin consent needed)

   - Configures for managed identity authentication
5. Retrieves container app managed identity
6. Assigns Cosmos DB Data Reader role to managed identity
7. Updates container app with authentication environment variables
8. (Optional) Assigns Mcp.Tool.Executor role to AI Foundry project MI
9. Displays complete configuration summary

**Parameters**:
- `ResourceGroup` (required): Name of Azure resource group
- `Location` (optional): Azure region (default: eastus)
- `CosmosAccountName` (optional): Cosmos DB account name (default: cosmosmcpkit)
- `ContainerAppName` (optional): Container app name (default: mcp-toolkit-app)
- `AIFoundryProjectResourceId` (optional): Full resource ID of AI Foundry project

**Example**:
```powershell
./Deploy-All.ps1 -ResourceGroup "my-rg" -AIFoundryProjectResourceId "/subscriptions/.../projects/my-project"
```

### Setup-Permissions.ps1 (STANDALONE UTILITY)
**Purpose**: Create Entra app only (if you need to create additional auth apps)

**When to use**: 
- Need a separate Entra app for different environment
- Want to recreate auth configuration
- Testing different authentication scenarios

**What it does**:
- Creates Entra app with unique name
- Adds Mcp.Tool.Executor role with User+Application member types
- Exposes API scope for user consent
- Optionally updates container app environment variables

### Setup-AIFoundry-RoleAssignment.ps1 (STANDALONE UTILITY)
**Purpose**: Assign role to AI Foundry project (if not done in Deploy-All)

**When to use**:
- Need to grant access to additional AI Foundry projects
- Role assignment failed during Deploy-All
- Changing AI Foundry project

**What it does**:
- Gets AI Foundry project managed identity
- Validates Entra app exists
- Assigns Mcp.Tool.Executor application role

## Troubleshooting

### Build Fails
- Ensure .NET 9.0 SDK is installed: `dotnet --version`
- Clean build: `dotnet clean` then retry

### Docker Push Fails
- Verify Docker is running: `docker ps`
- Check ACR credentials are configured
- Script uses ACR admin credentials automatically

### Authentication Errors (401/403)
- Wait 5-10 minutes for role assignments to propagate
- Verify Entra app Client ID matches container configuration
- Check AI Foundry connection uses correct audience

### "No databases found" or Empty Results
- Verify Cosmos DB role assignment: Check Azure Portal → Cosmos DB → Access Control (IAM)
- Role propagation can take 5-10 minutes
- Ensure Cosmos DB account has at least one database created

### AI Foundry Agent Fails to Call Tools
- Verify MCP connection created with correct endpoint and audience
- Check connection status in AI Foundry portal
- Ensure AI Foundry MI has Mcp.Tool.Executor role

## Architecture

```
AI Foundry Project (Managed Identity)
    ↓ (Bearer token with audience = Entra App Client ID)
Container App (MCP Server)
    ↓ (Uses managed identity)
Cosmos DB Account
```

**Authentication Flow**:
1. AI Foundry MI requests token for Entra App audience
2. Token sent as Bearer in Authorization header to MCP server
3. MCP server validates token (tenant, audience, signature)
4. MCP server uses its managed identity to access Cosmos DB
5. Results returned to AI Foundry agent

## Additional Resources

- **Main README**: ../README.md
- **Authentication Setup**: ../docs/AUTHENTICATION-SETUP.md
- **Troubleshooting Guide**: ../docs/TROUBLESHOOTING.md
- **Testing Guide**: ../TESTING_GUIDE.md
