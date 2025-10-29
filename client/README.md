# Azure Cosmos DB MCP Client

This client demonstrates how to use Azure AI Foundry agents with the Cosmos DB MCP Toolkit.

## Setup

1. **Create a `.env` file** from the example:
   ```bash
   cp .env.example .env
   ```

2. **Update the `.env` file** with your values:
   ```bash
   PROJECT_ENDPOINT=https://cosmos-mcp-toolkit-test.services.ai.azure.com/api/projects/cosmos-mcp-toolkit-test-project
   MODEL_DEPLOYMENT_NAME=gpt-4o
   CONNECTION_NAME=mcp-toolkit-connection
   MCP_SERVER_URL=https://mcp-toolkit-app.wittywave-32c6208c.eastus.azurecontainerapps.io/mcp
   MCP_SERVER_LABEL=cosmosdb
   ```

3. **Install dependencies**:
   ```bash
   pip install -r requirements.txt
   ```

4. **Make sure you have the MCP connection configured in AI Foundry**:
   - Connection Name: `mcp-toolkit-connection`
   - Target URL: `https://mcp-toolkit-app.wittywave-32c6208c.eastus.azurecontainerapps.io/mcp`
   - Audience: `21d81067-43f7-40e6-8c90-b21fcfb75af2`
   - Authentication: Project Managed Identity

## Run

```bash
python agents_cosmosdb_mcp.py
```

## What it does

The script creates an AI agent that can:
- List databases in your Cosmos DB account
- List containers in a database
- Get recent documents
- Search for documents
- Perform vector search
- Get container schemas

## Sample Questions

Edit the `input_text` array in the script to test different questions:

```python
input_text = [
    "Can you list all the databases in my Cosmos DB account?",
    "Show me the containers in the first database",
    "What does the schema look like for the first container?",
    "Get me the 5 most recent documents from the first container",
    "Search for documents containing 'test' in the name property",
]
```

Change `content=input_text[0]` to test different questions (e.g., `input_text[1]`, `input_text[2]`, etc.).

## Troubleshooting

If you see "network error":
1. Check container app logs: `az containerapp logs show --name mcp-toolkit-app --resource-group cosmos-mcp-toolkit-final --tail 50`
2. Verify the MCP connection in AI Foundry has the correct audience
3. Make sure the agent has access to the connection

If authentication fails:
1. Verify the Entra App Client ID: `21d81067-43f7-40e6-8c90-b21fcfb75af2`
2. Check role assignments are in place
3. Ensure the container app has the correct environment variables
