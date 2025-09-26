# MCP Toolkit Troubleshooting Guide

## Authentication Issues

### Problem: ManagedIdentityCredential Authentication Failed

**Symptoms:**
- MCP tools fail with "ManagedIdentityCredential authentication failed"
- Error: "Unable to load the proper Managed Identity"
- VS Code GitHub Copilot Chat returns authentication errors

**Root Cause:**
- Stale Cosmos DB role assignments
- Container app needs authentication token refresh
- Missing or incorrect managed identity configuration

**Solution Steps:**

1. **Recreate Cosmos DB Role Assignment**
```bash
# List current role assignments
az cosmosdb sql role assignment list --account-name "mcp-toolkit-cosmos-lho6nfkzly22o" --resource-group "rg-sajee-mcp-toolkit"

# Delete old assignment (replace with actual assignment ID)
az cosmosdb sql role assignment delete --account-name "mcp-toolkit-cosmos-lho6nfkzly22o" --resource-group "rg-sajee-mcp-toolkit" --role-assignment-id "<OLD_ASSIGNMENT_ID>"

# Get managed identity principal ID
az containerapp show --name "mcp-toolkit-app" --resource-group "rg-sajee-mcp-toolkit" --query "identity.userAssignedIdentities.*.principalId" -o tsv

# Create new role assignment with Built-in Data Contributor role
az cosmosdb sql role assignment create --account-name "mcp-toolkit-cosmos-lho6nfkzly22o" --resource-group "rg-sajee-mcp-toolkit" --role-definition-id "00000000-0000-0000-0000-000000000002" --principal-id "<PRINCIPAL_ID>"
```

2. **Update Container App Configuration**
```bash
# Add managed identity client ID as environment variable
az containerapp update --name "mcp-toolkit-app" --resource-group "rg-sajee-mcp-toolkit" --set-env-vars "AZURE_CLIENT_ID=<CLIENT_ID>"

# Restart container app to refresh tokens
az containerapp revision restart --name "mcp-toolkit-app" --resource-group "rg-sajee-mcp-toolkit" --revision "<CURRENT_REVISION>"
```

3. **Verify Authentication**
```bash
# Check container app health
curl https://mcp-toolkit-app.greenrock-3ca4379b.eastus.azurecontainerapps.io/health

# Test MCP functionality through VS Code GitHub Copilot Chat
# Query: "List all databases in my Cosmos DB account"
```

**Prevention:**
- Monitor container app logs regularly
- Verify role assignments after infrastructure updates
- Test MCP functionality after deployments

## Health Check Endpoints

- **Application Health:** `https://mcp-toolkit-app.greenrock-3ca4379b.eastus.azurecontainerapps.io/health`
- **Expected Response:** `200 OK` with "Healthy" content

## Logging and Monitoring

```bash
# View container app logs
az containerapp logs show --name "mcp-toolkit-app" --resource-group "rg-sajee-mcp-toolkit" --follow

# Check specific revision logs
az containerapp revision list --name "mcp-toolkit-app" --resource-group "rg-sajee-mcp-toolkit"
```

## Common Error Messages

### "ManagedIdentityCredential authentication failed"
- **Solution:** Recreate role assignments and restart container app

### "Unable to load the proper Managed Identity"
- **Solution:** Verify AZURE_CLIENT_ID environment variable is set

### "403 Forbidden" from Cosmos DB
- **Solution:** Check role assignment exists with correct principal ID

## Support Resources

- [Azure Container Apps Documentation](https://docs.microsoft.com/azure/container-apps/)
- [Azure Cosmos DB RBAC](https://docs.microsoft.com/azure/cosmos-db/how-to-setup-rbac)
- [Managed Identity Documentation](https://docs.microsoft.com/azure/active-directory/managed-identities-azure-resources/)