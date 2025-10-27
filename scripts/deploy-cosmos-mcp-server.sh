#!/bin/bash

set -e

# Configuration
RESOURCE_GROUP=""
LOCATION="eastus"
APP_NAME="mcp-demo-app"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Entra App Configuration
ENTRA_APP_NAME="Azure Cosmos DB MCP Toolkit API"

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

# Function to display usage
show_usage() {
    echo "Usage: $0 --resource-group <resource_group> [--location <location>]"
    echo ""
    echo "Arguments:"
    echo "  --resource-group <name>     Resource group name for the deployment"
    echo "  --location <location>       Azure region (default: eastus)"
    echo ""
    echo "Example:"
    echo "  ./deploy-cosmos-mcp-server.sh --resource-group \"rg-mcp-toolkit-demo\" --location \"eastus\""
    echo ""
}

# Parse command line arguments
parse_arguments() {
    while [[ $# -gt 0 ]]; do
        case $1 in
            --resource-group)
                RESOURCE_GROUP="$2"
                shift 2
                ;;
            --location)
                LOCATION="$2"
                shift 2
                ;;
            -h|--help)
                show_usage
                exit 0
                ;;
            *)
                echo_error "Unknown argument: $1"
                show_usage
                exit 1
                ;;
        esac
    done

    # Validate required arguments
    if [[ -z "$RESOURCE_GROUP" ]]; then
        echo_error "Resource group is required"
        show_usage
        exit 1
    fi

    echo_info "Using Resource Group: $RESOURCE_GROUP"
    echo_info "Using Location: $LOCATION"
}

# Check prerequisites
check_prerequisites() {
    echo_info "Checking prerequisites..."

    if ! command -v az &> /dev/null; then
        echo_error "Azure CLI is not installed. Please install it from https://docs.microsoft.com/en-us/cli/azure/install-azure-cli"
        exit 1
    fi

    if ! command -v jq &> /dev/null; then
        echo_error "jq is required but not installed. Please install jq to continue."
        echo_info "Install with: brew install jq (macOS) or apt-get install jq (Ubuntu)"
        exit 1
    fi

    if ! command -v docker &> /dev/null; then
        echo_error "Docker is required but not installed. Please install Docker to continue."
        exit 1
    fi

    echo_info "Prerequisites check passed"
}

# Login to Azure
login_azure() {
    echo_info "Checking Azure CLI login status..."

    if ! az account show &> /dev/null; then
        echo_info "Not logged in to Azure CLI. Running 'az login'..."
        az login
    fi

    # Get current subscription details
    SUBSCRIPTION_ID=$(az account show --query "id" --output tsv)
    TENANT_ID=$(az account show --query "tenantId" --output tsv)
    
    echo_info "Using subscription: $SUBSCRIPTION_ID"
    echo_info "Using tenant: $TENANT_ID"
}

# Create resource group
create_resource_group() {
    echo_info "Creating resource group: $RESOURCE_GROUP"

    az group create \
        --name "$RESOURCE_GROUP" \
        --location "$LOCATION" \
        --output table
}

# Deploy infrastructure using Bicep
deploy_infrastructure() {
    echo_info "Deploying Azure Container Apps and Entra App..."

    DEPLOYMENT_NAME="mcp-deployment-$(date +%s)"
    
    az deployment group create \
        --resource-group "$RESOURCE_GROUP" \
        --template-file "$SCRIPT_DIR/../infrastructure/main.bicep" \
        --name "$DEPLOYMENT_NAME" \
        --output table

    echo_info "Infrastructure deployment completed!"
}

# Get deployment outputs
get_deployment_outputs() {
    echo_info "Getting deployment outputs..."

    # Get the latest deployment
    DEPLOYMENT_NAME=$(az deployment group list \
        --resource-group "$RESOURCE_GROUP" \
        --query "[0].name" \
        --output tsv)

    # Get all outputs
    CONTAINER_REGISTRY=$(az deployment group show \
        --resource-group "$RESOURCE_GROUP" \
        --name "$DEPLOYMENT_NAME" \
        --query "properties.outputs.CONTAINER_REGISTRY_LOGIN_SERVER.value" \
        --output tsv)

    CONTAINER_APP_URL=$(az deployment group show \
        --resource-group "$RESOURCE_GROUP" \
        --name "$DEPLOYMENT_NAME" \
        --query "properties.outputs.CONTAINER_APP_URL.value" \
        --output tsv)

    ENTRA_APP_CLIENT_ID=$(az deployment group show \
        --resource-group "$RESOURCE_GROUP" \
        --name "$DEPLOYMENT_NAME" \
        --query "properties.outputs.ENTRA_APP_CLIENT_ID.value" \
        --output tsv)

    ENTRA_APP_OBJECT_ID=$(az deployment group show \
        --resource-group "$RESOURCE_GROUP" \
        --name "$DEPLOYMENT_NAME" \
        --query "properties.outputs.ENTRA_APP_OBJECT_ID.value" \
        --output tsv)

    ENTRA_APP_SP_OBJECT_ID=$(az deployment group show \
        --resource-group "$RESOURCE_GROUP" \
        --name "$DEPLOYMENT_NAME" \
        --query "properties.outputs.ENTRA_APP_SERVICE_PRINCIPAL_ID.value" \
        --output tsv)

    ENTRA_APP_ROLE_ID=$(az deployment group show \
        --resource-group "$RESOURCE_GROUP" \
        --name "$DEPLOYMENT_NAME" \
        --query "properties.outputs.ENTRA_APP_ROLE_ID.value" \
        --output tsv)

    CONTAINER_APP_PRINCIPAL_ID=$(az deployment group show \
        --resource-group "$RESOURCE_GROUP" \
        --name "$DEPLOYMENT_NAME" \
        --query "properties.outputs.CONTAINER_APP_PRINCIPAL_ID.value" \
        --output tsv)

    echo_info "Container Registry: $CONTAINER_REGISTRY"
    echo_info "Container App URL: $CONTAINER_APP_URL"
    echo_info "Entra App Client ID: $ENTRA_APP_CLIENT_ID"
}

# Build and push container image
build_and_push_image() {
    echo_info "Building and pushing container image..."

    # Get the container registry name (without .azurecr.io)
    REGISTRY_NAME=$(echo "$CONTAINER_REGISTRY" | cut -d'.' -f1)
    
    # Build and push using ACR build (automatically handles authentication)
    az acr build \
        --registry "$REGISTRY_NAME" \
        --image "mcp-toolkit:latest" \
        --file "$SCRIPT_DIR/../Dockerfile" \
        "$SCRIPT_DIR/.."

    echo_info "Container image built and pushed successfully!"
}

# Update container app with the new image
update_container_app() {
    echo_info "Updating container app with new image..."

    az containerapp update \
        --name "$APP_NAME" \
        --resource-group "$RESOURCE_GROUP" \
        --image "$CONTAINER_REGISTRY/mcp-toolkit:latest"

    echo_info "Container app updated successfully!"
}

# Show container logs
show_container_logs() {
    echo_info "Waiting 10 seconds for Azure Container App to initialize then fetching logs..."
    sleep 10

    echo ""
    echo_info "Azure Container App logs:"
    echo "Begin_Azure_Container_App_Logs ---->"
    if az containerapp logs show \
        --name "$APP_NAME" \
        --resource-group "$RESOURCE_GROUP" \
        --tail 20 \
        --output table 2>/dev/null; then
        echo "<---- End_Azure_Container_App_Logs"
        echo ""
    else
        echo_warn "Could not retrieve logs. The Azure Container App might still be starting up."
        echo_info "Check logs later with: az containerapp logs show --name $APP_NAME --resource-group $RESOURCE_GROUP --tail 20"
    fi
}

# Display deployment summary
show_deployment_summary() {
    echo_info "Deployment Summary:"
    
    # Create JSON summary
    SUMMARY_JSON=$(jq -n \
        --arg mcp_server_uri "$CONTAINER_APP_URL" \
        --arg entra_app_client_id "$ENTRA_APP_CLIENT_ID" \
        --arg entra_app_object_id "$ENTRA_APP_OBJECT_ID" \
        --arg entra_app_sp_object_id "$ENTRA_APP_SP_OBJECT_ID" \
        --arg entra_app_role_id "$ENTRA_APP_ROLE_ID" \
        --arg aca_mi_principal_id "$CONTAINER_APP_PRINCIPAL_ID" \
        --arg resource_group "$RESOURCE_GROUP" \
        --arg subscription_id "$SUBSCRIPTION_ID" \
        --arg tenant_id "$TENANT_ID" \
        --arg location "$LOCATION" \
        '{
            "MCP_SERVER_URI": $mcp_server_uri,
            "ENTRA_APP_CLIENT_ID": $entra_app_client_id,
            "ENTRA_APP_OBJECT_ID": $entra_app_object_id,
            "ENTRA_APP_SP_OBJECT_ID": $entra_app_sp_object_id,
            "ENTRA_APP_ROLE_VALUE": "Mcp.Tool.Executor",
            "ENTRA_APP_ROLE_ID": $entra_app_role_id,
            "ACA_MI_PRINCIPAL_ID": $aca_mi_principal_id,
            "RESOURCE_GROUP": $resource_group,
            "SUBSCRIPTION_ID": $subscription_id,
            "TENANT_ID": $tenant_id,
            "LOCATION": $location
        }')
    
    echo "$SUMMARY_JSON"
    
    DEPLOYMENT_INFO_FILE="$SCRIPT_DIR/deployment-info.json"
    echo "$SUMMARY_JSON" > "$DEPLOYMENT_INFO_FILE"
    echo_info "Deployment information written to: $DEPLOYMENT_INFO_FILE"
    
    echo ""
    echo_info "🎉 Deployment completed successfully!"
    echo_info "📱 Test your MCP server at: $CONTAINER_APP_URL"
    echo_info "🔐 Entra App Client ID: $ENTRA_APP_CLIENT_ID"
    echo_info "📄 Full deployment details: $DEPLOYMENT_INFO_FILE"
}

# Main function
main() {
    echo_info "Starting Azure Cosmos DB MCP Toolkit deployment..."

    parse_arguments "$@"
    check_prerequisites
    login_azure
    create_resource_group
    deploy_infrastructure
    get_deployment_outputs
    build_and_push_image
    update_container_app
    show_container_logs
    show_deployment_summary

    echo_info "Deployment completed successfully!"
}

# Run main function
main "$@"