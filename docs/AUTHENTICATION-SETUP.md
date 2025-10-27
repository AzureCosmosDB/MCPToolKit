# Authentication Setup Guide

This guide explains how to set up Azure Entra ID authentication for the Azure Cosmos DB MCP Toolkit following the same pattern as the [Azure PostgreSQL MCP Demo](https://github.com/Azure-Samples/azure-postgres-mcp-demo).

## Overview

The toolkit supports two authentication modes:

1. **Production Mode**: Full Azure Entra ID authentication with JWT Bearer tokens
2. **Development Mode**: Authentication bypass for local development and testing

## Production Authentication Setup

### 1. Deploy Infrastructure with Entra ID App Registration

The Bicep templates automatically create:
- Azure Container Apps environment
- Container Registry
- Entra ID application registration with `Mcp.Tool.Executor` role
- Managed Identity role assignments

```bash
# Deploy infrastructure
cd infrastructure
az deployment group create \
    --resource-group <your-resource-group> \
    --template-file deploy-all-resources.bicep \
    --parameters @deploy-all-resources.parameters.json
```

### 2. Configure User Access

After deployment, assign users to the `Mcp.Tool.Executor` role:

```bash
# Get the Application ID from deployment output
APP_ID=$(az deployment group show \
    --resource-group <your-resource-group> \
    --name <deployment-name> \
    --query properties.outputs.entraAppClientId.value -o tsv)

# Assign user to the MCP Tool Executor role
az ad app-role-assignment create \
    --id $APP_ID \
    --app-role-id $(az ad app show --id $APP_ID --query "appRoles[?value=='Mcp.Tool.Executor'].id" -o tsv) \
    --assignee-object-id $(az ad user show --id <user-email> --query id -o tsv)
```

### 3. Configure Cosmos DB Read-Only Access

After deployment, configure read-only access to your existing Cosmos DB account. **Choose ONE of the following options based on your security requirements:**

#### Option 1: Cosmos DB Built-in Data Reader (Recommended)

This is the **most secure option** for production environments:

```bash
# Get the managed identity principal ID from deployment output
MANAGED_IDENTITY_ID=$(az deployment group show \
    --resource-group <your-resource-group> \
    --name <deployment-name> \
    --query properties.outputs.managedIdentityPrincipalId.value -o tsv)

echo "Managed Identity Principal ID: $MANAGED_IDENTITY_ID"

# Assign Cosmos DB Built-in Data Reader role
az cosmosdb sql role assignment create \
    --account-name <your-cosmos-account> \
    --resource-group <cosmos-resource-group> \
    --scope "/" \
    --principal-id $MANAGED_IDENTITY_ID \
    --role-definition-name "Cosmos DB Built-in Data Reader"
```

**What this provides:**
- ✅ Read access to all databases and containers
- ✅ Query execution permissions
- ✅ Metadata reading capabilities
- ❌ No write, update, or delete permissions
- ❌ No schema modification permissions

#### Option 2: Custom Read-Only Role (Maximum Security)

For environments requiring the most restrictive access:

```bash
# Step 1: Create custom read-only role definition
cat > cosmos-readonly-role.json << 'EOF'
{
    "RoleName": "MCP Toolkit Read Only",
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

# Step 2: Create the role definition
ROLE_DEF_ID=$(az cosmosdb sql role definition create \
    --account-name <your-cosmos-account> \
    --resource-group <cosmos-resource-group> \
    --body @cosmos-readonly-role.json \
    --query id -o tsv)

echo "Created role definition ID: $ROLE_DEF_ID"

# Step 3: Assign the custom role to managed identity
az cosmosdb sql role assignment create \
    --account-name <your-cosmos-account> \
    --resource-group <cosmos-resource-group> \
    --scope "/" \
    --principal-id $MANAGED_IDENTITY_ID \
    --role-definition-id $ROLE_DEF_ID

echo "✅ Custom read-only role assigned successfully"
```

#### Option 3: Azure RBAC (Account Level - Less Secure)

**⚠️ Warning:** This grants broader permissions than necessary for read-only access:

```bash
# Assign read permissions at the account level (NOT RECOMMENDED for production)
az role assignment create \
    --assignee-object-id $MANAGED_IDENTITY_ID \
    --role "DocumentDB Account Contributor" \
    --scope "/subscriptions/{subscription-id}/resourceGroups/{cosmos-rg}/providers/Microsoft.DocumentDB/databaseAccounts/{account-name}"
```

#### Option 4: Connection String (Development/Testing Only)

**⚠️ Security Risk:** Only use for development environments:

```bash
# For development environments only - NOT for production
az containerapp update \
    --name <app-name> \
    --resource-group <resource-group> \
    --set-env-vars COSMOS_CONNECTION_STRING="<read-only-connection-string>"
```

**Security Note:** Connection strings should be read-only keys and never primary keys.

### 4. Configure External Cosmos DB Endpoint

Update the container app environment variables to point to your Cosmos DB:

```bash
az containerapp update \
    --name <app-name> \
    --resource-group <resource-group> \
    --set-env-vars \
        COSMOS_ENDPOINT="https://<your-cosmos-account>.documents.azure.com:443/" \
        AZURE_OPENAI_ENDPOINT="https://<your-openai>.openai.azure.com/"
```

Clients must obtain JWT tokens from Azure Entra ID to access the MCP endpoints:

```bash
# Get access token
az account get-access-token \
    --resource api://<app-client-id> \
    --query accessToken -o tsv
```

Include the token in HTTP requests:
```
Authorization: Bearer <jwt-token>
```

## Development Mode Setup

For local development, you can bypass authentication entirely:

### Option 1: Environment Variable
```bash
# Set environment variable
$env:DEV_BYPASS_AUTH = "true"

# Run the application
dotnet run --project src/AzureCosmosDB.MCP.Toolkit
```

### Option 2: Configuration File
Update `appsettings.Development.json`:
```json
{
  "DevelopmentMode": {
    "BypassAuthentication": true
  }
}
```

## Authentication Endpoints

### Health Check
```http
GET /api/health
```
Returns authentication status and configuration.

### Authenticated Health Check
```http
GET /api/health/auth
Authorization: Bearer <jwt-token>
```
Returns detailed user information and role assignments.

## Security Model

### Roles
- **Mcp.Tool.Executor**: Required role for accessing MCP tools and operations

### Azure Cosmos DB Permissions (Read-Only)
The toolkit is designed to work with **read-only access** to Azure Cosmos DB for security best practices:

#### Required RBAC Roles for Cosmos DB:
- **Cosmos DB Account Reader Role**: Allows reading account properties
- **DocumentDB Account Contributor** (minimal): For reading database/container metadata
- **Custom Read-Only Role** (recommended): Create a custom role with only read permissions

#### Recommended Custom Role Definition:
```json
{
  "roleName": "Cosmos DB MCP Reader",
  "type": "CustomRole",
  "assignableScopes": ["/subscriptions/{subscription-id}/resourceGroups/{resource-group}/providers/Microsoft.DocumentDB/databaseAccounts/{account-name}"],
  "permissions": [
    {
      "actions": [
        "Microsoft.DocumentDB/databaseAccounts/read",
        "Microsoft.DocumentDB/databaseAccounts/sqlDatabases/read",
        "Microsoft.DocumentDB/databaseAccounts/sqlDatabases/containers/read",
        "Microsoft.DocumentDB/databaseAccounts/sqlDatabases/containers/items/read"
      ],
      "notActions": [],
      "dataActions": [
        "Microsoft.DocumentDB/databaseAccounts/readMetadata",
        "Microsoft.DocumentDB/databaseAccounts/sqlDatabases/containers/executeQuery",
        "Microsoft.DocumentDB/databaseAccounts/sqlDatabases/containers/readChangeFeed",
        "Microsoft.DocumentDB/databaseAccounts/sqlDatabases/containers/items/read"
      ],
      "notDataActions": [
        "Microsoft.DocumentDB/databaseAccounts/sqlDatabases/containers/items/create",
        "Microsoft.DocumentDB/databaseAccounts/sqlDatabases/containers/items/upsert",
        "Microsoft.DocumentDB/databaseAccounts/sqlDatabases/containers/items/replace",
        "Microsoft.DocumentDB/databaseAccounts/sqlDatabases/containers/items/delete"
      ]
    }
  ]
}
```

#### Built-in Role Alternative:
Use the **Cosmos DB Built-in Data Reader** role:
```bash
az role assignment create \
    --assignee-object-id <managed-identity-object-id> \
    --role "Cosmos DB Built-in Data Reader" \
    --scope "/subscriptions/{subscription-id}/resourceGroups/{resource-group}/providers/Microsoft.DocumentDB/databaseAccounts/{account-name}"
```

### Token Validation
- **Issuer**: `https://login.microsoftonline.com/{tenant-id}/v2.0`
- **Audience**: Application Client ID or `api://{client-id}`
- **Claims**: 
  - `roles`: Array of assigned application roles
  - `oid`: User object ID
  - `upn` or `email`: User email
  - `name`: User display name

### Protected Endpoints
All MCP protocol endpoints require:
1. Valid JWT Bearer token
2. `Mcp.Tool.Executor` role assignment

Exception: OPTIONS requests allow anonymous access for CORS support.

## Troubleshooting

### Common Issues

1. **401 Unauthorized**: 
   - Check if token is included in Authorization header
   - Verify token hasn't expired
   - Ensure token audience matches application

2. **403 Forbidden**:
   - Verify user has `Mcp.Tool.Executor` role
   - Check role assignment in Azure Portal

3. **Token Validation Errors**:
   - Verify tenant ID and client ID configuration
   - Check token issuer and audience claims

### Debug Information

Use the health endpoints to diagnose authentication issues:

```bash
# Check authentication configuration
curl http://localhost:5000/api/health

# Test authenticated access (with token)
curl -H "Authorization: Bearer <token>" \
     http://localhost:5000/api/health/auth
```

### Development Mode Verification

When authentication bypass is enabled, the health endpoint will show:
```json
{
  "authenticationEnabled": false,
  "devMode": true,
  "user": {
    "id": "dev-user",
    "email": "dev@localhost",
    "name": "Development User"
  }
}
```

## Production Deployment

When deploying to production:

1. Ensure authentication bypass is disabled
2. Configure proper Azure Entra ID settings
3. Assign appropriate users to the `Mcp.Tool.Executor` role
4. Use HTTPS for all communications
5. Regularly rotate application secrets (if any)

## Related Documentation

- [Azure Entra ID Application Registration](https://docs.microsoft.com/azure/active-directory/develop/quickstart-register-app)
- [Azure Container Apps Authentication](https://docs.microsoft.com/azure/container-apps/authentication)
- [JWT Bearer Authentication in ASP.NET Core](https://docs.microsoft.com/aspnet/core/security/authentication/jwt-authn)