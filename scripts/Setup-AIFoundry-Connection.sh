#!/bin/bash

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
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

echo_header() {
    echo -e "${CYAN}$1${NC}"
}

# Function to display usage
print_usage() {
    echo "Usage: ./Setup-AIFoundry-Connection.sh --resource-group <rg> --ai-foundry-project-resource-id <resource-id> [--connection-name <name>]"
    echo ""
    echo "Create a managed identity connection in AI Foundry project for Azure Cosmos DB MCP Toolkit."
    echo ""
    echo "REQUIRED OPTIONS:"
    echo "  --resource-group <rg>"
    echo "                          Resource group where MCP Toolkit is deployed"
    echo "  --ai-foundry-project-resource-id <resource-id>"
    echo "                          Resource ID of AI Foundry project"
    echo "                          Format: /subscriptions/{sub}/resourceGroups/{rg}/providers/Microsoft.CognitiveServices/accounts/{account}/projects/{project}"
    echo ""
    echo "OPTIONAL:"
    echo "  --connection-name <name>"
    echo "                          Connection name (default: cosmos-mcp-toolkit)"
    echo ""
    echo "EXAMPLE:"
    echo "  ./Setup-AIFoundry-Connection.sh \\"
    echo "    --resource-group \"rg-cosmos-mcp\" \\"
    echo "    --ai-foundry-project-resource-id \"/subscriptions/12345.../projects/my-project\" \\"
    echo "    --connection-name \"cosmos-mcp\""
    echo ""
}

validate_ai_foundry_project_resource_id() {
    local resource_id="$1"
    if [[ ! "$resource_id" =~ ^/subscriptions/[a-fA-F0-9-]+/resourceGroups/[^/]+/providers/Microsoft\.CognitiveServices/accounts/[^/]+/projects/[^/]+$ ]]; then
        echo_error "Invalid AI Foundry project resource ID format"
        echo_error "Expected format: /subscriptions/{subscriptionId}/resourceGroups/{resourceGroup}/providers/Microsoft.CognitiveServices/accounts/{accountName}/projects/{projectName}"
        echo_error "Provided: $resource_id"
        exit 1
    fi
}

# Function to parse command line arguments
parse_arguments() {
    RESOURCE_GROUP=""
    AI_FOUNDRY_PROJECT_RESOURCE_ID=""
    CONNECTION_NAME="cosmos-mcp-toolkit"

    while [[ $# -gt 0 ]]; do
        case $1 in
            --resource-group)
                RESOURCE_GROUP="$2"
                shift 2
                ;;
            --ai-foundry-project-resource-id)
                AI_FOUNDRY_PROJECT_RESOURCE_ID="$2"
                shift 2
                ;;
            --connection-name)
                CONNECTION_NAME="$2"
                shift 2
                ;;
            -h|--help)
                print_usage
                exit 0
                ;;
            *)
                echo_error "Unknown argument: $1"
                print_usage
                exit 1
                ;;
        esac
    done

    # Check if all required arguments are provided
    if [ -z "$RESOURCE_GROUP" ]; then
        echo_error "Missing required argument: --resource-group"
        print_usage
        exit 1
    fi

    if [ -z "$AI_FOUNDRY_PROJECT_RESOURCE_ID" ]; then
        echo_error "Missing required argument: --ai-foundry-project-resource-id"
        print_usage
        exit 1
    fi

    validate_ai_foundry_project_resource_id "$AI_FOUNDRY_PROJECT_RESOURCE_ID"

    AI_FOUNDRY_SUBSCRIPTION_ID=$(echo "$AI_FOUNDRY_PROJECT_RESOURCE_ID" | sed -E 's|^/subscriptions/([^/]+)/.*$|\1|')
    if [[ -z "$AI_FOUNDRY_SUBSCRIPTION_ID" ]]; then
        echo_error "Failed to extract subscription ID from AI Foundry project resource ID."
        exit 1
    fi
    
    AI_FOUNDRY_ACCOUNT_NAME=$(echo "$AI_FOUNDRY_PROJECT_RESOURCE_ID" | sed -E 's|^.*/providers/Microsoft\.CognitiveServices/accounts/([^/]+)/projects/.*$|\1|')
    if [[ -z "$AI_FOUNDRY_ACCOUNT_NAME" ]]; then
        echo_error "Failed to extract account name from AI Foundry project resource ID."
        exit 1
    fi

    AI_FOUNDRY_RESOURCE_GROUP=$(echo "$AI_FOUNDRY_PROJECT_RESOURCE_ID" | sed -E 's|^/subscriptions/[^/]+/resourceGroups/([^/]+)/.*$|\1|')
    if [[ -z "$AI_FOUNDRY_RESOURCE_GROUP" ]]; then
        echo_error "Failed to extract resource group from AI Foundry project resource ID."
        exit 1
    fi

    AI_FOUNDRY_PROJECT_NAME=$(echo "$AI_FOUNDRY_PROJECT_RESOURCE_ID" | sed -E 's|^.*/projects/([^/]+)$|\1|')
    if [[ -z "$AI_FOUNDRY_PROJECT_NAME" ]]; then
        echo_error "Failed to extract project name from AI Foundry project resource ID."
        exit 1
    fi
    
    echo_header "═══════════════════════════════════════════════════════════════"
    echo_header "  Azure Cosmos DB MCP Toolkit - AI Foundry Integration Setup"
    echo_header "═══════════════════════════════════════════════════════════════"
    echo ""
    echo_info "✓ MCP Toolkit Resource Group: $RESOURCE_GROUP"
    echo_info "✓ Connection Name: $CONNECTION_NAME"
    echo_info "✓ AI Foundry Subscription: $AI_FOUNDRY_SUBSCRIPTION_ID"
    echo_info "✓ AI Foundry Account: $AI_FOUNDRY_ACCOUNT_NAME"
    echo_info "✓ AI Foundry Resource Group: $AI_FOUNDRY_RESOURCE_GROUP"
    echo_info "✓ AI Foundry Project: $AI_FOUNDRY_PROJECT_NAME"
    echo ""
}

check_prerequisites() {
    echo_info "Checking prerequisites (az-cli, jq, curl)..."

    if ! command -v az &> /dev/null; then
        echo_error "Azure CLI is not installed. Please install it from https://docs.microsoft.com/en-us/cli/azure/install-azure-cli"
        exit 1
    fi

    if ! command -v jq &> /dev/null; then
        echo_error "jq is required but not installed. Please install jq to continue."
        echo_info "Install with: brew install jq (macOS) or sudo apt-get install jq (Linux)"
        exit 1
    fi

    if ! command -v curl &> /dev/null; then
        echo_error "curl is required but not installed. Please install curl to continue."
        exit 1
    fi

    echo_info "✓ All prerequisites met"
    echo ""
}

login_azure() {
    echo_info "Checking Azure CLI login status..."

    if ! az account show &> /dev/null; then
        echo_info "Not logged in. Running 'az login'..."
        az login
    fi

    # Get current subscription for MCP Toolkit
    CURRENT_SUBSCRIPTION=$(az account show --query "id" -o tsv)
    echo_info "✓ Logged in to Azure (Subscription: $CURRENT_SUBSCRIPTION)"
    echo ""
}

get_mcp_server_details() {
    echo_info "Retrieving MCP Toolkit deployment details..."

    # Find Container App
    CONTAINER_APP_NAME=$(az containerapp list --resource-group "$RESOURCE_GROUP" --query "[0].name" -o tsv 2>/dev/null)
    if [[ -z "$CONTAINER_APP_NAME" ]]; then
        echo_error "No Container App found in resource group: $RESOURCE_GROUP"
        echo_error "Please ensure the MCP Toolkit is deployed to this resource group."
        exit 1
    fi

    # Get Container App URL
    CONTAINER_APP_URL=$(az containerapp show --name "$CONTAINER_APP_NAME" --resource-group "$RESOURCE_GROUP" --query "properties.configuration.ingress.fqdn" -o tsv 2>/dev/null)
    if [[ -z "$CONTAINER_APP_URL" ]]; then
        echo_error "Failed to get Container App URL"
        exit 1
    fi

    MCP_SERVER_URI="https://$CONTAINER_APP_URL"
    
    # Find Entra App
    ENTRA_APP_CLIENT_ID=$(az ad app list --query "[?contains(displayName, 'Azure Cosmos DB MCP Toolkit API')].appId | [0]" -o tsv 2>/dev/null)
    if [[ -z "$ENTRA_APP_CLIENT_ID" ]]; then
        echo_error "No Entra ID app found for Azure Cosmos DB MCP Toolkit"
        echo_error "Please run Setup-Permissions.ps1 first to create the Entra app."
        exit 1
    fi

    # Get Service Principal Object ID
    ENTRA_APP_SP_OBJECT_ID=$(az ad sp show --id "$ENTRA_APP_CLIENT_ID" --query "id" -o tsv 2>/dev/null)
    if [[ -z "$ENTRA_APP_SP_OBJECT_ID" ]]; then
        echo_error "Service principal not found for app: $ENTRA_APP_CLIENT_ID"
        echo_error "Please run Setup-Permissions.ps1 first."
        exit 1
    fi

    # Get App Role ID
    ENTRA_APP_ROLE_ID=$(az ad app show --id "$ENTRA_APP_CLIENT_ID" --query "appRoles[?value=='Mcp.Tool.Executor'].id | [0]" -o tsv 2>/dev/null)
    if [[ -z "$ENTRA_APP_ROLE_ID" ]]; then
        echo_error "App role 'Mcp.Tool.Executor' not found"
        echo_error "Please run Setup-Permissions.ps1 first."
        exit 1
    fi

    ENTRA_APP_ROLE_VALUE="Mcp.Tool.Executor"
    
    # The audience for AI Foundry should be api://{clientId}
    CONNECTION_AUDIENCE="api://$ENTRA_APP_CLIENT_ID"
    CONNECTION_TARGET="$MCP_SERVER_URI"
    
    echo_info "✓ Container App: $CONTAINER_APP_NAME"
    echo_info "✓ MCP Server URI: $MCP_SERVER_URI"
    echo_info "✓ Entra App Client ID: $ENTRA_APP_CLIENT_ID"
    echo_info "✓ Connection Audience: $CONNECTION_AUDIENCE"
    echo ""
}

get_access_token() {
    local resource_uri="$1"
    
    if [[ -z "$resource_uri" ]]; then
        echo_error "Resource URI is required"
        exit 1
    fi

    TOKEN_JSON=$(az account get-access-token --resource "$resource_uri" -o json 2>/dev/null)

    if [ $? -ne 0 ]; then
        echo_error "Failed to get access token for $resource_uri"
        exit 1
    fi

    ACCESS_TOKEN=$(jq -r '.accessToken // empty' <<< "$TOKEN_JSON")
    if [[ -z "$ACCESS_TOKEN" ]]; then
        echo_error "Failed to extract access token for $resource_uri"
        exit 1
    fi

    echo "$ACCESS_TOKEN"
}

get_ai_foundry_project_mi() {
    echo_info "Fetching AI Foundry project managed identity..."

    # Switch to AI Foundry subscription if different
    if [[ "$AI_FOUNDRY_SUBSCRIPTION_ID" != "$CURRENT_SUBSCRIPTION" ]]; then
        echo_info "Switching to AI Foundry subscription: $AI_FOUNDRY_SUBSCRIPTION_ID"
        az account set --subscription "$AI_FOUNDRY_SUBSCRIPTION_ID"
    fi

    AI_FOUNDRY_ACCOUNT_JSON=$(az cognitiveservices account show \
        --name "$AI_FOUNDRY_ACCOUNT_NAME" \
        --resource-group "$AI_FOUNDRY_RESOURCE_GROUP" \
        -o json 2>/dev/null)

    if [ $? -ne 0 ]; then
        echo_error "Failed to get AI Foundry account details"
        echo_error "Please ensure the account exists and you have access."
        exit 1
    fi

    AI_FOUNDRY_REGION=$(jq -r '.location // empty' <<< "$AI_FOUNDRY_ACCOUNT_JSON")
    if [[ -z "$AI_FOUNDRY_REGION" ]]; then
        echo_error "Failed to extract region from AI Foundry account"
        exit 1
    fi

    # Normalize region name (remove spaces, convert to lowercase)
    AI_FOUNDRY_REGION=$(echo "$AI_FOUNDRY_REGION" | tr '[:upper:]' '[:lower:]' | tr -d ' ')

    ARM_ACCESS_TOKEN=$(get_access_token "https://management.azure.com")

    echo_info "Fetching AI Foundry project details..."

    API_ENDPOINT="https://${AI_FOUNDRY_REGION}.management.azure.com:443${AI_FOUNDRY_PROJECT_RESOURCE_ID}?api-version=2025-04-01-preview"

    AI_FOUNDRY_PROJECT_JSON=$(curl -s -X GET \
        -H "Authorization: Bearer $ARM_ACCESS_TOKEN" \
        -H "Content-Type: application/json" \
        "$API_ENDPOINT")

    if [ $? -ne 0 ]; then
        echo_error "Failed to fetch AI Foundry project details"
        exit 1
    fi

    if [[ -z "$AI_FOUNDRY_PROJECT_JSON" ]]; then
        echo_error "Empty response from API"
        exit 1
    fi

    AI_FOUNDRY_PROJECT_MI_PRINCIPAL_ID=$(jq -r '.identity.principalId // empty' <<< "$AI_FOUNDRY_PROJECT_JSON")
    if [[ -z "$AI_FOUNDRY_PROJECT_MI_PRINCIPAL_ID" ]]; then
        echo_error "Failed to extract project MI Principal ID from AI Foundry project"
        echo_error "Please ensure the AI Foundry project has a managed identity enabled."
        exit 1
    fi

    AI_FOUNDRY_PROJECT_MI_TENANT_ID=$(jq -r '.identity.tenantId // empty' <<< "$AI_FOUNDRY_PROJECT_JSON")
    AI_FOUNDRY_PROJECT_MI_TYPE=$(jq -r '.identity.type // empty' <<< "$AI_FOUNDRY_PROJECT_JSON")
    
    echo_info "✓ AI Foundry Project MI Principal ID: $AI_FOUNDRY_PROJECT_MI_PRINCIPAL_ID"
    echo_info "✓ MI Type: $AI_FOUNDRY_PROJECT_MI_TYPE"
    echo ""
}

create_ai_foundry_mi_connection() {
    echo_info "Creating managed identity connection: $CONNECTION_NAME..."

    ARM_ACCESS_TOKEN=$(get_access_token "https://management.azure.com")

    CONNECTION_PAYLOAD=$(jq -n \
        --arg name "$CONNECTION_NAME" \
        --arg target "$CONNECTION_TARGET" \
        --arg audience "$CONNECTION_AUDIENCE" \
        '{
            "name": $name,
            "type": "Microsoft.CognitiveServices/accounts/projects/connections",
            "properties": {
                "authType": "ProjectManagedIdentity",
                "audience": $audience,
                "group": "GenericProtocol",
                "category": "RemoteTool",
                "target": $target,
                "useWorkspaceManagedIdentity": false,
                "isSharedToAll": false,
                "sharedUserList": [],
                "metadata": {
                    "type": "custom_MCP",
                    "description": "Azure Cosmos DB MCP Toolkit connection for AI agents"
                }
            }
        }')

    API_ENDPOINT="https://${AI_FOUNDRY_REGION}.management.azure.com:443${AI_FOUNDRY_PROJECT_RESOURCE_ID}/connections/${CONNECTION_NAME}?api-version=2025-04-01-preview"

    CREATE_CONNECTION_RESPONSE=$(curl -s -X PUT \
        -H "Authorization: Bearer $ARM_ACCESS_TOKEN" \
        -H "Content-Type: application/json" \
        -d "$CONNECTION_PAYLOAD" \
        "$API_ENDPOINT")

    if [ $? -ne 0 ]; then
        echo_error "Failed to create connection"
        exit 1
    fi

    if [[ -z "$CREATE_CONNECTION_RESPONSE" ]]; then
        echo_error "Empty response from API"
        exit 1
    fi

    # Check for error in response
    ERROR_MESSAGE=$(jq -r '.error.message // empty' <<< "$CREATE_CONNECTION_RESPONSE")
    if [[ -n "$ERROR_MESSAGE" ]]; then
        echo_error "Failed to create connection: $ERROR_MESSAGE"
        exit 1
    fi

    AI_FOUNDRY_PROJECT_MI_CONNECTION_NAME=$(jq -r '.name // empty' <<< "$CREATE_CONNECTION_RESPONSE")
    if [[ -z "$AI_FOUNDRY_PROJECT_MI_CONNECTION_NAME" ]]; then
        echo_error "Failed to read connection name from response"
        echo_error "Response:"
        echo "$CREATE_CONNECTION_RESPONSE" | jq .
        exit 1
    fi

    AI_FOUNDRY_PROJECT_MI_CONNECTION_TARGET=$(jq -r '.properties.target // empty' <<< "$CREATE_CONNECTION_RESPONSE")
    AI_FOUNDRY_PROJECT_MI_CONNECTION_AUDIENCE=$(jq -r '.properties.audience // empty' <<< "$CREATE_CONNECTION_RESPONSE")
    
    echo_info "✓ Connection created successfully!"
    echo ""
}

set_ai_foundry_mi_role_assignment() {
    echo_info "Assigning 'Mcp.Tool.Executor' role to AI Foundry project MI..."
    
    GRAPH_ACCESS_TOKEN=$(get_access_token "https://graph.microsoft.com")

    echo_info "Checking for existing role assignment..."
    EXISTING_RESPONSE=$(curl -s -X GET \
        "https://graph.microsoft.com/v1.0/servicePrincipals/$AI_FOUNDRY_PROJECT_MI_PRINCIPAL_ID/appRoleAssignments" \
        -H "Authorization: Bearer $GRAPH_ACCESS_TOKEN" \
        -H "Content-Type: application/json")

    if [ $? -ne 0 ]; then
        echo_error "Failed to query existing role assignments"
        exit 1
    fi

    EXISTING_ASSIGNMENT=$(echo "$EXISTING_RESPONSE" | jq -r ".value[] | select(.resourceId==\"$ENTRA_APP_SP_OBJECT_ID\" and .appRoleId==\"$ENTRA_APP_ROLE_ID\") | .id" 2>/dev/null)

    if [[ -n "$EXISTING_ASSIGNMENT" ]]; then
        echo_info "✓ App role assignment already exists"
        echo_info "  Role Assignment ID: $EXISTING_ASSIGNMENT"
        ENTRA_APP_ROLE_ASSIGNMENT_ID="$EXISTING_ASSIGNMENT"
    else
        echo_info "Creating new app role assignment..."

        ROLE_ASSIGNMENT_PAYLOAD=$(jq -n \
            --arg principalId "$AI_FOUNDRY_PROJECT_MI_PRINCIPAL_ID" \
            --arg resourceId "$ENTRA_APP_SP_OBJECT_ID" \
            --arg appRoleId "$ENTRA_APP_ROLE_ID" \
            '{
                "principalId": $principalId,
                "resourceId": $resourceId,
                "appRoleId": $appRoleId
            }')

        ROLE_ASSIGNMENT_RESPONSE=$(curl -s -X POST \
            "https://graph.microsoft.com/v1.0/servicePrincipals/$AI_FOUNDRY_PROJECT_MI_PRINCIPAL_ID/appRoleAssignments" \
            -H "Authorization: Bearer $GRAPH_ACCESS_TOKEN" \
            -H "Content-Type: application/json" \
            -d "$ROLE_ASSIGNMENT_PAYLOAD")

        if [ $? -eq 0 ]; then
            ENTRA_APP_ROLE_ASSIGNMENT_ID=$(jq -r '.id // empty' <<< "$ROLE_ASSIGNMENT_RESPONSE")
            
            # Check for error
            ERROR_MESSAGE=$(jq -r '.error.message // empty' <<< "$ROLE_ASSIGNMENT_RESPONSE")
            if [[ -n "$ERROR_MESSAGE" ]]; then
                echo_error "Failed to assign app role: $ERROR_MESSAGE"
                exit 1
            fi
            
            if [[ -n "$ENTRA_APP_ROLE_ASSIGNMENT_ID" && "$ENTRA_APP_ROLE_ASSIGNMENT_ID" != "null" ]]; then
                echo_info "✓ Successfully assigned app role to project MI"
                echo_info "  Role Assignment ID: $ENTRA_APP_ROLE_ASSIGNMENT_ID"
            else
                echo_error "Failed to assign app role to project MI"
                echo_error "Response:"
                echo "$ROLE_ASSIGNMENT_RESPONSE" | jq .
                exit 1
            fi
        else
            echo_error "Failed to create app role assignment"
            exit 1
        fi
    fi
    echo ""
}

# Display results as JSON
show_results() {
    echo ""
    echo_header "═══════════════════════════════════════════════════════════════"
    echo_header "  Setup Completed Successfully!"
    echo_header "═══════════════════════════════════════════════════════════════"
    echo ""
    echo_info "Connection Details:"
    echo ""
    
    jq -n \
        --arg resource_group "$RESOURCE_GROUP" \
        --arg mcp_server_uri "$MCP_SERVER_URI" \
        --arg entra_app_client_id "$ENTRA_APP_CLIENT_ID" \
        --arg ai_foundry_project_resource_id "$AI_FOUNDRY_PROJECT_RESOURCE_ID" \
        --arg ai_foundry_subscription_id "$AI_FOUNDRY_SUBSCRIPTION_ID" \
        --arg ai_foundry_resource_group "$AI_FOUNDRY_RESOURCE_GROUP" \
        --arg ai_foundry_account_name "$AI_FOUNDRY_ACCOUNT_NAME" \
        --arg ai_foundry_project_name "$AI_FOUNDRY_PROJECT_NAME" \
        --arg ai_foundry_region "$AI_FOUNDRY_REGION" \
        --arg ai_foundry_project_mi_principal_id "$AI_FOUNDRY_PROJECT_MI_PRINCIPAL_ID" \
        --arg ai_foundry_project_mi_type "$AI_FOUNDRY_PROJECT_MI_TYPE" \
        --arg ai_foundry_project_mi_tenant_id "$AI_FOUNDRY_PROJECT_MI_TENANT_ID" \
        --arg connection_name "$AI_FOUNDRY_PROJECT_MI_CONNECTION_NAME" \
        --arg connection_target "$AI_FOUNDRY_PROJECT_MI_CONNECTION_TARGET" \
        --arg connection_audience "$AI_FOUNDRY_PROJECT_MI_CONNECTION_AUDIENCE" \
        --arg role_assignment_id "$ENTRA_APP_ROLE_ASSIGNMENT_ID" \
        '{
            "MCP_Toolkit": {
                "ResourceGroup": $resource_group,
                "ServerURI": $mcp_server_uri,
                "EntraAppClientId": $entra_app_client_id
            },
            "AI_Foundry": {
                "ProjectResourceId": $ai_foundry_project_resource_id,
                "SubscriptionId": $ai_foundry_subscription_id,
                "ResourceGroup": $ai_foundry_resource_group,
                "AccountName": $ai_foundry_account_name,
                "ProjectName": $ai_foundry_project_name,
                "Region": $ai_foundry_region,
                "ManagedIdentity": {
                    "PrincipalId": $ai_foundry_project_mi_principal_id,
                    "Type": $ai_foundry_project_mi_type,
                    "TenantId": $ai_foundry_project_mi_tenant_id,
                    "RoleAssignmentId": $role_assignment_id
                }
            },
            "Connection": {
                "Name": $connection_name,
                "Target": $connection_target,
                "Audience": $connection_audience,
                "Status": "Active"
            }
        }'
    
    echo ""
    echo_info "Next Steps:"
    echo_info "1. Go to Azure AI Foundry Portal: https://ai.azure.com"
    echo_info "2. Navigate to your project: $AI_FOUNDRY_PROJECT_NAME"
    echo_info "3. Your connection '$CONNECTION_NAME' is ready to use!"
    echo_info "4. Test with: @agent List all databases in Cosmos DB"
    echo ""
}

# Main function
main() {
    parse_arguments "$@"
    check_prerequisites
    login_azure
    get_mcp_server_details
    get_ai_foundry_project_mi
    create_ai_foundry_mi_connection
    set_ai_foundry_mi_role_assignment
    show_results
}

# Run main function
main "$@"
