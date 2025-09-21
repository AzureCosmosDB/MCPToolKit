# Quick validation script for MCP Toolkit
# This script validates your setup before deployment

Write-Host "🔍 MCP Toolkit Pre-deployment Validation" -ForegroundColor Green
Write-Host "═══════════════════════════════════════════════════════════════" -ForegroundColor Green

$errors = @()
$warnings = @()

# Check 1: Azure CLI
Write-Host "1️⃣ Checking Azure CLI..." -ForegroundColor Blue
try {
    $azVersion = az --version 2>$null
    if ($azVersion) {
        Write-Host "   ✅ Azure CLI is installed" -ForegroundColor Green
        
        # Check if logged in
        try {
            $account = az account show 2>$null | ConvertFrom-Json
            if ($account) {
                Write-Host "   ✅ Logged in as: $($account.user.name)" -ForegroundColor Green
                Write-Host "   📋 Subscription: $($account.name)" -ForegroundColor Cyan
            } else {
                $errors += "Azure CLI: Not logged in. Run 'az login'"
            }
        } catch {
            $errors += "Azure CLI: Not logged in. Run 'az login'"
        }
    } else {
        $errors += "Azure CLI: Not installed or not in PATH"
    }
} catch {
    $errors += "Azure CLI: Error checking installation"
}

# Check 2: Docker
Write-Host "2️⃣ Checking Docker..." -ForegroundColor Blue
try {
    $dockerVersion = docker --version 2>$null
    if ($dockerVersion) {
        Write-Host "   ✅ Docker is installed: $dockerVersion" -ForegroundColor Green
        
        # Check if Docker daemon is running
        try {
            docker info 2>$null | Out-Null
            Write-Host "   ✅ Docker daemon is running" -ForegroundColor Green
        } catch {
            $warnings += "Docker: Docker Desktop may not be running"
            Write-Host "   ⚠️ Docker Desktop may not be running" -ForegroundColor Yellow
        }
    } else {
        $errors += "Docker: Not installed or not in PATH"
    }
} catch {
    $errors += "Docker: Error checking installation"
}

# Check 3: Project files
Write-Host "3️⃣ Checking project files..." -ForegroundColor Blue
$requiredFiles = @(
    "Dockerfile",
    "docker-compose.yml", 
    "src/AzureCosmosDB.MCP.Toolkit/AzureCosmosDB.MCP.Toolkit.csproj",
    "infrastructure/main.bicep",
    "scripts/deploy.ps1"
)

foreach ($file in $requiredFiles) {
    if (Test-Path $file) {
        Write-Host "   ✅ $file exists" -ForegroundColor Green
    } else {
        $errors += "Missing required file: $file"
    }
}

# Check 4: .NET SDK
Write-Host "4️⃣ Checking .NET SDK..." -ForegroundColor Blue
try {
    $dotnetVersion = dotnet --version 2>$null
    if ($dotnetVersion -and $dotnetVersion.StartsWith("9.")) {
        Write-Host "   ✅ .NET 9.0 SDK is installed: $dotnetVersion" -ForegroundColor Green
    } elseif ($dotnetVersion) {
        $warnings += ".NET: Version $dotnetVersion detected, but .NET 9.0 is recommended"
        Write-Host "   ⚠️ .NET version: $dotnetVersion (.NET 9.0 recommended)" -ForegroundColor Yellow
    } else {
        $warnings += ".NET SDK: Not found or not in PATH"
    }
} catch {
    $warnings += ".NET SDK: Error checking installation"
}

# Check 5: PowerShell execution policy
Write-Host "5️⃣ Checking PowerShell execution policy..." -ForegroundColor Blue
$executionPolicy = Get-ExecutionPolicy
if ($executionPolicy -eq "Restricted") {
    $warnings += "PowerShell execution policy is Restricted. May need to run: Set-ExecutionPolicy RemoteSigned -Scope CurrentUser"
    Write-Host "   ⚠️ Execution policy: $executionPolicy" -ForegroundColor Yellow
} else {
    Write-Host "   ✅ Execution policy: $executionPolicy" -ForegroundColor Green
}

# Summary
Write-Host ""
Write-Host "📊 Validation Summary" -ForegroundColor Green
Write-Host "═══════════════════════════════════════════════════════════════" -ForegroundColor Green

if ($errors.Count -eq 0 -and $warnings.Count -eq 0) {
    Write-Host "🎉 All checks passed! You're ready to deploy." -ForegroundColor Green
    Write-Host ""
    Write-Host "📋 Next Steps:" -ForegroundColor Blue
    Write-Host "1. Set up Azure resources (Cosmos DB + OpenAI)" -ForegroundColor White
    Write-Host "2. Run: .\scripts\test-deployment.ps1" -ForegroundColor White
    Write-Host "3. Or test locally first: docker-compose up -d" -ForegroundColor White
} else {
    if ($errors.Count -gt 0) {
        Write-Host "❌ Errors found (must fix before deployment):" -ForegroundColor Red
        $errors | ForEach-Object { Write-Host "   • $_" -ForegroundColor Red }
        Write-Host ""
    }
    
    if ($warnings.Count -gt 0) {
        Write-Host "⚠️ Warnings (recommended to address):" -ForegroundColor Yellow
        $warnings | ForEach-Object { Write-Host "   • $_" -ForegroundColor Yellow }
        Write-Host ""
    }
    
    Write-Host "💡 Fix the issues above and run this script again." -ForegroundColor Cyan
}

Write-Host ""
Write-Host "🔗 Helpful Links:" -ForegroundColor Blue
Write-Host "• Azure CLI: https://docs.microsoft.com/en-us/cli/azure/install-azure-cli" -ForegroundColor Gray
Write-Host "• Docker Desktop: https://www.docker.com/products/docker-desktop" -ForegroundColor Gray
Write-Host "• .NET 9.0 SDK: https://dotnet.microsoft.com/download/dotnet/9.0" -ForegroundColor Gray
Write-Host "• Testing Guide: See TESTING_GUIDE.md in this repository" -ForegroundColor Gray