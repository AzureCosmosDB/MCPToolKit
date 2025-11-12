<#
.SYNOPSIS
    Verifies role assignments for the Azure Cosmos DB MCP Toolkit.

.DESCRIPTION
    This script lists all users who have been assigned the Mcp.Tool.Executor role
    for the Azure Cosmos DB MCP Toolkit application.

.PARAMETER DeploymentInfoPath
    Path to the deployment-info.json file. Defaults to deployment-info.json in the current directory.

.EXAMPLE
    .\Verify-Role-Assignments.ps1
    
.EXAMPLE
    .\Verify-Role-Assignments.ps1 -DeploymentInfoPath ".\scripts\deployment-info.json"

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
Write-Info "Verify Role Assignments"
Write-Info "=========================================="
Write-Host ""

# Check if deployment-info.json exists
if (-not (Test-Path $DeploymentInfoPath)) {
    Write-Error "❌ ERROR: deployment-info.json not found at: $DeploymentInfoPath"
    Write-Host ""
    Write-Host "Please ensure you've run the deployment script first, or provide the correct path:"
    Write-Host "  .\Verify-Role-Assignments.ps1 -DeploymentInfoPath 'path\to\deployment-info.json'"
    exit 1
}

# Get deployment info
Write-Info "Reading deployment configuration..."
try {
    $deploymentInfo = Get-Content $DeploymentInfoPath | ConvertFrom-Json
    $spObjectId = $deploymentInfo.entraAppSpObjectId
    $clientId = $deploymentInfo.entraAppClientId
    $appName = "Azure Cosmos DB MCP Toolkit API"
    Write-Success "✓ Service Principal Object ID: $spObjectId"
    Write-Success "✓ App Client ID: $clientId"
} catch {
    Write-Error "❌ ERROR: Failed to read deployment-info.json"
    Write-Host ""
    Write-Host "Error: $_"
    exit 1
}

Write-Host ""

# Get role assignments
Write-Info "Fetching role assignments..."
$appRoleId = "c6ae5dd5-ae87-48d8-8134-e07d93fdb962"

try {
    $result = az rest --method GET `
        --url "https://graph.microsoft.com/v1.0/servicePrincipals/$spObjectId/appRoleAssignedTo" `
        --query "value[?appRoleId=='$appRoleId'].{User:principalDisplayName, Email:principalId, Assigned:createdDateTime}" 2>&1
    
    if ($LASTEXITCODE -ne 0) {
        throw "Failed to get role assignments: $result"
    }
    
    $assignments = $result | ConvertFrom-Json
    
    if ($assignments.Count -eq 0) {
        Write-Warning "⚠️ No users found with the 'Mcp.Tool.Executor' role"
        Write-Host ""
        Write-Info "To assign roles, run:"
        Write-Host "  .\Assign-Role-To-Current-User.ps1          # For yourself"
        Write-Host "  .\Assign-Role-To-Users.ps1                 # For other users"
    } else {
        Write-Success "✅ Found $($assignments.Count) user(s) with 'Mcp.Tool.Executor' role:"
        Write-Host ""
        
        $assignments | Format-Table -Property User, Assigned -AutoSize
        
        Write-Host ""
        Write-Info "Details:"
        foreach ($assignment in $assignments) {
            # Get user details
            $userId = $assignment.Email
            $userDetails = az rest --method GET --url "https://graph.microsoft.com/v1.0/users/$userId" 2>$null
            if ($LASTEXITCODE -eq 0 -and $userDetails) {
                $user = $userDetails | ConvertFrom-Json
                Write-Host "  • $($assignment.User)" -ForegroundColor Cyan
                Write-Host "    Email: $($user.mail)" -ForegroundColor Gray
                Write-Host "    UPN: $($user.userPrincipalName)" -ForegroundColor Gray
                Write-Host "    Object ID: $userId" -ForegroundColor Gray
                Write-Host "    Assigned: $($assignment.Assigned)" -ForegroundColor Gray
                Write-Host ""
            } else {
                Write-Host "  • $($assignment.User)" -ForegroundColor Cyan
                Write-Host "    Object ID: $userId" -ForegroundColor Gray
                Write-Host "    Assigned: $($assignment.Assigned)" -ForegroundColor Gray
                Write-Host ""
            }
        }
    }
} catch {
    Write-Error "❌ ERROR: Failed to get role assignments"
    Write-Host ""
    Write-Host "Error: $_"
    exit 1
}

Write-Info "=========================================="
Write-Info "Application Information"
Write-Info "=========================================="
Write-Host ""
Write-Host "App Name: $appName" -ForegroundColor Cyan
Write-Host "Client ID: $clientId" -ForegroundColor Cyan
Write-Host "Container App URL: $($deploymentInfo.containerAppUrl)" -ForegroundColor Cyan
Write-Host ""
