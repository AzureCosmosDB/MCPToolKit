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

# Configure Container App registry credentials
Write-Host "Configuring registry access..." -ForegroundColor Yellow
$RegistryServer = "$RegistryName.azurecr.io"

# Get the managed identity for the Container App Environment
$ContainerAppEnv = az containerapp show --name $ContainerAppName --resource-group $ResourceGroup --query "properties.environmentId" --output tsv
$EnvName = Split-Path $ContainerAppEnv -Leaf

# Enable admin user on ACR temporarily for Container Apps
az acr update --name $RegistryName --admin-enabled true
if ($LASTEXITCODE -ne 0) { Write-Warning "Failed to enable ACR admin - trying managed identity approach" }

# Get ACR credentials
$AcrUsername = az acr credential show --name $RegistryName --query "username" --output tsv
$AcrPassword = az acr credential show --name $RegistryName --query "passwords[0].value" --output tsv

# Update Container App with registry credentials
Write-Host "Updating Container App with registry credentials..." -ForegroundColor Yellow
$RevisionSuffix = "v" + (Get-Date -Format "MMdd-HHmm")

az containerapp update `
    --name $ContainerAppName `
    --resource-group $ResourceGroup `
    --image $ImageName `
    --registry-server $RegistryServer `
    --registry-username $AcrUsername `
    --registry-password $AcrPassword `
    --revision-suffix $RevisionSuffix

if ($LASTEXITCODE -ne 0) { Write-Error "Container App update failed" }

# Disable admin user after deployment for security
Write-Host "Securing registry..." -ForegroundColor Yellow
az acr update --name $RegistryName --admin-enabled false

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