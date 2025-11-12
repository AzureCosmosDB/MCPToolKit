# Deployment Scripts

This folder contains scripts for deploying and managing the Azure Cosmos DB MCP Toolkit.

## Main Deployment Scripts

### Deploy-Cosmos-MCP-Toolkit.ps1

The main deployment script that provisions all Azure resources and deploys the MCP Toolkit.

**Usage:**
```powershell
.\scripts\Deploy-Cosmos-MCP-Toolkit.ps1 -ResourceGroup "YOUR-RESOURCE-GROUP" -Location "eastus"
```

**Parameters:**
- `-ResourceGroup` (Required): Name of the Azure resource group
- `-Location` (Optional): Azure region (default: eastus)
- `-CosmosAccountName` (Optional): Name for Cosmos DB account (auto-generated if not provided)
- `-ContainerAppName` (Optional): Name for Container App (auto-generated if not provided)
- `-EntraAppName` (Optional): Name of existing Entra App (skips app creation)
- `-ServiceManagementReference` (Optional): GUID for service management reference

**See Also:** [Main README](../README.md) for detailed deployment instructions

### Setup-AIFoundry-Connection.ps1

Configures AI Foundry (Azure ML) connections for the deployed MCP Toolkit.

**Usage:**
```powershell
.\scripts\Setup-AIFoundry-Connection.ps1
```

## Role Assignment Scripts

These scripts help manage user access to the MCP Toolkit by assigning the `Mcp.Tool.Executor` role.

### Assign-Role-To-Current-User.ps1

Assigns the `Mcp.Tool.Executor` role to the currently logged-in user.

**When to use:**
- After deployment completes
- For Visual Studio subscriptions / personal Microsoft accounts
- When auto-assignment during deployment fails

**Usage:**
```powershell
.\scripts\Assign-Role-To-Current-User.ps1
```

**What it does:**
- Gets your Object ID using Graph API `/me` endpoint (works for all account types)
- Reads configuration from `deployment-info.json`
- Assigns the role automatically
- Shows clear success/error messages

**Example Output:**
```
==========================================
Assign Role to Current User
==========================================

Getting your Object ID from Microsoft Graph...
✓ User: John Doe (john@company.com)
✓ Object ID: 12345678-1234-1234-1234-123456789abc

Reading deployment configuration...
✓ Service Principal Object ID: 87654321-4321-4321-4321-cba987654321
✓ App Client ID: abcdef12-3456-7890-abcd-ef1234567890

Assigning 'Mcp.Tool.Executor' role...

==========================================
✅ SUCCESS! Role assigned.
==========================================

Next steps:
  1. Sign out from the web UI
  2. Use Incognito/Private browser window
  3. Sign in again to get a fresh token with the role
```

### Assign-Role-To-Users.ps1

Assigns the `Mcp.Tool.Executor` role to one or more users.

**When to use:**
- To grant access to teammates
- To assign roles to multiple users at once
- For bulk user provisioning

**Usage:**
```powershell
# Assign to multiple users at once
.\scripts\Assign-Role-To-Users.ps1 -UserEmails "user1@company.com,user2@company.com,user3@company.com"

# Or run interactively (will prompt for emails)
.\scripts\Assign-Role-To-Users.ps1
```

**Parameters:**
- `-UserEmails` (Optional): Comma-separated list of user emails. If not provided, prompts interactively.
- `-DeploymentInfoPath` (Optional): Path to deployment-info.json (default: current directory)

**What it does:**
- Handles both corporate accounts and Visual Studio subscriptions
- Tries multiple lookup methods if standard lookup fails
- Shows detailed results for each user
- Provides helpful error messages and next steps

**Example Output:**
```
==========================================
Assign Roles to Multiple Users
==========================================

Reading deployment configuration...
✓ Service Principal Object ID: 87654321-4321-4321-4321-cba987654321
✓ App Client ID: abcdef12-3456-7890-abcd-ef1234567890

Users to assign roles to:
  • user1@company.com
  • user2@company.com
  • user3@company.com

Processing: user1@company.com
  ✓ Found user: 11111111-1111-1111-1111-111111111111
  ✅ Role assigned to user1@company.com

Processing: user2@company.com
  ✓ Found user: 22222222-2222-2222-2222-222222222222
  ℹ️ Role already assigned to user2@company.com

==========================================
Summary
==========================================

✅ Successfully assigned: 2
ℹ️ Already assigned: 1
❌ Failed: 0
```

### Verify-Role-Assignments.ps1

Lists all users who have been assigned the `Mcp.Tool.Executor` role.

**When to use:**
- To verify role assignments after deployment
- To audit who has access to the MCP Toolkit
- To troubleshoot authentication issues

**Usage:**
```powershell
.\scripts\Verify-Role-Assignments.ps1
```

**Parameters:**
- `-DeploymentInfoPath` (Optional): Path to deployment-info.json (default: current directory)

**What it does:**
- Lists all users with the `Mcp.Tool.Executor` role
- Shows user details (name, email, UPN, Object ID)
- Displays when each role was assigned
- Shows application information

**Example Output:**
```
==========================================
Verify Role Assignments
==========================================

Reading deployment configuration...
✓ Service Principal Object ID: 87654321-4321-4321-4321-cba987654321
✓ App Client ID: abcdef12-3456-7890-abcd-ef1234567890

Fetching role assignments...
✅ Found 3 user(s) with 'Mcp.Tool.Executor' role:

User              Assigned
----              --------
John Doe          2025-01-15T10:30:00Z
Jane Smith        2025-01-15T11:45:00Z
Bob Johnson       2025-01-16T09:15:00Z

Details:
  • John Doe
    Email: john@company.com
    UPN: john@company.com
    Object ID: 12345678-1234-1234-1234-123456789abc
    Assigned: 2025-01-15T10:30:00Z

  • Jane Smith
    Email: jane@company.com
    UPN: jane@company.com
    Object ID: 23456789-2345-2345-2345-23456789abcd
    Assigned: 2025-01-15T11:45:00Z

  • Bob Johnson
    Email: bob@company.com
    UPN: bob@company.com
    Object ID: 34567890-3456-3456-3456-34567890abcd
    Assigned: 2025-01-16T09:15:00Z

==========================================
Application Information
==========================================

App Name: Azure Cosmos DB MCP Toolkit API
Client ID: abcdef12-3456-7890-abcd-ef1234567890
Container App URL: https://ca-mcpkitenvironment-xxxxx.azurecontainerapps.io
```

## Common Workflows

### Initial Deployment

1. **Deploy the infrastructure:**
   ```powershell
   .\scripts\Deploy-Cosmos-MCP-Toolkit.ps1 -ResourceGroup "my-mcp-rg" -Location "eastus"
   ```

2. **Assign role to yourself:**
   ```powershell
   .\scripts\Assign-Role-To-Current-User.ps1
   ```

3. **Verify the assignment:**
   ```powershell
   .\scripts\Verify-Role-Assignments.ps1
   ```

### Adding Team Members

1. **Assign roles to multiple users:**
   ```powershell
   .\scripts\Assign-Role-To-Users.ps1 -UserEmails "teammate1@company.com,teammate2@company.com"
   ```

2. **Verify all assignments:**
   ```powershell
   .\scripts\Verify-Role-Assignments.ps1
   ```

### Troubleshooting Access Issues

1. **Verify role assignments:**
   ```powershell
   .\scripts\Verify-Role-Assignments.ps1
   ```

2. **If user is missing, assign the role:**
   ```powershell
   # For the current user
   .\scripts\Assign-Role-To-Current-User.ps1
   
   # For other users
   .\scripts\Assign-Role-To-Users.ps1 -UserEmails "missing-user@company.com"
   ```

3. **Verify again:**
   ```powershell
   .\scripts\Verify-Role-Assignments.ps1
   ```

## Prerequisites

All scripts require:
- **Azure CLI** installed and in PATH
- **Authenticated Azure session** (`az login`)
- **Appropriate permissions** to create resources and assign roles

## Files Created

### deployment-info.json

Created by `Deploy-Cosmos-MCP-Toolkit.ps1` and used by role assignment scripts.

**Contents:**
```json
{
    "entraAppClientId": "your-app-client-id",
    "entraAppSpObjectId": "your-service-principal-object-id",
    "tenantId": "your-tenant-id",
    "containerAppUrl": "https://your-app.azurecontainerapps.io",
    "cosmosAccountName": "your-cosmos-account",
    "resourceGroup": "your-resource-group"
}
```

## Troubleshooting

For detailed troubleshooting information, see:
- [TROUBLESHOOTING-DEPLOYMENT.md](../docs/TROUBLESHOOTING-DEPLOYMENT.md)

### Common Issues

| Issue | Script to Use |
|-------|--------------|
| Can't sign in to web UI | `Assign-Role-To-Current-User.ps1` |
| Teammate needs access | `Assign-Role-To-Users.ps1` |
| Check who has access | `Verify-Role-Assignments.ps1` |
| Visual Studio subscription user | `Assign-Role-To-Current-User.ps1` |
| HTTP 401 errors | `Verify-Role-Assignments.ps1` then assign if missing |

## Additional Resources

- [Main README](../README.md) - Deployment and usage instructions
- [Troubleshooting Guide](../docs/TROUBLESHOOTING-DEPLOYMENT.md) - Detailed troubleshooting steps
- [Architecture Documentation](../docs/ARCHITECTURE.md) - System architecture overview
