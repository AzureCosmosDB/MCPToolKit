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

Write-Host "Building image..." -ForegroundColor Yellow
docker build -t $ImageName .
if ($LASTEXITCODE -ne 0) { Write-Error "Build failed" }

# Push image
Write-Host "Pushing image..." -ForegroundColor Yellow
docker push $ImageName
if ($LASTEXITCODE -ne 0) { Write-Error "Push failed" }

# Simple approach - just update image and let the existing managed identity handle auth
Write-Host "Updating Container App with new image..." -ForegroundColor Yellow
$RevisionSuffix = "v" + (Get-Date -Format "MMdd-HHmm")

# Since we already have managed identity with AcrPull role, try simple update first
az containerapp update `
    --name $ContainerAppName `
    --resource-group $ResourceGroup `
    --image $ImageName `
    --revision-suffix $RevisionSuffix

# If that fails, enable ACR admin and use basic auth
if ($LASTEXITCODE -ne 0) {
    Write-Host "Simple update failed, trying with ACR admin credentials..." -ForegroundColor Yellow
    
    # Enable admin user on ACR
    az acr update --name $RegistryName --admin-enabled true
    
    # Wait for admin to be enabled and try again
    Start-Sleep -Seconds 15
    
    # Try update again - the Container App should now be able to authenticate
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