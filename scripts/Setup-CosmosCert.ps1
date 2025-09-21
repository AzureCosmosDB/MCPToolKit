# PowerShell script to download and trust the Cosmos DB emulator certificate
# This helps with SSL connection issues when connecting from outside the container

Write-Host "🔐 Setting up Cosmos DB Emulator Certificate..." -ForegroundColor Green

# Check if emulator is running
try {
    $response = Invoke-WebRequest -Uri "https://localhost:8081/_explorer/emulator.pem" -SkipCertificateCheck -UseBasicParsing -ErrorAction Stop
    Write-Host "✅ Cosmos DB emulator is running" -ForegroundColor Green
} catch {
    Write-Host "❌ Cosmos DB emulator is not running on https://localhost:8081" -ForegroundColor Red
    Write-Host "   Please start the emulator with: docker-compose up -d cosmos-emulator" -ForegroundColor Yellow
    exit 1
}

# Download the certificate
Write-Host "📥 Downloading emulator certificate..." -ForegroundColor Blue
try {
    Invoke-WebRequest -Uri "https://localhost:8081/_explorer/emulator.pem" -OutFile "cosmos-emulator.crt" -SkipCertificateCheck -UseBasicParsing
    Write-Host "✅ Certificate downloaded: cosmos-emulator.crt" -ForegroundColor Green
} catch {
    Write-Host "❌ Failed to download certificate: $_" -ForegroundColor Red
    exit 1
}

# Try to import the certificate (requires admin privileges)
Write-Host ""
Write-Host "🔧 Attempting to import certificate to Trusted Root store..." -ForegroundColor Blue

try {
    # Check if running as administrator
    $currentPrincipal = New-Object Security.Principal.WindowsPrincipal([Security.Principal.WindowsIdentity]::GetCurrent())
    $isAdmin = $currentPrincipal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
    
    if ($isAdmin) {
        Import-Certificate -FilePath "cosmos-emulator.crt" -CertStoreLocation "Cert:\LocalMachine\Root" -ErrorAction Stop
        Write-Host "✅ Certificate imported successfully!" -ForegroundColor Green
        Write-Host "   The Cosmos DB emulator certificate is now trusted system-wide." -ForegroundColor Green
    } else {
        Write-Host "⚠️  Not running as Administrator. Certificate downloaded but not imported." -ForegroundColor Yellow
        Write-Host ""
        Write-Host "To import the certificate manually:" -ForegroundColor Yellow
        Write-Host "1. Run PowerShell as Administrator" -ForegroundColor White
        Write-Host "2. Execute: Import-Certificate -FilePath cosmos-emulator.crt -CertStoreLocation Cert:\LocalMachine\Root" -ForegroundColor White
        Write-Host ""
        Write-Host "Or double-click cosmos-emulator.crt and install it to 'Trusted Root Certification Authorities'" -ForegroundColor White
    }
} catch {
    Write-Host "❌ Failed to import certificate: $_" -ForegroundColor Red
    Write-Host ""
    Write-Host "Manual import instructions:" -ForegroundColor Yellow
    Write-Host "1. Run PowerShell as Administrator" -ForegroundColor White
    Write-Host "2. Execute: Import-Certificate -FilePath cosmos-emulator.crt -CertStoreLocation Cert:\LocalMachine\Root" -ForegroundColor White
}

Write-Host ""
Write-Host "⚠️  Note: For Docker Compose, SSL verification is disabled by default" -ForegroundColor Cyan
Write-Host "   The certificate is only needed if connecting from outside the container network" -ForegroundColor Cyan