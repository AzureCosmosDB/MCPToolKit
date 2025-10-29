# Azure Cosmos DB MCP Toolkit - Deployment Scripts# Azure Cosmos DB MCP Toolkit - Deployment Scripts# Azure Cosmos DB MCP Toolkit - Deployment Scripts# Azure Cosmos DB MCP Toolkit - Deployment Scripts# Azure Cosmos DB MCP Toolkit - Deployment Scripts# Scripts Directory



This directory contains deployment scripts for the Azure Cosmos DB MCP Toolkit with AI Foundry integration.



## Quick StartThis directory contains deployment scripts for the Azure Cosmos DB MCP Toolkit with AI Foundry integration.



### Use Deploy-All.ps1 ⭐ **RECOMMENDED**



```powershell## PrerequisitesThis directory contains deployment scripts for the Azure Cosmos DB MCP Toolkit with AI Foundry integration.

.\scripts\Deploy-All.ps1 -ResourceGroup "<your-resource-group>"

```



This script handles everything in one step:Before running the deployment, ensure you have:

- ✅ Builds the .NET application  

- ✅ Pushes Docker image to ACR  

- ✅ Creates Entra ID application  

- ✅ Configures all permissions  1. **Azure CLI** installed and authenticated (`az login`)## PrerequisitesThis directory contains deployment scripts for the Azure Cosmos DB MCP Toolkit with AI Foundry integration.

- ✅ Updates Container App  

2. **Docker** installed and running

---

3. **.NET 9.0 SDK** installed

## Available Scripts

4. **PowerShell 7+** (or Windows PowerShell 5.1)

### `Deploy-All.ps1` - Complete Deployment

5. **Azure Subscription** with permissions to:Before running the deployment, ensure you have:

**Usage:**

```powershell   - Create/manage resource groups

.\scripts\Deploy-All.ps1 -ResourceGroup "rg-myproject-mcp"

```   - Deploy Container Apps, Cosmos DB



### `Setup-Permissions.ps1` - Permissions Only   - Create Entra ID applications



**Usage:**   - Assign roles and permissions1. **Azure CLI** installed and authenticated (`az login`)## PrerequisitesThis directory contains deployment scripts for the Azure Cosmos DB MCP Toolkit with AI Foundry integration.This directory contains deployment and testing scripts for the Azure Cosmos DB MCP Toolkit.

```powershell

.\scripts\Setup-Permissions.ps1 -ResourceGroup "rg-myproject-mcp"6. **AI Foundry project** with an embedding model deployed (for vector search functionality)

```

2. **Docker** installed and running

**Optional:**

```powershell> **Note**: This toolkit is designed to work with **AI Foundry** (the modern Azure AI platform). The legacy standalone Azure OpenAI service is no longer required - AI Foundry projects include Azure OpenAI capabilities with enhanced features.

.\scripts\Setup-Permissions.ps1 -ResourceGroup "rg-myproject-mcp" -UserEmail "user@domain.com"

```3. **.NET 9.0 SDK** installed



### `Setup-AIFoundry-RoleAssignment.ps1` - AI Foundry Integration## Quick Start - One-Step Deployment



**Usage:**4. **PowerShell 7+** (or Windows PowerShell 5.1)

```powershell

.\scripts\Setup-AIFoundry-RoleAssignment.ps1 `### Step 1: Deploy Infrastructure

    -AIFoundryProjectResourceId "/subscriptions/<sub-id>/resourceGroups/<rg>/providers/Microsoft.MachineLearningServices/workspaces/<project>" `

    -EntraAppClientId "<client-id>"5. **Azure Subscription** with permissions to:Before running the deployment, ensure you have:

```

First, deploy the Azure resources using Bicep:

---

   - Create/manage resource groups

## Notes

```powershell

- **Quick-Deploy.ps1 has been removed** - Use `Deploy-All.ps1` instead

- Scripts now have 15-second timeouts to prevent hangingcd infrastructure   - Deploy Container Apps, Cosmos DB, Azure OpenAI

- AI Foundry detection is automatic with fallback to Azure OpenAI

- All scripts support `--only-show-errors` for faster execution



---# Create resource group   - Create Entra ID applications



For detailed documentation, see the main [README.md](../README.md)az group create --name "<your-resource-group-name>" --location "eastus"


   - Assign roles and permissions1. **Azure CLI** installed and authenticated (`az login`)## Prerequisites# Scripts Directory

# Deploy all resources

az deployment group create `6. **(Optional)** AI Foundry project for MCP integration

    --resource-group "<your-resource-group-name>" `

    --template-file deploy-all-resources.bicep `2. **Docker** installed and running

    --parameters deploy-all-resources.parameters.json

```## Quick Start - One-Step Deployment



**Required Parameters**:3. **.NET 9.0 SDK** installed

- `cosmosEndpoint`: Your Cosmos DB account endpoint (e.g., `https://your-cosmos.documents.azure.com:443/`)

- `aifProjectEndpoint`: Your AI Foundry project endpoint (find this in AI Foundry portal → Project Settings → Endpoints)### Step 1: Deploy Infrastructure

- `embeddingDeploymentName`: Name of your embedding model deployment in AI Foundry (e.g., `text-embedding-ada-002` or `text-embedding-3-small`)

4. **PowerShell 7+** (or Windows PowerShell 5.1)

This creates:

- Azure Container Apps environmentFirst, deploy the Azure resources using Bicep:

- Azure Container Registry

- Managed Identity5. **Azure Subscription** with permissions to:Before running the deployment, ensure you have:This directory contains deployment and testing scripts for the Azure Cosmos DB MCP Toolkit.

- Necessary networking and security

```powershell

### Step 2: Deploy MCP Server and Configure Authentication

cd infrastructure   - Create/manage resource groups

Run the comprehensive deployment script:



```powershell

cd ../scripts# Create resource group   - Deploy Container Apps, Cosmos DB, Azure OpenAI



# Basic deployment (without AI Foundry MCP connection)az group create --name "<your-resource-group-name>" --location "eastus"

./Deploy-All.ps1 -ResourceGroup "<your-resource-group-name>"

   - Create Entra ID applications

# With AI Foundry MCP connection integration

./Deploy-All.ps1 `# Deploy all resources

    -ResourceGroup "<your-resource-group-name>" `

    -AIFoundryProjectResourceId "/subscriptions/<subscription-id>/resourceGroups/<resource-group>/providers/Microsoft.MachineLearningServices/workspaces/<hub-name>/projects/<project-name>"az deployment group create `   - Assign roles and permissions1. **Azure CLI** installed and authenticated (`az login`)## 🚀 Deployment Scripts

```

    --resource-group "<your-resource-group-name>" `

The script automatically:

1. Builds and pushes Docker image to ACR    --template-file deploy-all-resources.bicep `6. **(Optional)** AI Foundry project for MCP integration

2. Creates Entra app with Mcp.Tool.Executor role

3. Assigns Cosmos DB Data Reader permissions    --parameters deploy-all-resources.parameters.json

4. Updates container app with authentication settings

5. (If AI Foundry provided) Assigns roles to AI Foundry managed identity for MCP connection```2. **Docker** installed and running



### Step 3: Assign AI Foundry Project Permissions



Your container app needs permissions to call the AI Foundry project for embeddings:This creates:## Quick Start - One-Step Deployment



```powershell- Azure Container Apps environment

# Get the container app's managed identity principal ID

$containerMI = az containerapp show --name "<your-container-app-name>" --resource-group "<your-resource-group-name>" --query "identity.principalId" -o tsv- Azure Container Registry3. **.NET 9.0 SDK** installed### `Quick-Deploy.ps1` ⭐ **RECOMMENDED**



# Assign Cognitive Services OpenAI User role to the managed identity- Azure Cosmos DB account

az role assignment create `

    --assignee $containerMI `- Azure OpenAI service### Step 1: Deploy Infrastructure

    --role "Cognitive Services OpenAI User" `

    --scope "/subscriptions/<subscription-id>/resourceGroups/<ai-foundry-resource-group>/providers/Microsoft.MachineLearningServices/workspaces/<hub-name>/projects/<project-name>"- Managed Identity

```

- Necessary networking and security4. **PowerShell 7+** (or Windows PowerShell 5.1)

> **Important**: This step is required for vector search to work. The container app uses its managed identity to call AI Foundry for generating embeddings.



### Step 4: Create AI Foundry MCP Connection (If Using AI Foundry Agents)

### Step 2: Deploy MCP Server and Configure AuthenticationFirst, deploy the Azure resources using Bicep:

After deployment completes, it will display:

- MCP Server endpoint URL

- Entra App Client ID

- Connection configuration detailsRun the comprehensive deployment script:5. **Azure Subscription** with permissions to:**Fast deployment script** for updating existing Azure resources after "Deploy to Azure" button:



Create an MCP connection in AI Foundry:

1. Navigate to AI Foundry project → **Connections**

2. Click **"New Connection"** → **"Model Context Protocol"**```powershell```powershell

3. Configure:

   - **Name**: Give it a descriptive name (e.g., `mcp-cosmos-connection`)cd ../scripts

   - **MCP Server URL**: Use the endpoint from deployment output

   - **Authentication**: Select "Connection (Managed Identity)"cd infrastructure   - Create/manage resource groups

   - **Audience/Client ID**: Use the Client ID from deployment output

# Basic deployment (without AI Foundry)

### Step 5: Test the Integration

./Deploy-All.ps1 -ResourceGroup "<your-resource-group-name>"

Test using the Python client:



```powershell

cd ../client# With AI Foundry integration# Create resource group   - Deploy Container Apps, Cosmos DB, Azure OpenAI- ✅ Works with existing Azure infrastructure 



# Create .env file./Deploy-All.ps1 `

@"

PROJECT_CONNECTION_STRING=<your-ai-foundry-project-connection-string>    -ResourceGroup "<your-resource-group-name>" `az group create --name "cosmos-mcp-toolkit-final" --location "eastus"

MCP_CONNECTION_NAME=<your-connection-name>

MODEL_DEPLOYMENT_NAME=<your-model-deployment-name>    -AIFoundryProjectResourceId "/subscriptions/<subscription-id>/resourceGroups/<resource-group>/providers/Microsoft.MachineLearningServices/workspaces/<hub-name>/projects/<project-name>"

"@ | Out-File -FilePath .env -Encoding utf8

```   - Create Entra ID applications- ✅ Builds and deploys latest application code

# Install dependencies

pip install -r requirements.txt



# Run testThe script automatically:# Deploy all resources

python agents_cosmosdb_mcp.py

```1. Builds and pushes Docker image to ACR



## Available Scripts2. Creates Entra app with Mcp.Tool.Executor roleaz deployment group create `   - Assign roles and permissions- ✅ Updates Container App with new revision



### Deploy-All.ps1 (MAIN DEPLOYMENT SCRIPT)3. Assigns Cosmos DB Data Reader permissions



**Purpose**: Complete end-to-end deployment in one command4. Updates container app with authentication settings    --resource-group "cosmos-mcp-toolkit-final" `



**What it does**:5. (If AI Foundry provided) Assigns roles to AI Foundry managed identity

1. Validates resource group exists

2. Builds .NET application and Docker image    --template-file deploy-all-resources.bicep `6. **(Optional)** AI Foundry project for MCP integration- ✅ Tests deployment automatically

3. Pushes image to Azure Container Registry

4. Creates Entra app with proper configuration:### Step 3: Create AI Foundry Connection (If Using AI Foundry)

   - Adds Mcp.Tool.Executor app role

   - Exposes API with user consent scope (no admin consent needed)    --parameters deploy-all-resources.parameters.json

   - Configures for managed identity authentication

5. Retrieves container app managed identityAfter deployment completes, it will display:

6. Assigns Cosmos DB Data Reader role to managed identity

7. Updates container app with authentication environment variables- MCP Server endpoint URL```- ✅ Takes 2-3 minutes

8. (Optional) Assigns Mcp.Tool.Executor role to AI Foundry project MI

9. Displays complete configuration summary- Entra App Client ID



**Parameters**:- Connection configuration details

- `ResourceGroup` (required): Name of Azure resource group

- `Location` (optional): Azure region (default: eastus)

- `CosmosAccountName` (optional): Cosmos DB account name (default: auto-detected from resource group)

- `ContainerAppName` (optional): Container app name (default: auto-detected from resource group)Create an MCP connection in AI Foundry:This creates:## Quick Start - One-Step Deployment

- `AIFoundryProjectResourceId` (optional): Full resource ID of AI Foundry project

1. Navigate to AI Foundry project → **Connections**

**Example**:

```powershell2. Click **"New Connection"** → **"Model Context Protocol"**- Azure Container Apps environment

./Deploy-All.ps1 `

    -ResourceGroup "<your-resource-group-name>" `3. Configure:

    -AIFoundryProjectResourceId "/subscriptions/<sub-id>/resourceGroups/<rg>/providers/Microsoft.MachineLearningServices/workspaces/<hub>/projects/<project>"

```   - **Name**: Give it a descriptive name (e.g., `mcp-cosmos-connection`)- Azure Container Registry**Usage:**



### Setup-Permissions.ps1 (STANDALONE UTILITY)   - **MCP Server URL**: Use the endpoint from deployment output



**Purpose**: Create Entra app only (if you need to create additional auth apps)   - **Authentication**: Select "Connection (Managed Identity)"- Azure Cosmos DB account



**When to use**:    - **Audience/Client ID**: Use the Client ID from deployment output

- Need a separate Entra app for different environment

- Want to recreate auth configuration- Azure OpenAI service### Step 1: Deploy Infrastructure```powershell

- Testing different authentication scenarios

### Step 4: Test the Integration

**What it does**:

- Creates Entra app with unique name- Managed Identity

- Adds Mcp.Tool.Executor role with User+Application member types

- Exposes API scope for user consentTest using the Python client:

- Optionally updates container app environment variables

- Necessary networking and security.\Quick-Deploy.ps1 -ResourceGroup "rg-sajee-cosmos-mcp-kit" -ContainerAppName "mcp-toolkit-app" -RegistryName "mcptoolkitacr57c4u6r4dcvto"

**Example**:

```powershell```powershell

./Setup-Permissions.ps1 -ResourceGroup "<your-resource-group-name>"

```cd ../client



### Setup-AIFoundry-RoleAssignment.ps1 (STANDALONE UTILITY)



**Purpose**: Assign role to AI Foundry project (if not done in Deploy-All)# Create .env file### Step 2: Deploy MCP Server and Configure AuthenticationFirst, deploy the Azure resources using Bicep:```



**When to use**:@"

- Need to grant access to additional AI Foundry projects

- Role assignment failed during Deploy-AllPROJECT_CONNECTION_STRING=<your-ai-foundry-project-connection-string>

- Changing AI Foundry project

MCP_CONNECTION_NAME=<your-connection-name>

**What it does**:

- Gets AI Foundry project managed identityMODEL_DEPLOYMENT_NAME=<your-model-deployment-name>Run the comprehensive deployment script:

- Validates Entra app exists

- Assigns Mcp.Tool.Executor application role"@ | Out-File -FilePath .env -Encoding utf8



**Example**:

```powershell

./Setup-AIFoundry-RoleAssignment.ps1 `# Install dependencies

    -ResourceGroup "<your-resource-group-name>" `

    -AIFoundryProjectResourceId "/subscriptions/<sub-id>/resourceGroups/<rg>/providers/Microsoft.MachineLearningServices/workspaces/<hub>/projects/<project>"pip install -r requirements.txt```powershell```powershell### `Deploy-CosmosMcpServer.ps1` (Full Setup)

```



## Troubleshooting

# Run testcd ../scripts

### Build Fails

- Ensure .NET 9.0 SDK is installed: `dotnet --version`python agents_cosmosdb_mcp.py

- Clean build: `dotnet clean` then retry

```cd infrastructure

### Docker Push Fails

- Verify Docker is running: `docker ps`

- Check ACR credentials are configured

- Script uses ACR admin credentials automatically## Available Scripts# Basic deployment (without AI Foundry)



### Authentication Errors (401/403)

- Wait 5-10 minutes for role assignments to propagate

- Verify Entra app Client ID matches container configuration### Deploy-All.ps1 (MAIN DEPLOYMENT SCRIPT)./Deploy-All.ps1 -ResourceGroup "cosmos-mcp-toolkit-final"**Complete deployment script** for Windows that creates everything from scratch:

- Check AI Foundry connection uses correct audience



### "No databases found" or Empty Results

- Verify Cosmos DB role assignment: Check Azure Portal → Cosmos DB → Access Control (IAM)**Purpose**: Complete end-to-end deployment in one command

- Role propagation can take 5-10 minutes

- Ensure Cosmos DB account has at least one database created



### Vector Search Fails**What it does**:# With AI Foundry integration# Create resource group

- Verify AI Foundry project endpoint is correct

- Ensure container app MI has "Cognitive Services OpenAI User" role on the AI Foundry project1. Validates resource group exists

- Check embedding deployment name matches your AI Foundry deployment

- AI Foundry projects provide Azure OpenAI-compatible endpoints2. Builds .NET application and Docker image./Deploy-All.ps1 `



### AI Foundry Agent Fails to Call Tools3. Pushes image to Azure Container Registry

- Verify MCP connection created with correct endpoint and audience

- Check connection status in AI Foundry portal4. Creates Entra app with proper configuration:    -ResourceGroup "cosmos-mcp-toolkit-final" `az group create --name "cosmos-mcp-toolkit-final" --location "eastus"- ✅ Entra ID App Registration with `Mcp.Tool.Executor` role

- Ensure AI Foundry MI has Mcp.Tool.Executor role

   - Adds Mcp.Tool.Executor app role

## Architecture

   - Exposes API with user consent scope (no admin consent needed)    -AIFoundryProjectResourceId "/subscriptions/<sub-id>/resourceGroups/<rg>/providers/Microsoft.MachineLearningServices/workspaces/<hub>/projects/<project>"

```

AI Foundry Project (Managed Identity)   - Configures for managed identity authentication

    ↓ (Bearer token with audience = Entra App Client ID)

Container App (MCP Server)5. Retrieves container app managed identity```- ✅ Azure Container Apps infrastructure  

    ↓ (Uses managed identity for embeddings)

AI Foundry Project (Azure OpenAI endpoint)6. Assigns Cosmos DB Data Reader role to managed identity

    ↓ (Uses managed identity for data access)

Cosmos DB Account7. Updates container app with authentication environment variables

```

8. (Optional) Assigns Mcp.Tool.Executor role to AI Foundry project MI

**Authentication Flow**:

1. AI Foundry MI requests token for Entra App audience (for MCP connection)9. Displays complete configuration summaryThe script automatically:# Deploy all resources- ✅ Azure Container Registry

2. Token sent as Bearer in Authorization header to MCP server

3. MCP server validates token (tenant, audience, signature)

4. MCP server uses its managed identity to:

   - Access Cosmos DB (Cosmos DB Data Reader role)**Parameters**:1. Builds and pushes Docker image to ACR

   - Call AI Foundry for embeddings (Cognitive Services OpenAI User role)

5. Results returned to AI Foundry agent- `ResourceGroup` (required): Name of Azure resource group



## AI Foundry vs Legacy Azure OpenAI- `Location` (optional): Azure region (default: eastus)2. Creates Entra app with Mcp.Tool.Executor roleaz deployment group create `- ✅ Complete authentication setup



This toolkit uses **AI Foundry** as the modern approach:- `CosmosAccountName` (optional): Cosmos DB account name (default: auto-detected from resource group)



| Feature | AI Foundry (Current) | Legacy Azure OpenAI |- `ContainerAppName` (optional): Container app name (default: auto-detected from resource group)3. Assigns Cosmos DB Data Reader permissions

|---------|---------------------|---------------------|

| Platform | Integrated AI platform with projects | Standalone OpenAI resource |- `AIFoundryProjectResourceId` (optional): Full resource ID of AI Foundry project

| Endpoint | Project-based endpoint | Resource-based endpoint |

| Management | Unified in AI Foundry portal | Separate Azure portal |4. Updates container app with authentication settings    --resource-group "cosmos-mcp-toolkit-final" `

| Features | Enhanced with RAG, agents, evaluations | Basic OpenAI APIs only |

| Recommended | ✅ Yes | ❌ Legacy |**Example**:



Your AI Foundry project endpoint can be found in: **AI Foundry Portal → Project Settings → Endpoints**```powershell5. (If AI Foundry provided) Assigns roles to AI Foundry managed identity



## Additional Resources./Deploy-All.ps1 `



- **Main README**: ../README.md    -ResourceGroup "<your-resource-group-name>" `    --template-file deploy-all-resources.bicep `**Usage:**

- **Authentication Setup**: ../docs/AUTHENTICATION-SETUP.md

- **Troubleshooting Guide**: ../docs/TROUBLESHOOTING.md    -AIFoundryProjectResourceId "/subscriptions/<sub-id>/resourceGroups/<rg>/providers/Microsoft.MachineLearningServices/workspaces/<hub>/projects/<project>"

- **Testing Guide**: ../TESTING_GUIDE.md

- **AI Foundry Documentation**: https://learn.microsoft.com/azure/ai-studio/```### Step 3: Create AI Foundry Connection (If Using AI Foundry)




### Setup-Permissions.ps1 (STANDALONE UTILITY)    --parameters deploy-all-resources.parameters.json```powershell



**Purpose**: Create Entra app only (if you need to create additional auth apps)After deployment completes, it will display:



**When to use**: - MCP Server endpoint URL```.\Deploy-CosmosMcpServer.ps1 -ResourceGroup "rg-mcp-demo"

- Need a separate Entra app for different environment

- Want to recreate auth configuration- Entra App Client ID

- Testing different authentication scenarios

- Connection configuration details```

**What it does**:

- Creates Entra app with unique name

- Adds Mcp.Tool.Executor role with User+Application member types

- Exposes API scope for user consentCreate an MCP connection in AI Foundry:This creates:

- Optionally updates container app environment variables

1. Navigate to AI Foundry project → **Connections**

**Example**:

```powershell2. Click **"New Connection"** → **"Model Context Protocol"**- Azure Container Apps environment### `deploy-cosmos-mcp-server.sh` (Full Setup)

./Setup-Permissions.ps1 -ResourceGroup "<your-resource-group-name>"

```3. Configure:



### Setup-AIFoundry-RoleAssignment.ps1 (STANDALONE UTILITY)   - **Name**: Give it a descriptive name (e.g., `mcp-cosmos-connection`)- Azure Container Registry



**Purpose**: Assign role to AI Foundry project (if not done in Deploy-All)   - **MCP Server URL**: Use the endpoint from deployment output



**When to use**:   - **Authentication**: Select "Connection (Managed Identity)"- Azure Cosmos DB account**Complete deployment script** for Linux/macOS with the same functionality.

- Need to grant access to additional AI Foundry projects

- Role assignment failed during Deploy-All   - **Audience/Client ID**: Use the Client ID from deployment output

- Changing AI Foundry project

- Azure OpenAI service

**What it does**:

- Gets AI Foundry project managed identity### Step 4: Test the Integration

- Validates Entra app exists

- Assigns Mcp.Tool.Executor application role- Managed Identity**Usage:**



**Example**:Test using the Python client:

```powershell

./Setup-AIFoundry-RoleAssignment.ps1 `- Necessary networking and security```bash

    -ResourceGroup "<your-resource-group-name>" `

    -AIFoundryProjectResourceId "/subscriptions/<sub-id>/resourceGroups/<rg>/providers/Microsoft.MachineLearningServices/workspaces/<hub>/projects/<project>"```powershell

```

cd ../client./deploy-cosmos-mcp-server.sh --resource-group "rg-mcp-demo"

## Troubleshooting



### Build Fails

- Ensure .NET 9.0 SDK is installed: `dotnet --version`# Create .env file### Step 2: Deploy MCP Server and Configure Authentication```

- Clean build: `dotnet clean` then retry

@"

### Docker Push Fails

- Verify Docker is running: `docker ps`PROJECT_CONNECTION_STRING=<your-ai-foundry-project-connection-string>

- Check ACR credentials are configured

- Script uses ACR admin credentials automaticallyMCP_CONNECTION_NAME=mcp-cosmos-connection



### Authentication Errors (401/403)MODEL_DEPLOYMENT_NAME=gpt-4.1-miniRun the comprehensive deployment script:## 🧪 Testing Scripts

- Wait 5-10 minutes for role assignments to propagate

- Verify Entra app Client ID matches container configuration"@ | Out-File -FilePath .env -Encoding utf8

- Check AI Foundry connection uses correct audience



### "No databases found" or Empty Results

- Verify Cosmos DB role assignment: Check Azure Portal → Cosmos DB → Access Control (IAM)# Install dependencies

- Role propagation can take 5-10 minutes

- Ensure Cosmos DB account has at least one database createdpip install -r requirements.txt```powershell### `test-deployment.sh`



### AI Foundry Agent Fails to Call Tools

- Verify MCP connection created with correct endpoint and audience

- Check connection status in AI Foundry portal# Run testcd ../scripts

- Ensure AI Foundry MI has Mcp.Tool.Executor role

python agents_cosmosdb_mcp.py

## Architecture

```Validates your deployment by testing:

```

AI Foundry Project (Managed Identity)

    ↓ (Bearer token with audience = Entra App Client ID)

Container App (MCP Server)## Available Scripts# Basic deployment (without AI Foundry)- Health endpoints

    ↓ (Uses managed identity)

Cosmos DB Account

```

### Deploy-All.ps1 (MAIN DEPLOYMENT SCRIPT)./Deploy-All.ps1 -ResourceGroup "cosmos-mcp-toolkit-final"- Authentication security (401 responses)

**Authentication Flow**:

1. AI Foundry MI requests token for Entra App audience

2. Token sent as Bearer in Authorization header to MCP server

3. MCP server validates token (tenant, audience, signature)**Purpose**: Complete end-to-end deployment in one command- MCP protocol endpoints

4. MCP server uses its managed identity to access Cosmos DB

5. Results returned to AI Foundry agent



## Additional Resources**What it does**:# With AI Foundry integration



- **Main README**: ../README.md1. Validates resource group exists

- **Authentication Setup**: ../docs/AUTHENTICATION-SETUP.md

- **Troubleshooting Guide**: ../docs/TROUBLESHOOTING.md2. Builds .NET application and Docker image./Deploy-All.ps1 `**Usage:**

- **Testing Guide**: ../TESTING_GUIDE.md

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
