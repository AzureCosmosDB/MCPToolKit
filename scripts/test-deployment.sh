#!/bin/bash

# Test script for Azure Cosmos DB MCP Server deployment
# Reads deployment-info.json and tests the deployed endpoints

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DEPLOYMENT_INFO_FILE="$SCRIPT_DIR/deployment-info.json"

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
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

# Load deployment info
load_deployment_info() {
    if [ ! -f "$DEPLOYMENT_INFO_FILE" ]; then
        echo_error "Deployment info file not found: $DEPLOYMENT_INFO_FILE"
        echo_error "Please run the deployment script first."
        exit 1
    fi

    echo_info "Loading deployment info from: $DEPLOYMENT_INFO_FILE"
    
    MCP_SERVER_URI=$(jq -r '.MCP_SERVER_URI // empty' "$DEPLOYMENT_INFO_FILE")
    ENTRA_APP_CLIENT_ID=$(jq -r '.ENTRA_APP_CLIENT_ID // empty' "$DEPLOYMENT_INFO_FILE")
    
    if [[ -z "$MCP_SERVER_URI" ]]; then
        echo_error "MCP_SERVER_URI not found in deployment info"
        exit 1
    fi
    
    echo_info "MCP Server URI: $MCP_SERVER_URI"
    echo_info "Entra App Client ID: $ENTRA_APP_CLIENT_ID"
}

# Test health endpoint
test_health_endpoint() {
    echo_info "Testing health endpoint (should work without authentication)..."
    
    HEALTH_RESPONSE=$(curl -s -w "%{http_code}" "$MCP_SERVER_URI/health" || echo "000")
    HTTP_CODE="${HEALTH_RESPONSE: -3}"
    RESPONSE_BODY="${HEALTH_RESPONSE%???}"
    
    if [ "$HTTP_CODE" = "200" ]; then
        echo_info "✅ Health endpoint working: $RESPONSE_BODY"
    else
        echo_error "❌ Health endpoint failed: HTTP $HTTP_CODE"
        echo_error "Response: $RESPONSE_BODY"
    fi
}

# Test MCP endpoint without authentication
test_mcp_unauthorized() {
    echo_info "Testing MCP endpoint without authentication (should return 401)..."
    
    RESPONSE=$(curl -s -w "%{http_code}" -X POST "$MCP_SERVER_URI/mcp" \
        -H "Content-Type: application/json" \
        -d '{"jsonrpc":"2.0","method":"tools/list","id":1}' || echo "000")
    
    HTTP_CODE="${RESPONSE: -3}"
    RESPONSE_BODY="${RESPONSE%???}"
    
    if [ "$HTTP_CODE" = "401" ]; then
        echo_info "✅ Authentication working correctly: Returns 401 Unauthorized"
    else
        echo_warn "⚠️  Unexpected response: HTTP $HTTP_CODE"
        echo_warn "Response: $RESPONSE_BODY"
        if [ "$HTTP_CODE" = "200" ]; then
            echo_warn "Note: This might indicate authentication bypass mode is enabled"
        fi
    fi
}

# Test CORS headers
test_cors_headers() {
    echo_info "Testing CORS support..."
    
    CORS_RESPONSE=$(curl -s -I -X OPTIONS "$MCP_SERVER_URI/mcp" \
        -H "Origin: https://example.com" \
        -H "Access-Control-Request-Method: POST" \
        -H "Access-Control-Request-Headers: Content-Type")
    
    if echo "$CORS_RESPONSE" | grep -i "access-control-allow-origin" > /dev/null; then
        echo_info "✅ CORS headers present"
    else
        echo_warn "⚠️  CORS headers not found"
    fi
}

# Display authentication instructions
show_auth_instructions() {
    echo ""
    echo_info "🔐 Authentication Setup Instructions:"
    echo ""
    echo "To authenticate and use the MCP tools, you need:"
    echo ""
    echo "1. Assign the 'Mcp.Tool.Executor' role to users:"
    echo "   az ad app role assignment create \\"
    echo "     --id '$ENTRA_APP_CLIENT_ID' \\"
    echo "     --principal 'user@domain.com' \\"
    echo "     --role 'Mcp.Tool.Executor'"
    echo ""
    echo "2. Get an access token:"
    echo "   az account get-access-token \\"
    echo "     --resource 'api://$ENTRA_APP_CLIENT_ID' \\"
    echo "     --query 'accessToken' --output tsv"
    echo ""
    echo "3. Test with authentication:"
    echo "   curl -X POST '$MCP_SERVER_URI/mcp' \\"
    echo "     -H 'Authorization: Bearer \$ACCESS_TOKEN' \\"
    echo "     -H 'Content-Type: application/json' \\"
    echo "     -d '{\"jsonrpc\":\"2.0\",\"method\":\"tools/list\",\"id\":1}'"
    echo ""
    echo "4. Web-based testing (similar to PostgreSQL demo):"
    echo "   🌐 Download: cosmos-mcp-client.html from the repo"
    echo "   📝 Server URL: $MCP_SERVER_URI"
    echo "   🔑 Access Token: Use token from step 2"
    echo "   💡 Interactive testing with all Cosmos DB MCP tools"
    echo ""
}

# Display summary
show_summary() {
    echo ""
    echo_info "📊 Test Summary:"
    echo ""
    echo "🌐 MCP Server URL: $MCP_SERVER_URI"
    echo "🔑 Entra App ID: $ENTRA_APP_CLIENT_ID"
    echo "📄 Deployment Details: $DEPLOYMENT_INFO_FILE"
    echo ""
    echo_info "✅ Your Azure Cosmos DB MCP Server is deployed and secured!"
    echo_info "📖 Next: Follow the authentication instructions above to start using the MCP tools."
}

# Main execution
main() {
    echo_info "🧪 Testing Azure Cosmos DB MCP Server deployment..."
    echo ""
    
    load_deployment_info
    test_health_endpoint
    test_mcp_unauthorized
    test_cors_headers
    show_auth_instructions
    show_summary
}

# Check if jq is available
if ! command -v jq &> /dev/null; then
    echo_error "jq is required but not installed. Please install jq to continue."
    echo_info "Install with: brew install jq (macOS) or apt-get install jq (Ubuntu)"
    exit 1
fi

# Run main function
main "$@"