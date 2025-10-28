#!/usr/bin/env pwsh
<#
.SYNOPSIS
    Quick deployment script for MCP Toolkit
.DESCRIPTION
    Builds and deploys the MCP Toolkit application to an existing Azure Container App.
.PARAMETER ResourceGroup
    The Azure resource group name
.PARAMETER ContainerAppName
    The name of the Container App
.PARAMETER RegistryName
    The name of the Azure Container Registry
.EXAMPLE
    .\Quick-Deploy.ps1 -ResourceGroup "rg-name" -ContainerAppName "mcp-toolkit-app" -RegistryName "registryname"
#>

param(
    [Parameter(Mandatory=$true)]
    [string]$ResourceGroup,
    
    [Parameter(Mandatory=$true)]
    [string]$ContainerAppName,
    
    [Parameter(Mandatory=$true)]
    [string]$RegistryName
)

$ErrorActionPreference = "Stop"

Write-Host "MCP Toolkit Quick Deployment" -ForegroundColor Cyan

# Check prerequisites
try { az version | Out-Null } catch { Write-Error "Azure CLI not installed" }
try { docker version | Out-Null } catch { Write-Error "Docker not running" }

Write-Host "Prerequisites OK" -ForegroundColor Green

# Login to registry
Write-Host "Logging into registry..." -ForegroundColor Yellow
az acr login --name $RegistryName
if ($LASTEXITCODE -ne 0) { Write-Error "Registry login failed" }

# Build image
$ImageTag = (Get-Date -Format "yyyyMMdd-HHmmss")
$ImageName = "$RegistryName.azurecr.io/mcp-toolkit:$ImageTag"

Write-Host "Building image (this may take a few minutes)..." -ForegroundColor Yellow
Write-Host "Using no-cache to ensure fresh build with latest files..." -ForegroundColor Gray
docker build --no-cache -t $ImageName .
if ($LASTEXITCODE -ne 0) { Write-Error "Build failed" }

# Push image
Write-Host "Pushing image..." -ForegroundColor Yellow
docker push $ImageName
if ($LASTEXITCODE -ne 0) { Write-Error "Push failed" }

# Simple approach - just update image and let the existing managed identity handle auth
Write-Host "Updating Container App with new image..." -ForegroundColor Yellow
$RevisionSuffix = "v" + (Get-Date -Format "MMdd-HHmm")

# Get managed identity principal ID
$ManagedIdentityId = az containerapp show --name $ContainerAppName --resource-group $ResourceGroup --query "identity.principalId" --output tsv

if ($ManagedIdentityId) {
    Write-Host "Assigning AcrPull role to managed identity..." -ForegroundColor Yellow
    $RegistryId = az acr show --name $RegistryName --query "id" --output tsv
    az role assignment create --assignee $ManagedIdentityId --role "AcrPull" --scope $RegistryId 2>$null | Out-Null
    Write-Host "Waiting for role assignment to propagate..." -ForegroundColor Gray
    Start-Sleep -Seconds 15
}

# Try update with managed identity
az containerapp update `
    --name $ContainerAppName `
    --resource-group $ResourceGroup `
    --image $ImageName `
    --revision-suffix $RevisionSuffix

# If that fails, enable ACR admin and use basic auth
if ($LASTEXITCODE -ne 0) {
    Write-Host "Managed identity auth failed, trying with ACR admin credentials..." -ForegroundColor Yellow
    
    # Enable admin user on ACR
    az acr update --name $RegistryName --admin-enabled true
    
    # Get admin credentials
    $AdminUser = az acr credential show --name $RegistryName --query "username" --output tsv
    $AdminPassword = az acr credential show --name $RegistryName --query "passwords[0].value" --output tsv
    
    # Update with registry credentials
    az containerapp registry set `
        --name $ContainerAppName `
        --resource-group $ResourceGroup `
        --server "$RegistryName.azurecr.io" `
        --username $AdminUser `
        --password $AdminPassword
    
    # Try update again
    az containerapp update `
        --name $ContainerAppName `
        --resource-group $ResourceGroup `
        --image $ImageName `
        --revision-suffix $RevisionSuffix
        
    # Disable admin for security after deployment
    az acr update --name $RegistryName --admin-enabled false
}

if ($LASTEXITCODE -ne 0) { Write-Error "Container App update failed" }

# Get URL
$AppUrl = az containerapp show --name $ContainerAppName --resource-group $ResourceGroup --query "properties.configuration.ingress.fqdn" --output tsv

Write-Host ""
Write-Host "Deployment completed successfully!" -ForegroundColor Green
Write-Host "App URL: https://$AppUrl" -ForegroundColor Cyan
Write-Host "Health: https://$AppUrl/api/health" -ForegroundColor Cyan

# Test deployment
Write-Host ""
Write-Host "Testing deployment..." -ForegroundColor Yellow
Start-Sleep -Seconds 15

try {
    $Health = Invoke-RestMethod -Uri "https://$AppUrl/api/health" -TimeoutSec 30
    Write-Host "Health check passed: $($Health.status)" -ForegroundColor Green
    if ($Health.version) { Write-Host "Version: $($Health.version)" -ForegroundColor Gray }
} catch {
    Write-Host "Health check failed - app may still be starting" -ForegroundColor Yellow
    Write-Host "Please check the URL manually in a few minutes" -ForegroundColor Gray
}