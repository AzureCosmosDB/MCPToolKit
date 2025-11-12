<#
.SYNOPSIS
    Assigns the Mcp.Tool.Executor role to the current user.

.DESCRIPTION
    This script assigns the Mcp.Tool.Executor role to the currently logged-in user.
    It's especially useful for Visual Studio subscriptions, personal Microsoft accounts,
    or when the deployment script's auto-assignment fails.
    
    The script uses the Graph API /me endpoint to get your Object ID, which works
    for all account types (corporate, personal, guest, Visual Studio subscriptions).

.PARAMETER DeploymentInfoPath
    Path to the deployment-info.json file. Defaults to deployment-info.json in the current directory.

.EXAMPLE
    .\Assign-Role-To-Current-User.ps1
    
.EXAMPLE
    .\Assign-Role-To-Current-User.ps1 -DeploymentInfoPath ".\scripts\deployment-info.json"

.NOTES
    Requires Azure CLI to be installed and authenticated.
    Run 'az login' before executing this script.
#>

param(
    [string]$DeploymentInfoPath = "deployment-info.json"
)

$ErrorActionPreference = "Stop"

# Colors
function Write-Success { param([string]$Message) Write-Host $Message -ForegroundColor Green }
function Write-Info { param([string]$Message) Write-Host $Message -ForegroundColor Cyan }
function Write-Warning { param([string]$Message) Write-Host $Message -ForegroundColor Yellow }
function Write-Error { param([string]$Message) Write-Host $Message -ForegroundColor Red }

Write-Info "=========================================="
Write-Info "Assign Role to Current User"
Write-Info "=========================================="
Write-Host ""

# Check if deployment-info.json exists
if (-not (Test-Path $DeploymentInfoPath)) {
    Write-Error "❌ ERROR: deployment-info.json not found at: $DeploymentInfoPath"
    Write-Host ""
    Write-Host "Please ensure you've run the deployment script first, or provide the correct path:"
    Write-Host "  .\Assign-Role-To-Current-User.ps1 -DeploymentInfoPath 'path\to\deployment-info.json'"
    exit 1
}

# Get current user's Object ID using Graph API /me endpoint
Write-Info "Getting your Object ID from Microsoft Graph..."
try {
    $meResult = az rest --method GET --url "https://graph.microsoft.com/v1.0/me" 2>&1
    if ($LASTEXITCODE -ne 0) {
        throw "Failed to get user info from Graph API"
    }
    $me = $meResult | ConvertFrom-Json
    Write-Success "✓ User: $($me.displayName) ($($me.userPrincipalName))"
    Write-Success "✓ Object ID: $($me.id)"
} catch {
    Write-Error "❌ ERROR: Failed to get your user information"
    Write-Host ""
    Write-Host "Please ensure you're logged in to Azure CLI:"
    Write-Host "  az login"
    exit 1
}

Write-Host ""

# Get deployment info
Write-Info "Reading deployment configuration..."
try {
    $deploymentInfo = Get-Content $DeploymentInfoPath | ConvertFrom-Json
    $spObjectId = $deploymentInfo.entraAppSpObjectId
    $clientId = $deploymentInfo.entraAppClientId
    Write-Success "✓ Service Principal Object ID: $spObjectId"
    Write-Success "✓ App Client ID: $clientId"
} catch {
    Write-Error "❌ ERROR: Failed to read deployment-info.json"
    Write-Host ""
    Write-Host "Error: $_"
    exit 1
}

Write-Host ""

# Assign role
Write-Info "Assigning 'Mcp.Tool.Executor' role..."
$appRoleId = "c6ae5dd5-ae87-48d8-8134-e07d93fdb962"

$body = @{
    principalId = $me.id
    resourceId = $spObjectId
    appRoleId = $appRoleId
} | ConvertTo-Json

$tempFile = "$env:TEMP\role-assignment-$([guid]::NewGuid()).json"
try {
    $body | Out-File -FilePath $tempFile -Encoding utf8 -NoNewline
    
    $result = az rest --method POST `
        --url "https://graph.microsoft.com/v1.0/servicePrincipals/$spObjectId/appRoleAssignedTo" `
        --headers "Content-Type=application/json" `
        --body "@$tempFile" 2>&1
    
    if ($LASTEXITCODE -eq 0) {
        Write-Host ""
        Write-Success "=========================================="
        Write-Success "✅ SUCCESS! Role assigned."
        Write-Success "=========================================="
    } elseif ($result -match "already exists") {
        Write-Host ""
        Write-Warning "=========================================="
        Write-Warning "✅ Role already assigned!"
        Write-Warning "=========================================="
    } else {
        Write-Host ""
        Write-Error "=========================================="
        Write-Error "❌ Error: $result"
        Write-Error "=========================================="
        exit 1
    }
} finally {
    if (Test-Path $tempFile) {
        Remove-Item $tempFile -Force
    }
}

Write-Host ""
Write-Info "Next steps:"
Write-Host "  1. Sign out from the web UI"
Write-Host "  2. Use Incognito/Private browser window"
Write-Host "  3. Sign in again to get a fresh token with the role"
Write-Host ""
Write-Info "Container App URL: $($deploymentInfo.containerAppUrl)"
Write-Host ""
