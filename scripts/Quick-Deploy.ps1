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

# Update Container App
Write-Host "Updating Container App..." -ForegroundColor Yellow
$RevisionSuffix = "v" + (Get-Date -Format "MMdd-HHmm")

az containerapp update --name $ContainerAppName --resource-group $ResourceGroup --image $ImageName --revision-suffix $RevisionSuffix
if ($LASTEXITCODE -ne 0) { Write-Error "Update failed" }

# Get URL
$AppUrl = az containerapp show --name $ContainerAppName --resource-group $ResourceGroup --query "properties.configuration.ingress.fqdn" --output tsv

Write-Host "Deployment completed successfully!" -ForegroundColor Green
Write-Host "App URL: https://$AppUrl" -ForegroundColor Cyan
Write-Host "Health: https://$AppUrl/api/health" -ForegroundColor Cyan

# Test deployment
Write-Host "Testing..." -ForegroundColor Yellow
Start-Sleep -Seconds 10
try {
    $Health = Invoke-RestMethod -Uri "https://$AppUrl/api/health" -TimeoutSec 30
    Write-Host "Health check passed: $($Health.status)" -ForegroundColor Green
} catch {
    Write-Host "Health check failed - app may still be starting" -ForegroundColor Yellow
}

Write-Host "🏗️ Building Docker image..." -ForegroundColor Yellow
docker build -t $FullImageName -t $LatestImageName .

if ($LASTEXITCODE -ne 0) {
    Write-Error "Docker build failed"
}

# Push Docker image
Write-Host "📤 Pushing Docker image to registry..." -ForegroundColor Yellow
docker push $FullImageName
docker push $LatestImageName

if ($LASTEXITCODE -ne 0) {
    Write-Error "Docker push failed"
}

# Update Container App
Write-Host "🔄 Updating Container App..." -ForegroundColor Yellow
$RevisionSuffix = "v" + (Get-Date -Format "MMdd-HHmm")

az containerapp update `
    --name $ContainerAppName `
    --resource-group $ResourceGroup `
    --image $FullImageName `
    --revision-suffix $RevisionSuffix

if ($LASTEXITCODE -ne 0) {
    Write-Error "Container App update failed"
}

# Get Container App URL
Write-Host "🌐 Getting Container App URL..." -ForegroundColor Yellow
$AppUrl = az containerapp show `
    --name $ContainerAppName `
    --resource-group $ResourceGroup `
    --query "properties.configuration.ingress.fqdn" `
    --output tsv

if ([string]::IsNullOrEmpty($AppUrl)) {
    Write-Error "Failed to get Container App URL"
}

Write-Host ""
Write-Host "🎉 Deployment completed successfully!" -ForegroundColor Green
Write-Host "📱 Your MCP Toolkit is available at: https://$AppUrl" -ForegroundColor Cyan
Write-Host "🏥 Health check: https://$AppUrl/api/health" -ForegroundColor Cyan
Write-Host "🔧 MCP endpoint: https://$AppUrl/mcp" -ForegroundColor Cyan

# Test the deployment
Write-Host ""
Write-Host "🔍 Testing deployment..." -ForegroundColor Yellow
Start-Sleep -Seconds 10

try {
    $HealthResponse = Invoke-RestMethod -Uri "https://$AppUrl/api/health" -Method Get -TimeoutSec 30
    Write-Host "✅ Health check passed!" -ForegroundColor Green
    Write-Host "   Status: $($HealthResponse.status)" -ForegroundColor Gray
    Write-Host "   Version: $($HealthResponse.version)" -ForegroundColor Gray
} catch {
    Write-Host "⚠️ Health check failed. The app might still be starting up." -ForegroundColor Yellow
    Write-Host "   Please check the URL manually in a few minutes." -ForegroundColor Gray
}

Write-Host ""
Write-Host "🎯 Next steps:" -ForegroundColor Cyan
Write-Host "   1. Open the UI at https://$AppUrl" -ForegroundColor Gray
Write-Host "   2. Test the MCP tools in the web interface" -ForegroundColor Gray
Write-Host "   3. Configure your Cosmos DB connection if needed" -ForegroundColor Gray