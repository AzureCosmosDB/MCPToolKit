# Scripts Directory

This directory contains deployment and testing scripts for the Azure Cosmos DB MCP Toolkit.

## 🚀 Deployment Scripts

### `Deploy-CosmosMcpServer.ps1` (Windows PowerShell)

**Primary deployment script** for Windows that creates everything automatically:

- ✅ Entra ID App Registration with `Mcp.Tool.Executor` role
- ✅ Azure Container Apps infrastructure
- ✅ Azure Container Registry
- ✅ Complete authentication setup

**Usage:**
```powershell
.\Deploy-CosmosMcpServer.ps1 -ResourceGroup "rg-mcp-demo"
```

### `deploy-cosmos-mcp-server.sh` (Bash)

**Primary deployment script** for Linux/macOS with the same functionality.

**Usage:**
```bash
./deploy-cosmos-mcp-server.sh --resource-group "rg-mcp-demo"
```

## 🧪 Testing Scripts

### `test-deployment.sh`

Validates your deployment by testing:
- Health endpoints
- Authentication security (401 responses)
- MCP protocol endpoints

**Usage:**
```bash
./test-deployment.sh
```

### `validate-setup.ps1`

PowerShell validation script for Windows users.

## 🔑 Authentication Utilities

### `Get-AzureToken.ps1`

Gets Azure AD access tokens for testing your deployed MCP server.

**Usage:**
```powershell
.\Get-AzureToken.ps1
```

### `get-access-token.sh`

Bash version of the token utility for Linux/macOS.

**Usage:**
```bash
./get-access-token.sh
```

## 🛠️ Local Development

### `setup-cosmos-cert.sh` & `Setup-CosmosCert.ps1`

Sets up SSL certificates for local Cosmos DB emulator development.

### `Test-ManagedIdentityAuth.ps1` & `Test-MCPWithAAD.ps1`

Advanced testing scripts for managed identity and Azure AD authentication.

---

All scripts include comprehensive error handling and detailed output to guide you through the deployment and testing process.