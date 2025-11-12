<#
.SYNOPSIS
    Assigns the Mcp.Tool.Executor role to one or more users.

.DESCRIPTION
    This script assigns the Mcp.Tool.Executor role to specified users.
    You can provide user emails as a comma-separated list or interactively.
    
    The script automatically handles both corporate accounts and accounts
    that can't be found by standard lookup (Visual Studio subscriptions, etc.).

.PARAMETER UserEmails
    Comma-separated list of user emails to assign roles to.
    Example: "user1@company.com,user2@company.com"

.PARAMETER DeploymentInfoPath
    Path to the deployment-info.json file. Defaults to deployment-info.json in the current directory.

.EXAMPLE
    .\Assign-Role-To-Users.ps1 -UserEmails "user1@company.com,user2@company.com"
    
.EXAMPLE
    .\Assign-Role-To-Users.ps1
    (Will prompt for user emails interactively)

.NOTES
    Requires Azure CLI to be installed and authenticated.
    Run 'az login' before executing this script.
#>

param(
    [string]$UserEmails = "",
    [string]$DeploymentInfoPath = "deployment-info.json"
)

$ErrorActionPreference = "Stop"

# Colors
function Write-Success { param([string]$Message) Write-Host $Message -ForegroundColor Green }
function Write-Info { param([string]$Message) Write-Host $Message -ForegroundColor Cyan }
function Write-Warning { param([string]$Message) Write-Host $Message -ForegroundColor Yellow }
function Write-Error { param([string]$Message) Write-Host $Message -ForegroundColor Red }

Write-Info "=========================================="
Write-Info "Assign Roles to Multiple Users"
Write-Info "=========================================="
Write-Host ""

# Check if deployment-info.json exists
if (-not (Test-Path $DeploymentInfoPath)) {
    Write-Error "❌ ERROR: deployment-info.json not found at: $DeploymentInfoPath"
    Write-Host ""
    Write-Host "Please ensure you've run the deployment script first, or provide the correct path:"
    Write-Host "  .\Assign-Role-To-Users.ps1 -DeploymentInfoPath 'path\to\deployment-info.json'"
    exit 1
}

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

# Get user emails
if ([string]::IsNullOrWhiteSpace($UserEmails)) {
    Write-Info "Enter user emails (comma-separated):"
    Write-Host "Example: user1@company.com, user2@company.com" -ForegroundColor Gray
    $UserEmails = Read-Host "User emails"
}

if ([string]::IsNullOrWhiteSpace($UserEmails)) {
    Write-Error "❌ ERROR: No user emails provided"
    exit 1
}

# Parse user emails
$users = $UserEmails -split ',' | ForEach-Object { $_.Trim() } | Where-Object { $_ -ne "" }

Write-Host ""
Write-Info "Users to assign roles to:"
$users | ForEach-Object { Write-Host "  • $_" -ForegroundColor Cyan }
Write-Host ""

$appRoleId = "c6ae5dd5-ae87-48d8-8134-e07d93fdb962"
$successCount = 0
$alreadyAssignedCount = 0
$failedCount = 0
$failedUsers = @()

foreach ($userEmail in $users) {
    Write-Info "Processing: $userEmail"
    
    # Try standard lookup first
    $userObjectId = az ad user show --id $userEmail --query "id" -o tsv 2>$null
    
    # If standard lookup fails, try searching by display name
    if (-not $userObjectId -or $userObjectId -eq "null" -or $userObjectId -eq "") {
        Write-Warning "  ⚠ Standard lookup failed, trying alternative methods..."
        
        # Try searching by display name (extract name from email)
        $displayName = $userEmail.Split('@')[0]
        $searchResult = az ad user list --query "[?contains(mail, '$userEmail') || contains(userPrincipalName, '$userEmail')].id" -o tsv 2>$null
        
        if ($searchResult -and $searchResult -ne "" -and $searchResult -ne "null") {
            $userObjectId = $searchResult
        }
    }
    
    if ($userObjectId -and $userObjectId -ne "null" -and $userObjectId -ne "") {
        Write-Success "  ✓ Found user: $userObjectId"
        
        # Assign role
        $body = @{
            principalId = $userObjectId
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
                Write-Success "  ✅ Role assigned to $userEmail"
                $successCount++
            } elseif ($result -match "already exists") {
                Write-Warning "  ℹ️ Role already assigned to $userEmail"
                $alreadyAssignedCount++
            } else {
                Write-Error "  ❌ Failed for $userEmail : $result"
                $failedCount++
                $failedUsers += $userEmail
            }
        } finally {
            if (Test-Path $tempFile) {
                Remove-Item $tempFile -Force
            }
        }
    } else {
        Write-Error "  ❌ User not found: $userEmail"
        Write-Host "     Try one of these methods:" -ForegroundColor Gray
        Write-Host "     1. Ask the user to run: .\Assign-Role-To-Current-User.ps1" -ForegroundColor Gray
        Write-Host "     2. Get their Object ID from Azure Portal and use manual assignment" -ForegroundColor Gray
        $failedCount++
        $failedUsers += $userEmail
    }
    
    Write-Host ""
}

# Summary
Write-Info "=========================================="
Write-Info "Summary"
Write-Info "=========================================="
Write-Host ""
Write-Success "✅ Successfully assigned: $successCount"
Write-Warning "ℹ️ Already assigned: $alreadyAssignedCount"
Write-Error "❌ Failed: $failedCount"

if ($failedUsers.Count -gt 0) {
    Write-Host ""
    Write-Error "Failed users:"
    $failedUsers | ForEach-Object { Write-Host "  • $_" -ForegroundColor Red }
    Write-Host ""
    Write-Info "For failed users, try:"
    Write-Host "  • Ask them to run: .\Assign-Role-To-Current-User.ps1"
    Write-Host "  • Use Azure Portal to assign manually"
}

Write-Host ""
Write-Info "Verify assignments:"
Write-Host "  az rest --method GET --url 'https://graph.microsoft.com/v1.0/servicePrincipals/$spObjectId/appRoleAssignedTo' --query \"value[?appRoleId=='$appRoleId'].{user:principalDisplayName, assigned:createdDateTime}\" -o table"
Write-Host ""
