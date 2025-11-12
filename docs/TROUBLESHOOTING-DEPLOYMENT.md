# Troubleshooting Guide - Azure Cosmos DB MCP Toolkit

This guide covers common issues you may encounter during deployment and usage of the Azure Cosmos DB MCP Toolkit.

## Table of Contents

- [Common Deployment Issues](#common-deployment-issues)
  - [Entra App Creation Fails - Service Management Reference](#1-entra-app-creation-fails---service-management-reference-required)
  - [Service Principal Creation Fails](#2-service-principal-creation-fails)
  - [ACR Login Fails - Resource Not Found](#3-acr-login-fails---resource-not-found)
  - [Auto-Detection Times Out](#auto-detection-times-out-service-management-reference)
  - [Docker Push Fails - Network/SSL Errors](#docker-push-fails---networkssl-errors)
- [Authentication & Role Assignment Issues](#authentication--role-assignment-issues)
  - [Invalid or Expired Token (HTTP 401)](#invalid-or-expired-token-http-401-when-testing)
- [Testing Tips](#testing-tips)
- [Getting Help](#getting-help)

---

## Common Deployment Issues

### 1. Entra App Creation Fails - Service Management Reference Required

**Error Message:**
```
ServiceManagementReference parameter is required for your subscription
```

**Cause:** Your Microsoft subscription has a policy requiring organization-specific GUIDs for app creation.

**Solution:**

The script attempts to auto-detect the GUID from existing apps. If it fails or times out:

#### Option A: Skip Auto-Detection (Fastest)

If you already created the app manually, rerun with the app name:

```powershell
.\scripts\Deploy-Cosmos-MCP-Toolkit.ps1 -ResourceGroup "YOUR-RG" -EntraAppName "Azure Cosmos DB MCP Toolkit API"
```

#### Option B: Manual Creation

1. Find the service-management-reference GUID from any existing app:
   ```powershell
   az ad app list --top 5 --query "[?serviceManagementReference != null] | [0].{name:displayName, guid:serviceManagementReference}"
   ```

2. Create the app manually with the GUID:
   ```powershell
   az ad app create --display-name "Azure Cosmos DB MCP Toolkit API" --service-management-reference YOUR_GUID_HERE
   ```

3. Rerun the deployment script with the app name:
   ```powershell
   .\scripts\Deploy-Cosmos-MCP-Toolkit.ps1 -ResourceGroup "YOUR-RG" -EntraAppName "Azure Cosmos DB MCP Toolkit API"
   ```

---

### 2. Service Principal Creation Fails

**Error Message:**
```
Resource 'xxxx-xxxx-xxxx' does not exist or one of its queried reference-property objects are not present
```

**Cause:** The Service Principal for the Entra App doesn't exist yet (it's created separately from the App Registration).

**Solution:** The script automatically creates it. If you see this error, it's informational only. The script will:
1. Detect the Service Principal is missing
2. Create it automatically
3. Continue with deployment

**Manual verification:**
```powershell
# Check if Service Principal exists
az ad sp list --display-name "Azure Cosmos DB MCP Toolkit API"

# Create manually if needed
az ad sp create --id YOUR_APP_CLIENT_ID
```

---

### 3. ACR Login Fails - Resource Not Found

**Error Message:**
```
The Resource 'Microsoft.ContainerRegistry/registries/xxx' under resource group 'wrong-rg' was not found
```

**Cause:** The script is looking for ACR in the wrong resource group.

**Solution:** This has been fixed in the latest version. Ensure you're using the updated script and specify the correct resource group:

```powershell
.\scripts\Deploy-Cosmos-MCP-Toolkit.ps1 -ResourceGroup "YOUR-CORRECT-RESOURCE-GROUP"
```

---

### Auto-Detection Times Out (Service Management Reference)

**Symptoms:**
- Script shows: "Attempting to auto-detect service-management-reference GUID from existing apps..."
- Takes 5+ minutes or times out after 30 seconds

**Solution:**

The script has been optimized to query only 5 apps. If it still times out:

**Use the manual creation method** (see [Entra App Creation Fails](#1-entra-app-creation-fails---service-management-reference-required) above) or **provide the app name** if already created:

```powershell
.\scripts\Deploy-Cosmos-MCP-Toolkit.ps1 -ResourceGroup "YOUR-RG" -EntraAppName "Azure Cosmos DB MCP Toolkit API"
```

---

### Docker Push Fails - Network/SSL Errors

**Symptoms:**
```
Failed to build or push container image: ACR login failed
SSL connection error
EOF during push
Error response from daemon: Get "https://xxx.azurecr.io/v2/": net/http: TLS handshake timeout
```

**Cause:** Network connectivity issues to Azure Container Registry (ACR).

**Solution:**

The script gracefully handles this - deployment continues using the existing container image. To fix for future deployments:

1. **Check Docker is running:**
   ```powershell
   docker ps
   ```

2. **Verify ACR connectivity:**
   ```powershell
   az acr check-health --name YOUR_ACR_NAME --yes
   ```

3. **If behind a corporate proxy**, configure Docker proxy settings

4. **Try manual login:**
   ```powershell
   az acr login --name YOUR_ACR_NAME --resource-group YOUR_RG
   ```

5. **Rerun the deployment script** once network issues are resolved

---

### User Not Found - Visual Studio Subscriptions / Personal Accounts

**Symptoms:**
```
[WARN] Could not find user object ID for: your.email@outlook.com
[WARN] You may need to manually assign the role in Azure Portal
```

**Cause:** This happens with:
- **Visual Studio subscriptions** (MSDN subscriptions)
- **Personal Microsoft Accounts** (outlook.com, hotmail.com, live.com)
- **Guest users** in Azure AD
- **Login email ≠ User Principal Name** in the directory

**Why This Happens:**

The deployment script runs:
```powershell
az ad user show --id your.email@outlook.com
```

But your actual Azure AD username might be different (e.g., `your.email_outlook.com#EXT#@tenant.onmicrosoft.com`), so the lookup fails.

**Solution - Get Your Object ID and Assign Role:**

**Latest Script (Recommended):** The deployment script has been updated to automatically handle this using the Graph API `/me` endpoint. If you're using an older version, update your script or use the provided role assignment script:

**Quick Solution - Use the Script:**

```powershell
.\scripts\Assign-Role-To-Current-User.ps1
```

This script automatically:
- Gets your Object ID using the Graph API `/me` endpoint (works for all account types)
- Reads the Service Principal ID from `deployment-info.json`
- Assigns the `Mcp.Tool.Executor` role to your account

**Manual Method (Alternative):**

If you prefer to do it manually or need to understand the steps:

1. **Get your Object ID:**
   ```powershell
   az rest --method GET --url "https://graph.microsoft.com/v1.0/me" --query "id" -o tsv
   ```

2. **Get Service Principal Object ID:**
   ```powershell
   $deploymentInfo = Get-Content deployment-info.json | ConvertFrom-Json
   $spObjectId = $deploymentInfo.entraAppSpObjectId
   ```

3. **Assign the role:**
   ```powershell
   $userObjectId = "YOUR_OBJECT_ID_FROM_STEP_1"
   $appRoleId = "c6ae5dd5-ae87-48d8-8134-e07d93fdb962"
   
   $body = @{
       principalId = $userObjectId
       resourceId = $spObjectId
       appRoleId = $appRoleId
   } | ConvertTo-Json
   
   $tempFile = "$env:TEMP\role-assignment.json"
   $body | Out-File -FilePath $tempFile -Encoding utf8 -NoNewline
   
   az rest --method POST --url "https://graph.microsoft.com/v1.0/servicePrincipals/$spObjectId/appRoleAssignedTo" --headers "Content-Type=application/json" --body "@$tempFile"
   
   Remove-Item $tempFile -Force
   ```

**After Role Assignment:**
1. Sign out from the web UI
2. Use Incognito/Private window
3. Sign in again to get a fresh token with the role

---

### Assigning Roles to Other Users

**Scenario:** You want to grant access to teammates or other users.

**Quick Solution - Use the Script:**

```powershell
# Assign to multiple users at once
.\scripts\Assign-Role-To-Users.ps1 -UserEmails "user1@company.com,user2@company.com,user3@company.com"

# Or run interactively (will prompt for emails)
.\scripts\Assign-Role-To-Users.ps1
```

This script automatically:
- Handles both corporate accounts and Visual Studio subscriptions
- Tries multiple lookup methods if standard lookup fails
- Shows detailed results for each user
- Provides helpful error messages

**Verify Role Assignments:**

```powershell
.\scripts\Verify-Role-Assignments.ps1
```

This will list all users with the `Mcp.Tool.Executor` role.

**Manual Method (Alternative):**

If you prefer to do it manually:

1. **Get their Object ID:**
   ```powershell
   # For organizational users
   az ad user show --id their.email@company.com --query "id" -o tsv
   
   # If that fails, search by name
   az ad user list --query "[?contains(displayName, 'Their Name')].{name:displayName, id:id, upn:userPrincipalName}" -o table
   ```

2. **Assign the role:**
   ```powershell
   $userObjectId = "THEIR_OBJECT_ID"
   $deploymentInfo = Get-Content deployment-info.json | ConvertFrom-Json
   $spObjectId = $deploymentInfo.entraAppSpObjectId
   $appRoleId = "c6ae5dd5-ae87-48d8-8134-e07d93fdb962"
   
   $body = @{
       principalId = $userObjectId
       resourceId = $spObjectId
       appRoleId = $appRoleId
   } | ConvertTo-Json
   
   $tempFile = "$env:TEMP\role-assignment.json"
   $body | Out-File -FilePath $tempFile -Encoding utf8 -NoNewline
   
   az rest --method POST --url "https://graph.microsoft.com/v1.0/servicePrincipals/$spObjectId/appRoleAssignedTo" --headers "Content-Type=application/json" --body "@$tempFile"
   
   Remove-Item $tempFile -Force
   ```

---

## Authentication & Role Assignment Issues

### Invalid or Expired Token (HTTP 401) When Testing

**Symptoms:**
- Web UI shows: `Authentication failed. Please check: 1. You have the 'Mcp.Tool.Executor' role...`
- Error: `{"error":{"code":-32002,"message":"Invalid or expired token"}}`
- The "Roles" field shows "No roles found" after login

**Root Cause:** Your user doesn't have the `Mcp.Tool.Executor` role assigned, even though the deployment script attempted to assign it.

#### Why This Happens

The deployment script tries to automatically assign the role, but it requires **Graph API permissions** (`AppRoleAssignment.ReadWrite.All`) that many users don't have. The script will show a warning if auto-assignment fails.

#### Solution - Manual Role Assignment (Required)

You **MUST** manually assign the role through the Azure Portal:

1. Open [Azure Portal](https://portal.azure.com)
2. Navigate to **Microsoft Entra ID** (formerly Azure Active Directory)
3. Click **Enterprise Applications** in the left menu
4. In the search box, type: **Azure Cosmos DB MCP Toolkit API** (or your custom app name)
5. Click on the application
6. Click **Users and groups** in the left menu
7. Click **+ Add user/group** at the top
8. Under **Users**, click **None Selected**
   - Search for your user account
   - Select your user
   - Click **Select**
9. Under **Select a role**, click **None Selected**
   - Select **Mcp.Tool.Executor**
   - Click **Select**
10. Click **Assign** at the bottom

#### After Role Assignment

The role assignment takes effect **immediately**, but you need a fresh token:

1. **Sign out completely** from the web UI
2. **Clear browser cache** or use an **Incognito/Private window**
3. **Sign in again** to get a new token with the role claim
4. Verify the "Roles" field now shows: **Mcp.Tool.Executor**

#### Verification Commands

```powershell
# Check if role is assigned to your user
$appId = (Get-Content deployment-info.json | ConvertFrom-Json).entraAppClientId
$userEmail = az account show --query "user.name" -o tsv
az ad app show --id $appId --query "appRoles[?value=='Mcp.Tool.Executor'].{id:id}" -o tsv

# List all users with the role
az ad sp show --id $appId --query "appRoleAssignedTo" 2>$null
```

---

## Testing Tips

### Use the Test UI to Verify Authentication

1. Open `https://YOUR-CONTAINER-APP.azurecontainerapps.io`
2. Enter your **Client ID** and **Tenant ID** (from `deployment-info.json`)
3. Click **Sign In with Microsoft Entra**
4. After login, check:
   - ✅ **Auth Status**: Should show "Authenticated" (green)
   - ✅ **Roles**: Should show "Mcp.Tool.Executor"
   - ❌ If "Roles" shows "No roles found" → Follow [manual role assignment steps](#solution---manual-role-assignment-required) above

### Test MCP Tools

1. Click **List Tools** - should return all available MCP tools
2. Click **Test Tool** - should successfully call `list_databases`
3. If you get HTTP 401 → Your role is not assigned (see above)

### Common Test UI Issues

- **"Client ID and Tenant ID should be different"** → You swapped them, check `deployment-info.json`
- **"Application not found in directory"** → Wrong Client ID, verify from portal or `deployment-info.json`
- **"Authentication failed" after successful login** → Role not assigned, follow manual steps above

---

## Getting Help

If issues persist after trying these solutions:

### 1. Check Container Logs

```powershell
az containerapp logs show --name YOUR_CONTAINER_APP --resource-group YOUR_RG --follow
```

### 2. Verify Deployment Info

```powershell
Get-Content deployment-info.json | ConvertFrom-Json | Format-List
```

### 3. Check RBAC Assignments

```powershell
# Check Cosmos DB role assignment
az cosmosdb sql role assignment list --account-name YOUR_COSMOS_ACCOUNT --resource-group YOUR_RG

# Check Container App managed identity
az containerapp identity show --name YOUR_CONTAINER_APP --resource-group YOUR_RG
```

### 4. Open a GitHub Issue

Include the following information:
- Error messages from the deployment script
- Container app logs (sanitize sensitive information)
- Steps you've already tried
- Output from verification commands above

---

## Quick Reference

### Most Common Issues

| Issue | Quick Fix |
|-------|-----------|
| HTTP 401 - Invalid token | [Manual role assignment](#solution---manual-role-assignment-required) in Azure Portal |
| User not found / Visual Studio subscription | Use [Graph API /me endpoint](#user-not-found---visual-studio-subscriptions--personal-accounts) to get Object ID |
| Service management reference error | Use `-EntraAppName` parameter with existing app name |
| ACR login fails | Verify resource group name is correct |
| Auto-detection timeout | Skip auto-detection with `-EntraAppName` parameter |
| Docker push fails / TLS handshake timeout | Check Docker is running, verify ACR connectivity |
| Need to assign role to other users | Follow [Assigning Roles to Other Users](#assigning-roles-to-other-users) guide |

### Key Files

- `deployment-info.json` - Contains all configuration values (Client ID, Tenant ID, URLs)
- Container App logs - Check for runtime errors
- Browser DevTools Console - Check for frontend authentication errors

### Useful Commands

```powershell
# Get deployment info
Get-Content deployment-info.json | ConvertFrom-Json

# Check if app exists
az ad app list --display-name "Azure Cosmos DB MCP Toolkit API"

# Check container app status
az containerapp show --name YOUR_APP --resource-group YOUR_RG --query "properties.runningStatus"

# Test health endpoint
curl https://YOUR-CONTAINER-APP.azurecontainerapps.io/health
```

---

**Need more help?** Check the main [README](../README.md) or open an issue on [GitHub](https://github.com/AzureCosmosDB/MCPToolKit/issues).
