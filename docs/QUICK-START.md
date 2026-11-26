# ⚡ Quick Start (5 Minutes)

Get the MCP Toolkit running in Azure in just 5 minutes with zero configuration needed.

## Prerequisites (2 min)

You only need:

- ✅ **Azure subscription** ([free account](https://azure.microsoft.com/free/))
- ✅ **Azure Cosmos DB account** ([create here](https://learn.microsoft.com/azure/cosmos-db/nosql/quickstart-portal))
- ✅ **Embedding service** (pick ONE):
  - 🔷 Azure AI Services ([create](https://learn.microsoft.com/azure/ai-services/what-are-ai-services))
  - 🔷 Azure AI Foundry ([create](https://learn.microsoft.com/azure/ai/foundry/how-to/create-projects))
  - 🔷 OpenAI API ([get key](https://platform.openai.com/api-keys))

**You don't need to install anything locally** — everything runs in Azure.

---

## Step 1: Deploy to Azure (2 min)

Click this button and wait for deployment to complete:

[![Deploy to Azure](https://aka.ms/deploytoazurebutton)](https://portal.azure.com/#create/Microsoft.Template/uri/https%3A%2F%2Fraw.githubusercontent.com%2FAzureCosmosDB%2FMCPToolKit%2Fmain%2Finfrastructure%2Fdeploy-all-resources.json)

**What gets created automatically:**
- ✅ Azure Container Registry (stores the MCP server image)
- ✅ Azure Container Apps (runs the MCP server)
- ✅ Managed Identity (secure authentication)
- ✅ All networking & security configs

**After deployment finishes**, note your **resource group name** — you'll need it next.

---

## Step 2: Deploy the MCP Server (2 min)

**Clone the repository and run the deployment script:**

```powershell
# Clone the repo
git clone https://github.com/AzureCosmosDB/MCPToolKit.git
cd MCPToolKit

# Run deployment (replace YOUR-RESOURCE-GROUP with your resource group name)
.\scripts\Deploy-Cosmos-MCP-Toolkit.ps1 -ResourceGroup "YOUR-RESOURCE-GROUP"
```

**What this script does:**
- Builds the MCP server Docker image
- Deploys it to your Container Apps
- Creates Entra ID app registration for authentication
- Outputs all connection details to `deployment-info.json`

**The script takes about 2-3 minutes to complete.**

---

## Step 3: Test Your Deployment (1 min)

Once the script finishes, you have two ways to test:

### Option A: Web UI (Easy)

```powershell
# Get your Container App URL
$info = Get-Content deployment-info.json | ConvertFrom-Json
Write-Host "Open this in your browser: $($info.containerAppUrl)"
```

Then:
1. Open the URL in your browser
2. You'll see the MCP Toolkit test interface
3. Click **List Databases** to verify connection works
4. Try searching or fetching documents

### Option B: Health Check (Quick)

```powershell
# Get your Container App URL
$url = (Get-Content deployment-info.json | ConvertFrom-Json).containerAppUrl
Invoke-RestMethod "$url/health" | ConvertTo-Json
```

You should see:
```json
{
  "status": "healthy",
  "version": "1.1.2"
}
```

---

## ✅ You're Done!

Your MCP server is now **live and ready to use**. Here's what's next:

### 🤖 Use with AI Agents

**Microsoft Foundry Agents:**
- See [Microsoft Foundry Setup](../README.md#microsoft-foundry-integration) in the full README
- Create an agent and add this MCP server as a tool
- Ask it: *"Show me my latest documents"* or *"Search for products named Azure"*

**Claude (via MCP):**
- Add the MCP server to your Claude client config
- [See VS Code setup instructions](../README.md#vs-code-configuration)

**Python Scripts:**
- Use the [Python client example](../client/README.md)
- Query Cosmos DB from any Python application

### 📊 Test More Features

The web UI lets you test all MCP tools:

| Feature | Test It |
|---------|---------|
| **List Databases** | Click dropdown → select database |
| **Schema Discovery** | Select container → click "Get Schema" |
| **Text Search** | Type search term → click "Text Search" |
| **Vector Search** | Enter query → click "Vector Search" |
| **Hybrid Search** | Combines both search types |
| **BM25 Search** | Ranks documents by keyword relevance, without embeddings |
| **Recent Documents** | Gets N most recent documents |

### 🔧 Troubleshooting

**"Unauthorized" error in web UI?**

You need to assign yourself the required role:

```powershell
.\scripts\Assign-Role-To-Current-User.ps1
```

Then refresh your browser.

**Container didn't deploy?**

Check logs:

```powershell
az containerapp logs show \
  --name <YOUR-CONTAINER-APP-NAME> \
  --resource-group YOUR-RESOURCE-GROUP \
  --tail 50
```

**"Connection failed" in web UI?**

Verify your Cosmos DB connection string is correct in the `deployment-info.json`.

### 📚 Learn More

- [Full Setup Guide](../README.md#quick-start) — All options & advanced configuration
- [Architecture Diagrams](ARCHITECTURE-DIAGRAMS.md) — How it all works
- [Troubleshooting Guide](TROUBLESHOOTING-DEPLOYMENT.md) — Common issues & solutions
- [Web Testing Guide](WEB-TESTING-GUIDE.md) — Detailed UI walkthrough

---

**Done in 5 minutes!** 🎉  
Your MCP server is secure, scalable, and ready for production.
