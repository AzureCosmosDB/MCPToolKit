# Azure Policy Owner Tag Workaround

If your Azure subscription requires an "owner" tag on all resources, use this workaround to deploy the MCP Toolkit.

## Quick Fix

### Option 1: PowerShell Script (Recommended)

```powershell
# Navigate to the infrastructure directory
cd infrastructure

# Run the deployment script with owner tag
./deploy-with-owner-tag.ps1 -ResourceGroupName "rg-mcp-toolkit" -Location "East US" -PrincipalId "your-user-object-id" -OwnerTag "your-email@company.com"
```

### Option 2: Manual Bicep Deployment

```powershell
# Get your user object ID
$principalId = az ad signed-in-user show --query id -o tsv

# Create resource group with owner tag
az group create --name "rg-mcp-toolkit" --location "East US" --tags owner="your-email@company.com"

# Deploy using Bicep template
az deployment group create \
  --resource-group "rg-mcp-toolkit" \
  --template-file "deploy-all-resources.bicep" \
  --parameters \
    "principalId=$principalId" \
    "ownerTag=your-email@company.com"
```

### Option 3: Use Azure Portal with Modified Template

1. Download the Bicep file: `deploy-all-resources.bicep`
2. The file already includes the `ownerTag` parameter
3. Deploy using Azure CLI as shown in Option 2

## What Changed

The Bicep template now includes:
- `ownerTag` parameter (required)
- `commonTags` variable that includes the owner tag
- All resources now use the `commonTags` variable

## Error You Might See

```json
{
  "code": "RequestDisallowedByPolicy",
  "message": "Resource 'rg-mcp-toolkit' was disallowed by policy. Policy identifiers: '[{\"policyAssignment\":{\"name\":\"Require owner tag\"..."
}
```

This means your subscription has a policy requiring all resources to have an "owner" tag. Use one of the options above to comply with this policy.