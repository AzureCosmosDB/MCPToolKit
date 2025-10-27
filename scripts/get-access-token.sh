#!/bin/bash

# Get Azure AD access token for Azure Cosmos DB MCP Server
# Usage: ./get-access-token.sh [CLIENT_ID] [TENANT_ID]

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
GRAY='\033[0;37m'
NC='\033[0m'

echo_info() {
    echo -e "${GREEN}[INFO]${NC} $1"
}

echo_warn() {
    echo -e "${YELLOW}[WARN]${NC} $1"
}

echo_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

echo_cyan() {
    echo -e "${CYAN}$1${NC}"
}

echo_gray() {
    echo -e "${GRAY}$1${NC}"
}

# Get script directory
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DEPLOYMENT_INFO_FILE="$SCRIPT_DIR/deployment-info.json"

# Function to get token with client ID
get_token_with_client_id() {
    local client_id="$1"
    local tenant_id="$2"
    local resource="api://$client_id"
    
    echo_info "🔐 Getting Azure AD Access Token..."
    echo_gray "Client ID: $client_id"
    echo_gray "Resource: $resource"
    
    if [ -n "$tenant_id" ]; then
        echo_gray "Tenant ID: $tenant_id"
        ACCESS_TOKEN=$(az account get-access-token --resource "$resource" --tenant "$tenant_id" --query "accessToken" --output tsv)
    else
        ACCESS_TOKEN=$(az account get-access-token --resource "$resource" --query "accessToken" --output tsv)
    fi
    
    if [ -z "$ACCESS_TOKEN" ]; then
        echo_error "Failed to get access token. Make sure you're logged in with 'az login'"
        exit 1
    fi
    
    echo_info "✅ Token retrieved successfully!"
    echo ""
    echo_cyan "Access Token:"
    echo "$ACCESS_TOKEN"
    echo ""
    echo_cyan "💡 Usage Examples:"
    echo_gray "# Test MCP tools list:"
    echo_gray "curl -X POST 'https://your-app.azurecontainerapps.io/mcp' \\"
    echo_gray "  -H 'Authorization: Bearer $ACCESS_TOKEN' \\"
    echo_gray "  -H 'Content-Type: application/json' \\"
    echo_gray "  -d '{\"jsonrpc\":\"2.0\",\"method\":\"tools/list\",\"id\":1}'"
    echo ""
    echo_gray "# Set as environment variable:"
    echo_gray "export ACCESS_TOKEN='$ACCESS_TOKEN'"
    
    # Export for current session
    export ACCESS_TOKEN="$ACCESS_TOKEN"
    echo_info "✅ Token also set as \$ACCESS_TOKEN for this session"
}

# Function to get token from deployment info
get_token_from_deployment() {
    if [ ! -f "$DEPLOYMENT_INFO_FILE" ]; then
        echo_error "Deployment info file not found: $DEPLOYMENT_INFO_FILE"
        echo ""
        echo_warn "🔧 To create this file, run one of these deployment scripts:"
        echo_gray "• ./scripts/deploy-cosmos-mcp-server.sh"
        echo_gray "• ./scripts/Deploy-CosmosMcpServer.ps1"
        exit 1
    fi
    
    echo_info "🔍 Reading deployment information..."
    
    # Check if jq is available
    if ! command -v jq &> /dev/null; then
        echo_error "jq is required but not installed. Please install jq."
        exit 1
    fi
    
    # Extract values from deployment info
    CLIENT_ID=$(jq -r '.ENTRA_APP_CLIENT_ID // empty' "$DEPLOYMENT_INFO_FILE")
    SERVER_URL=$(jq -r '.MCP_SERVER_URI // empty' "$DEPLOYMENT_INFO_FILE")
    TENANT_ID=$(jq -r '.AZURE_TENANT_ID // empty' "$DEPLOYMENT_INFO_FILE")
    
    if [ -z "$CLIENT_ID" ]; then
        echo_error "ENTRA_APP_CLIENT_ID not found in deployment info"
        exit 1
    fi
    
    echo_info "✅ Deployment info loaded"
    echo_gray "Server URL: $SERVER_URL"
    echo_gray "Client ID: $CLIENT_ID"
    if [ -n "$TENANT_ID" ]; then
        echo_gray "Tenant ID: $TENANT_ID"
    fi
    echo ""
    
    # Get the token
    get_token_with_client_id "$CLIENT_ID" "$TENANT_ID"
    
    if [ -n "$SERVER_URL" ] && [ -n "$ACCESS_TOKEN" ]; then
        echo ""
        echo_cyan "🌐 Ready to test with your deployed server:"
        echo_gray "curl -X POST '$SERVER_URL/mcp' \\"
        echo_gray "  -H 'Authorization: Bearer $ACCESS_TOKEN' \\"
        echo_gray "  -H 'Content-Type: application/json' \\"
        echo_gray "  -d '{\"jsonrpc\":\"2.0\",\"method\":\"tools/list\",\"id\":1}'"
    fi
}

# Main logic
if [ $# -eq 0 ]; then
    # No arguments - try to read from deployment info
    get_token_from_deployment
elif [ $# -eq 1 ]; then
    # One argument - client ID provided
    get_token_with_client_id "$1" ""
elif [ $# -eq 2 ]; then
    # Two arguments - client ID and tenant ID provided
    get_token_with_client_id "$1" "$2"
else
    echo_error "Usage: $0 [CLIENT_ID] [TENANT_ID]"
    echo_gray "Examples:"
    echo_gray "  $0                                    # Read from deployment-info.json"
    echo_gray "  $0 12345678-1234-1234-1234-123456789abc  # Specify client ID"
    echo_gray "  $0 CLIENT_ID TENANT_ID                   # Specify both IDs"
    exit 1
fi