# Azure Container Apps Testing Guide for MCP Toolkit

## 🚀 Complete Testing Scenarios

This guide provides step-by-step instructions for testing your containerized MCP Toolkit in various environments.

## Prerequisites Checklist

- [ ] Azure CLI installed and logged in (`az login`)
- [ ] Docker Desktop installed and running
- [ ] Azure Cosmos DB account (for production testing)
- [ ] Azure OpenAI service (for vector search testing)
- [ ] VS Code with GitHub Copilot extension

## Testing Scenario 1: Local Container Test (Recommended First Step)

### Step 1: Start Docker Desktop
1. Open Docker Desktop application
2. Wait for it to fully start (green status in system tray)

### Step 2: Test Container Build
```powershell
# Build the container image
docker build -t mcp-toolkit-test .

# Verify the image was created
docker images | findstr mcp-toolkit-test
```

### Step 3: Run Local Test with Cosmos DB Emulator
```powershell
# Start the local development environment
docker-compose up -d

# Check container status
docker-compose ps

# View logs
docker-compose logs mcp-toolkit
docker-compose logs cosmos-emulator

# Test health endpoint
curl http://localhost:8080/health
```

### Step 4: Test Basic Functionality (Local)
```powershell
# Test with minimal MCP calls (without vector search)
Invoke-RestMethod -Uri "http://localhost:8080/health" -Method Get

# Create a simple test document in Cosmos emulator
# Navigate to https://localhost:8081/_explorer/index.html
# Create a database called "testdb" and container called "testcontainer"
```

### Step 5: VS Code Integration Test (Local)
Create `.vscode/mcp.json`:
```json
{
  "servers": {
    "azure-cosmos-db-mcp-local": {
      "type": "http",
      "url": "http://localhost:8080"
    }
  }
}
```

Test in GitHub Copilot Chat:
- "List all databases in my local Cosmos DB"
- "Show containers in testdb database"

## Testing Scenario 2: Azure Container Apps Deployment

### Step 1: Prepare Azure Resources

You need these Azure resources:
```powershell
# Example resource creation (replace with your values)
$resourceGroup = "rg-mcp-test"
$location = "East US"
$cosmosAccount = "cosmos-mcp-test-$(Get-Random)"
$openAIAccount = "openai-mcp-test-$(Get-Random)"

# Create resource group
az group create --name $resourceGroup --location $location

# Create Cosmos DB account
az cosmosdb create --name $cosmosAccount --resource-group $resourceGroup --locations regionName=$location

# Create Azure OpenAI service (if not exists)
az cognitiveservices account create \
  --name $openAIAccount \
  --resource-group $resourceGroup \
  --location $location \
  --kind OpenAI \
  --sku S0
```

### Step 2: Deploy to Azure Container Apps
```powershell
# Get resource endpoints
$cosmosEndpoint = az cosmosdb show --name $cosmosAccount --resource-group $resourceGroup --query "documentEndpoint" -o tsv
$openAIEndpoint = az cognitiveservices account show --name $openAIAccount --resource-group $resourceGroup --query "properties.endpoint" -o tsv

# Run deployment
.\scripts\deploy.ps1 `
  -ResourceGroupName $resourceGroup `
  -Location $location `
  -CosmosEndpoint $cosmosEndpoint `
  -OpenAIEndpoint $openAIEndpoint `
  -OpenAIEmbeddingDeployment "text-embedding-ada-002"
```

### Step 3: Configure RBAC Permissions

After deployment, configure permissions using the managed identity:

```powershell
# Get managed identity principal ID from deployment output
$deployment = az deployment group list --resource-group $resourceGroup --query "[0].name" -o tsv
$principalId = az deployment group show --resource-group $resourceGroup --name $deployment --query "properties.outputs.managedIdentityPrincipalId.value" -o tsv

# Assign Cosmos DB permissions
az cosmosdb sql role assignment create \
  --account-name $cosmosAccount \
  --resource-group $resourceGroup \
  --scope "/" \
  --principal-id $principalId \
  --role-definition-id 00000000-0000-0000-0000-000000000002

# Assign OpenAI permissions  
$openAIResourceId = az cognitiveservices account show --name $openAIAccount --resource-group $resourceGroup --query "id" -o tsv
az role assignment create \
  --assignee $principalId \
  --role "Cognitive Services OpenAI User" \
  --scope $openAIResourceId
```

### Step 4: Test Azure Container Apps Deployment

```powershell
# Get container app URL
$containerAppUrl = az containerapp show --name mcp-toolkit --resource-group $resourceGroup --query "properties.configuration.ingress.fqdn" -o tsv
$fullUrl = "https://$containerAppUrl"

# Test health endpoint
Invoke-RestMethod -Uri "$fullUrl/health" -Method Get

# Check container logs
az containerapp logs show --name mcp-toolkit --resource-group $resourceGroup --follow
```

### Step 5: VS Code Integration Test (Azure)
Update `.vscode/mcp.json`:
```json
{
  "servers": {
    "azure-cosmos-db-mcp": {
      "type": "http",
      "url": "https://your-container-app-url.azurecontainerapps.io"
    }
  }
}
```

## Testing Scenario 3: Comprehensive Functionality Tests

### Database Operations Tests
```
# In GitHub Copilot Chat:
@copilot "List all databases in my Cosmos DB account"
@copilot "Create a test database called 'mcptest' if it doesn't exist"
@copilot "List containers in the 'mcptest' database"
```

### Document Query Tests
```
# Add some test data first, then:
@copilot "Get the last 5 documents from container 'products' in database 'mcptest'"
@copilot "Find document with ID 'test-1' in the 'products' container"
@copilot "Search for documents containing 'test' in the 'name' property"
```

### Schema Discovery Tests
```
@copilot "Show me the schema of the 'products' container in 'mcptest' database"
@copilot "What properties are available in the 'orders' container?"
```

### Vector Search Tests (Requires OpenAI)
```
# First add documents with vector embeddings, then:
@copilot "Find products similar to 'wireless headphones' using vector search"
@copilot "Search for semantically similar content to 'customer complaint'"
```

## Troubleshooting Common Issues

### Issue 1: Health Check Fails
**Symptoms**: HTTP 500 or timeout on `/health` endpoint
**Solutions**:
1. Check container logs: `docker-compose logs mcp-toolkit` or `az containerapp logs show`
2. Verify environment variables are set correctly
3. Check if managed identity has proper RBAC permissions

### Issue 2: MCP Server Not Responding  
**Symptoms**: VS Code can't connect to MCP server
**Solutions**:
1. Verify the URL in `.vscode/mcp.json` is correct
2. Test the health endpoint directly with curl/Invoke-RestMethod
3. Restart VS Code after changing MCP configuration

### Issue 3: Authentication Errors
**Symptoms**: "Unauthorized" or "Forbidden" errors in logs
**Solutions**:
1. Verify managed identity has Cosmos DB Data Contributor role
2. Check OpenAI service permissions
3. For local development, ensure `az login` is current

### Issue 4: Container Won't Start
**Symptoms**: Container exits immediately or fails to start
**Solutions**:
1. Check Docker Desktop is running
2. Verify Dockerfile syntax: `docker build -t test .`
3. Check resource constraints and memory limits

## Performance Testing

### Load Testing
```powershell
# Simple load test using PowerShell
$url = "https://your-container-app.azurecontainerapps.io/health"
1..10 | ForEach-Object -Parallel {
    Measure-Command { Invoke-RestMethod -Uri $using:url }
} | Measure-Object -Property TotalMilliseconds -Average
```

### Scaling Verification
```powershell
# Check current replicas
az containerapp revision list --name mcp-toolkit --resource-group $resourceGroup --query "[?properties.active].{name:name, replicas:properties.replicas}"

# Monitor scaling during load
az containerapp logs tail --name mcp-toolkit --resource-group $resourceGroup
```

## Cleanup

### Local Environment
```powershell
docker-compose down
docker-compose down --volumes  # Removes persistent data
docker rmi mcp-toolkit-test    # Remove test image
```

### Azure Resources
```powershell
# Delete entire resource group (CAUTION: This deletes everything!)
az group delete --name $resourceGroup --yes --no-wait
```

## Success Criteria

Your MCP Toolkit is working correctly when:

- [ ] Health endpoint returns HTTP 200
- [ ] Container logs show no authentication errors
- [ ] VS Code GitHub Copilot can connect to MCP server
- [ ] Basic database queries work through Copilot Chat
- [ ] Container scales under load (Azure Container Apps)
- [ ] RBAC permissions are correctly configured
- [ ] Vector search works (if OpenAI is configured)

## Next Steps After Successful Testing

1. **Production Deployment**: Use the GitHub Actions workflow for CI/CD
2. **Monitoring Setup**: Configure Application Insights and alerts
3. **Security Review**: Audit RBAC permissions and network access
4. **Documentation**: Update team documentation with MCP server URLs
5. **Integration**: Connect to Azure AI Foundry or other AI services

---

**Need Help?** 
- Check the main README.md for detailed configuration options
- Review Azure Container Apps documentation for platform-specific issues
- Use `az containerapp logs show` for real-time troubleshooting