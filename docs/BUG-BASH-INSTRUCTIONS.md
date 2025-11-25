# Bug Bash - Azure Cosmos DB MCP Toolkit Integration Testing

## Overview
We're launching an **offline bug bash** for the Azure Cosmos DB MCP Toolkit - a Model Context Protocol (MCP) server that enables AI agents to interact with Azure Cosmos DB through natural language queries. Test at your own pace and report findings when complete.

## What We're Testing
A secure MCP server that provides:
- Azure Cosmos DB operations (CRUD, queries, schema discovery)
- Vector search with Azure OpenAI embeddings
- Enterprise security with Microsoft Entra ID authentication
- Azure Container Apps deployment

---

## Testing Scenarios

### Scenario 1: Basic Deployment & Health Check (Required)
**Objective:** Verify infrastructure deployment and service health

**Steps:**
1. Clone the repository:
   ```bash
   git clone https://github.com/AzureCosmosDB/MCPToolKit.git
   cd MCPToolKit
   ```

2. Deploy using the PowerShell script:
   ```powershell
   .\scripts\Deploy-Cosmos-MCP-Toolkit.ps1 -ResourceGroup "YOUR-RESOURCE-GROUP"
   ```

3. Verify deployment:
   - Check that `deployment-info.json` is created
   - Open the Container App URL in browser
   - Verify health endpoint returns HTTP 200

**Expected Result:** All Azure resources deployed successfully, health endpoint accessible

---

### Scenario 2: Web UI Testing (Required)
**Objective:** Test all 7 MCP tools via the built-in test UI

**Steps:**
1. Open the Container App URL: `https://YOUR-CONTAINER-APP.azurecontainerapps.io`
2. Sign in with Microsoft Entra ID
3. Test each tool:

**a) list_databases**
- Click "List Databases"
- Verify you see your Cosmos DB databases

**b) list_collections**
- Select a database
- Verify all containers are listed

**c) get_recent_documents**
- Select database and container
- Set n=5
- Verify recent documents are returned with actual field values (not empty arrays)

**d) find_document_by_id**
- Enter a valid document ID
- Verify document is returned correctly

**e) text_search**
- Enter a property name (e.g., "Make", "Name")
- Enter search text
- Set n=10
- Verify matching documents are returned

**f) get_approximate_schema**
- Select database and container
- Verify schema with property types is returned

**g) vector_search** *(requires Azure OpenAI)*
- Enter search text (e.g., "luxury sedan")
- Specify vector property (e.g., "embedding")
- Set topN=5
- Verify semantically similar documents are returned with similarity scores

**Expected Result:** All tools return data correctly formatted as JSON, no errors

---

### Scenario 3: Authentication & Security (Required)
**Objective:** Verify security controls work properly

**Steps:**
1. Try accessing the MCP endpoint without authentication:
   ```bash
   curl https://YOUR-CONTAINER-APP.azurecontainerapps.io/mcp
   ```
   **Expected:** HTTP 401 Unauthorized

2. Sign out from the Web UI and try accessing tools
   **Expected:** Redirect to login page

3. Verify Managed Identity permissions:
   - Check Azure Portal → Container App → Identity
   - Verify "Cosmos DB Data Reader" role assigned
   - If using vector search, verify "Cognitive Services OpenAI User" role

**Expected Result:** Authentication properly enforced, RBAC configured correctly

---

### Scenario 4: Vector Search with Demo Data (Optional - requires Azure OpenAI)
**Objective:** Test semantic search capabilities

**Prerequisites:**
- Azure OpenAI resource with `text-embedding-ada-002` deployment
- `OPENAI_ENDPOINT` environment variable set in Container App

**Steps:**
1. Create test data with embeddings (or use existing demo vehicles data)
2. Test vector search queries:
   - "luxury sedan" → Should return high-end vehicles
   - "affordable reliable truck" → Should return economical trucks
   - "fuel efficient compact car" → Should return small, efficient vehicles

**Expected Result:** Semantically relevant results ranked by similarity score

---

### Scenario 5: Microsoft Foundry Integration (Optional)
**Objective:** Test MCP server integration with Microsoft Foundry agents

> ⚠️ **IMPORTANT:** Microsoft Foundry integration is OPTIONAL and requires subscription whitelisting. Please **reach out to me with your subscription ID** if you want to test this scenario.

**Test URL:** 
https://eastus2euap.ai.azure.com/nextgen/

**Steps:**
1. Run the AI Foundry connection setup:
   ```powershell
   .\scripts\Setup-AIFoundry-Connection.ps1 -AIFoundryProjectName "YOUR-PROJECT" -ResourceGroup "YOUR-RG"
   ```

2. In AI Foundry UI:
   - Go to **Build** → **Create agent**
   - Add **Azure Cosmos DB** tool from catalog
   - Configure authentication with your Entra App Client ID (from `deployment-info.json`)
   - Add agent instructions with database/container parameters

3. Test natural language queries in the playground:
   - "List all databases in my Cosmos DB account"
   - "Show me the latest 10 documents from the [container-name] container"
   - "What's the schema of the [container-name] container?"
   - "Search for documents where name contains Azure"
   - "Find similar items to 'luxury sedan'" (if vector search configured)

**Expected Result:** Agent successfully calls MCP tools and returns accurate responses

---

## What to Report

Please log issues for:
- ❌ Deployment failures or errors
- ❌ Authentication/authorization issues
- ❌ Incorrect or missing data in tool responses
- ❌ Empty arrays or null values when data should exist
- ❌ UI/UX issues in the test interface
- ❌ Performance problems (slow queries, timeouts)
- ❌ Documentation gaps or unclear instructions
- ❌ Vector search not returning relevant results
- ❌ Microsoft Foundry integration failures

---

## Logging Your Results

**Please include:**
1. **Scenario number** and description
2. **Environment details**: Azure region, resource group name
3. **Steps to reproduce** the issue
4. **Expected vs actual behavior**
5. **Screenshots/logs** if applicable
6. **deployment-info.json** contents (if relevant)

---

## Resources

- **Repository:** https://github.com/AzureCosmosDB/MCPToolKit
- **Documentation:** See `/docs` folder in the repo
- **Architecture Diagrams:** `/docs/ARCHITECTURE-DIAGRAMS.md`
- **Local Development Guide:** `/LOCAL_DEVELOPMENT.md`

---

**Thank you for helping us ensure a high-quality release!** 🚀

**Remember:** Microsoft Foundry testing is optional - reach out if you want your subscription whitelisted!
