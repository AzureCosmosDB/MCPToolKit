#!/bin/bash

# Script to download and trust the Cosmos DB emulator certificate
# This helps with SSL connection issues when connecting from outside the container

echo "🔐 Setting up Cosmos DB Emulator Certificate..."

# Check if emulator is running
if ! curl -k -s https://localhost:8081/_explorer/emulator.pem > /dev/null; then
    echo "❌ Cosmos DB emulator is not running on https://localhost:8081"
    echo "   Please start the emulator with: docker-compose up -d cosmos-emulator"
    exit 1
fi

# Download the certificate
echo "📥 Downloading emulator certificate..."
curl -k https://localhost:8081/_explorer/emulator.pem > cosmos-emulator.crt

if [ $? -eq 0 ]; then
    echo "✅ Certificate downloaded: cosmos-emulator.crt"
    echo ""
    echo "🔧 To trust this certificate:"
    echo ""
    
    if [[ "$OSTYPE" == "darwin"* ]]; then
        echo "macOS:"
        echo "  sudo security add-trusted-cert -d -r trustRoot -k /Library/Keychains/System.keychain cosmos-emulator.crt"
    elif [[ "$OSTYPE" == "linux-gnu"* ]]; then
        echo "Linux:"
        echo "  sudo cp cosmos-emulator.crt /usr/local/share/ca-certificates/"
        echo "  sudo update-ca-certificates"
    else
        echo "Windows (run as Administrator in PowerShell):"
        echo "  Import-Certificate -FilePath cosmos-emulator.crt -CertStoreLocation Cert:\\LocalMachine\\Root"
    fi
    
    echo ""
    echo "⚠️  Note: For Docker Compose, SSL verification is disabled by default"
    echo "   The certificate is only needed if connecting from outside the container network"
else
    echo "❌ Failed to download certificate"
    exit 1
fi