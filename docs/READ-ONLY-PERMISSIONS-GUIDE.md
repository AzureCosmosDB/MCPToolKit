# 🔒 Read-Only Cosmos DB Permissions Guide

This guide provides step-by-step instructions for configuring read-only access to Azure Cosmos DB for the MCP Toolkit.

## 🎯 Quick Start (Recommended)

For most production scenarios, use the built-in data reader role:

```bash
# 1. Get your managed identity ID (from deployment or container app)
MANAGED_IDENTITY_ID=$(az containerapp show \
    --name "your-mcp-app" \
    --resource-group "your-resource-group" \
    --query identity.principalId -o tsv)

# 2. Set your Cosmos DB details
COSMOS_ACCOUNT="your-cosmos-account"
COSMOS_RG="your-cosmos-resource-group"

# 3. Assign read-only role
az cosmosdb sql role assignment create \
    --account-name $COSMOS_ACCOUNT \
    --resource-group $COSMOS_RG \
    --scope "/" \
    --principal-id $MANAGED_IDENTITY_ID \
    --role-definition-name "Cosmos DB Built-in Data Reader"

# 4. Verify assignment
az cosmosdb sql role assignment list \
    --account-name $COSMOS_ACCOUNT \
    --resource-group $COSMOS_RG \
    --output table
```

## 🔐 Security Options Comparison

| Option | Security Level | Use Case | Permissions |
|--------|---------------|----------|-------------|
| **Built-in Data Reader** | High | Production | Read documents, execute queries, read metadata |
| **Custom Minimal Role** | Maximum | Regulated environments | Minimal read access only |
| **Connection String** | Low | Development only | Based on key type used |

## 📋 Detailed Instructions

### Option 1: Built-in Data Reader (Recommended)

**Pros:**
- ✅ Microsoft-managed role definition
- ✅ Appropriate for most use cases
- ✅ Easy to implement and maintain
- ✅ Well-documented and supported

**Permissions granted:**
- Read all documents in all containers
- Execute SELECT queries
- Read database and container metadata
- Access change feed (read-only)

**Permissions denied:**
- Create, update, delete documents
- Modify database or container settings
- Execute stored procedures that write data

```bash
az cosmosdb sql role assignment create \
    --account-name "your-cosmos-account" \
    --resource-group "your-cosmos-rg" \
    --scope "/" \
    --principal-id "your-managed-identity-id" \
    --role-definition-name "Cosmos DB Built-in Data Reader"
```

### Option 2: Custom Minimal Role (Maximum Security)

**Pros:**
- ✅ Granular permission control
- ✅ Explicitly denies write operations
- ✅ Audit-friendly with clear permissions
- ✅ Customizable for specific requirements

**Use when:**
- Compliance requires explicit permission definitions
- Need to audit exact permissions granted
- Working in highly regulated environments

```bash
# Create role definition
cat > minimal-readonly.json << 'EOF'
{
    "RoleName": "MCP Minimal Read Only",
    "Type": "CustomRole",
    "AssignableScopes": ["/"],
    "Permissions": [{
        "DataActions": [
            "Microsoft.DocumentDB/databaseAccounts/readMetadata",
            "Microsoft.DocumentDB/databaseAccounts/sqlDatabases/containers/items/read",
            "Microsoft.DocumentDB/databaseAccounts/sqlDatabases/containers/executeQuery"
        ],
        "NotDataActions": [
            "Microsoft.DocumentDB/databaseAccounts/sqlDatabases/containers/items/create",
            "Microsoft.DocumentDB/databaseAccounts/sqlDatabases/containers/items/upsert",
            "Microsoft.DocumentDB/databaseAccounts/sqlDatabases/containers/items/replace",
            "Microsoft.DocumentDB/databaseAccounts/sqlDatabases/containers/items/delete"
        ]
    }]
}
EOF

# Create and assign role
ROLE_ID=$(az cosmosdb sql role definition create \
    --account-name "your-cosmos-account" \
    --resource-group "your-cosmos-rg" \
    --body @minimal-readonly.json \
    --query id -o tsv)

az cosmosdb sql role assignment create \
    --account-name "your-cosmos-account" \
    --resource-group "your-cosmos-rg" \
    --scope "/" \
    --principal-id "your-managed-identity-id" \
    --role-definition-id $ROLE_ID

rm minimal-readonly.json
```

### Option 3: Connection String (Development Only)

**⚠️ Warning:** Only for development/testing environments!

**Requirements:**
- Use read-only connection string (never primary key)
- Implement key rotation policies
- Monitor usage and access patterns

```bash
# Get read-only connection string from Azure Portal:
# Navigate to: Cosmos DB Account → Keys → Read-only Connection String

az containerapp update \
    --name "your-app" \
    --resource-group "your-rg" \
    --set-env-vars \
        COSMOS_CONNECTION_STRING="AccountEndpoint=https://account.documents.azure.com:443/;AccountKey=readonly-key=="
```

## 🧪 Testing Read-Only Access

After configuring permissions, verify they work correctly:

### Test 1: Verify Read Access
```bash
# This should work - reading documents
curl -X POST \
  -H "Content-Type: application/json" \
  -d '{"jsonrpc":"2.0","id":"1","method":"tools/call","params":{"name":"get_recent_documents","arguments":{"databaseId":"your-db","containerId":"your-container","n":5}}}' \
  "https://your-app.azurecontainerapps.io/mcp"
```

### Test 2: Verify Write Protection
```bash
# This should fail - attempting to create documents
curl -X POST \
  -H "Content-Type: application/json" \
  -d '{"jsonrpc":"2.0","id":"2","method":"tools/call","params":{"name":"create_document","arguments":{"databaseId":"test","containerId":"test","document":{"id":"test"}}}}' \
  "https://your-app.azurecontainerapps.io/mcp"

# Expected: Error indicating insufficient permissions
```

## 🔍 Troubleshooting

### Common Issues

1. **"Forbidden" or "Unauthorized" errors:**
   ```bash
   # Check role assignments
   az cosmosdb sql role assignment list \
       --account-name "your-cosmos-account" \
       --resource-group "your-cosmos-rg"
   ```

2. **Role assignment not taking effect:**
   ```bash
   # Wait 5-10 minutes for propagation, then restart container app
   az containerapp restart \
       --name "your-app" \
       --resource-group "your-rg"
   ```

3. **Cannot read metadata:**
   ```bash
   # Ensure readMetadata permission is included
   # Check firewall settings on Cosmos DB
   ```

### Verification Commands

```bash
# Check managed identity
az containerapp show \
    --name "your-app" \
    --resource-group "your-rg" \
    --query "identity"

# List all role assignments
az cosmosdb sql role assignment list \
    --account-name "your-cosmos-account" \
    --resource-group "your-cosmos-rg" \
    --output table

# Check container app environment variables
az containerapp show \
    --name "your-app" \
    --resource-group "your-rg" \
    --query "properties.template.containers[0].env"
```

## 📚 Additional Resources

- [Azure Cosmos DB RBAC Documentation](https://docs.microsoft.com/azure/cosmos-db/how-to-setup-rbac)
- [Container Apps Managed Identity](https://docs.microsoft.com/azure/container-apps/managed-identity)
- [Cosmos DB Security Best Practices](https://docs.microsoft.com/azure/cosmos-db/database-security)

---

**🎯 Result:** Your MCP Toolkit will have secure, read-only access to Cosmos DB with no risk of data modification!