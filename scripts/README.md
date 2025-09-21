# Scripts Directory

This directory contains utility scripts for deploying and managing the Azure Cosmos DB MCP Toolkit.

## 🚀 Deployment Scripts

### `Deploy-Complete.ps1` (Windows PowerShell)
**Purpose**: Complete Azure infrastructure deployment with all resources  
**What it does**:
- Deploys the full `infrastructure/deploy-all-resources.bicep` template
- Creates Cosmos DB, Azure OpenAI, Container Registry, Container Apps
- Configures all RBAC permissions automatically
- Builds and deploys the Docker container
- Provides deployment summary and health checks

**Usage**:
```powershell
.\scripts\Deploy-Complete.ps1 `
    -ResourceGroupName "rg-mcp-toolkit" `
    -Location "East US" `
    -PrincipalId "your-user-object-id" `
    -PrincipalType "User"
```

### `deploy-complete.sh` (Linux/macOS Bash)
**Purpose**: Cross-platform equivalent of Deploy-Complete.ps1  
**Usage**:
```bash
export RESOURCE_GROUP_NAME="rg-mcp-toolkit"
export LOCATION="East US"  
export PRINCIPAL_ID="your-user-object-id"
./scripts/deploy-complete.sh
```

## 🔍 Validation Scripts

### `validate-setup.ps1` (Windows PowerShell)
**Purpose**: Pre-deployment environment validation  
**What it checks**:
- Azure CLI installation and login status
- Docker installation and status
- Required permissions and subscriptions
- Network connectivity to Azure

**Usage**:
```powershell
.\scripts\validate-setup.ps1
```

## 🔐 Development Scripts

### `Setup-CosmosCert.ps1` (Windows PowerShell)
**Purpose**: Download and install Cosmos DB emulator certificate  
**When to use**: Docker Compose local development with SSL connections  
**Usage**:
```powershell
.\scripts\Setup-CosmosCert.ps1
```

### `setup-cosmos-cert.sh` (Linux/macOS Bash)
**Purpose**: Cross-platform certificate setup for Cosmos emulator  
**Usage**:
```bash
./scripts/setup-cosmos-cert.sh
```

## 📋 Alternative Deployment Methods

If you don't want to use these scripts, you can deploy using:

1. **Azure Portal Deploy Button**: Use the "Deploy to Azure" button in README.md
2. **Direct Bicep**: Deploy `infrastructure/deploy-all-resources.bicep` manually
3. **GitHub Actions**: Use the automated workflow in `.github/workflows/deploy-complete.yml`
4. **Azure CLI**: Deploy the Bicep template directly with `az deployment group create`

## 🗂️ What Was Removed

The following scripts were removed as they were redundant with the Bicep templates:
- `deploy.ps1` - Partial deployment (superseded by Deploy-Complete.ps1)
- `post-deploy.ps1` - Image building (integrated into Deploy-Complete.ps1)  
- `quick-validate.ps1` - Basic validation (superseded by validate-setup.ps1)
- `test-deployment.ps1` - Incomplete testing (superseded by GitHub Actions)

This streamlined approach focuses on essential scripts that provide unique value beyond what the Bicep templates and GitHub Actions workflows already provide.