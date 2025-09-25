# Resource Naming and Parameter Fixes

## Issues Fixed

### 1. Azure Container Registry Naming Issue
**Problem**: Container registry names like `mcp-toolkitacrlho6nfkzly22o` contained hyphens, which are not allowed in ACR names.

**Solution**: Updated the naming pattern to remove hyphens from the resource prefix:
- **Before**: `${resourcePrefix}acr${uniqueString(resourceGroup().id)}`
- **After**: `${replace(resourcePrefix, '-', '')}acr${uniqueString(resourceGroup().id)}`

**Result**: Names like `mcp-toolkit` become `mcptoolkit`, producing valid ACR names like `mcptoolkitacrlho6nfkzly22o`.

### 2. Owner Tag Made Optional
**Problem**: The `ownerTag` parameter was mandatory, causing deployment failures in subscriptions without Azure Policy requirements.

**Solution**: Made the owner tag optional with a sensible default:
- Added default value: `mcp-toolkit-user`
- Updated description to indicate it's optional
- Updated parameter template with default value

## Azure Container Registry Naming Rules
- Must contain **only alphanumeric characters** (a-z, A-Z, 0-9)
- Must be between **5 and 50 characters**
- Must be globally unique within Azure
- **No hyphens, underscores, or special characters allowed**

## Files Modified
- `infrastructure/deploy-all-resources.bicep` - Updated naming pattern and made ownerTag optional
- `infrastructure/deploy-all-resources.json` - ARM template with fixes applied
- `infrastructure/deploy-all-resources.parameters.template.json` - Added default ownerTag value

## Testing
- All unit tests continue to pass
- Template compiles successfully with warnings only about conditional OpenAI resources
- Naming validation ensures ACR names are compliant with Azure requirements