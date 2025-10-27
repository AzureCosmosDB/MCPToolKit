#!/bin/bash

# Azure MCP Toolkit - Complete Deployment Script
# This script deploys the MCP toolkit container app with external Cosmos DB and Azure OpenAI

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

echo -e "${GREEN}🚀 Azure MCP Toolkit - Complete Deployment${NC}"
echo "══════════════════════════════════════════════════════════════"

# Check if required parameters are provided
if [ -z "$RESOURCE_GROUP_NAME" ]; then
    echo -e "${RED}❌ Error: RESOURCE_GROUP_NAME environment variable is required${NC}"
    exit 1
fi

if [ -z "$LOCATION" ]; then
    echo -e "${RED}❌ Error: LOCATION environment variable is required${NC}"
    exit 1
fi

if [ -z "$PRINCIPAL_ID" ]; then
    echo -e "${RED}❌ Error: PRINCIPAL_ID environment variable is required${NC}"
    exit 1
fi

if [ -z "$COSMOS_ENDPOINT" ]; then
    echo -e "${RED}❌ Error: COSMOS_ENDPOINT environment variable is required${NC}"
    exit 1
fi

if [ -z "$OPENAI_ENDPOINT" ]; then
    echo -e "${RED}❌ Error: OPENAI_ENDPOINT environment variable is required${NC}"
    exit 1
fi

if [ -z "$OPENAI_EMBEDDING_DEPLOYMENT" ]; then
    echo -e "${RED}❌ Error: OPENAI_EMBEDDING_DEPLOYMENT environment variable is required${NC}"
    exit 1
fi

# Set defaults
PRINCIPAL_TYPE=${PRINCIPAL_TYPE:-"User"}
RESOURCE_PREFIX=${RESOURCE_PREFIX:-"mcp-toolkit"}

echo -e "${BLUE}📋 Deployment Configuration:${NC}"
echo "   Resource Group: $RESOURCE_GROUP_NAME"
echo "   Location: $LOCATION"
echo "   Principal ID: $PRINCIPAL_ID"
echo "   Principal Type: $PRINCIPAL_TYPE"
echo "   Resource Prefix: $RESOURCE_PREFIX"
echo "   Cosmos DB Endpoint: $COSMOS_ENDPOINT"
echo "   Azure OpenAI Endpoint: $OPENAI_ENDPOINT"
echo "   OpenAI Embedding Deployment: $OPENAI_EMBEDDING_DEPLOYMENT"
echo ""

# Check if Azure CLI is logged in
echo -e "${BLUE}🔍 Checking Azure CLI authentication...${NC}"
if ! az account show &> /dev/null; then
    echo -e "${RED}❌ Not logged in to Azure CLI. Please run 'az login' first.${NC}"
    exit 1
fi

ACCOUNT_INFO=$(az account show --query "{name:name, user:user.name}" -o json)
echo -e "${GREEN}✅ Logged in to Azure${NC}"
echo "   Account: $(echo $ACCOUNT_INFO | jq -r .name)"
echo "   User: $(echo $ACCOUNT_INFO | jq -r .user)"

# Create resource group
echo -e "${BLUE}📦 Creating resource group...${NC}"
az group create --name "$RESOURCE_GROUP_NAME" --location "$LOCATION" --tags Environment=Production Application=MCP-Toolkit

# Deploy container app resources only
echo -e "${BLUE}☁️ Deploying Azure Container App resources...${NC}"
DEPLOYMENT_NAME="mcp-toolkit-deployment-$(date +%Y%m%d-%H%M%S)"

az deployment group create \
    --resource-group "$RESOURCE_GROUP_NAME" \
    --template-file "infrastructure/deploy-all-resources.bicep" \
    --name "$DEPLOYMENT_NAME" \
    --parameters \
        resourcePrefix="$RESOURCE_PREFIX" \
        location="$LOCATION" \
        principalId="$PRINCIPAL_ID" \
        principalType="$PRINCIPAL_TYPE" \
        cosmosEndpoint="$COSMOS_ENDPOINT" \
        openaiEndpoint="$OPENAI_ENDPOINT" \
        openaiEmbeddingDeployment="$OPENAI_EMBEDDING_DEPLOYMENT"

if [ $? -ne 0 ]; then
    echo -e "${RED}❌ Container App deployment failed${NC}"
    exit 1
fi

echo -e "${GREEN}✅ Container App resources deployed successfully!${NC}"

echo -e "${YELLOW}📋 Important: You need to manually assign permissions for the Managed Identity to access your external resources:${NC}"
echo "   1. Cosmos DB: Assign 'Cosmos DB Built-in Data Contributor' role to Principal ID: $PRINCIPAL_ID"
echo "   2. Azure OpenAI: Assign 'Cognitive Services OpenAI User' role to Principal ID: $PRINCIPAL_ID"
echo ""

# Get deployment outputs
echo -e "${BLUE}📋 Getting deployment outputs...${NC}"
OUTPUTS=$(az deployment group show --resource-group "$RESOURCE_GROUP_NAME" --name "$DEPLOYMENT_NAME" --query "properties.outputs" -o json)

CONTAINER_REGISTRY_NAME=$(echo $OUTPUTS | jq -r .containerRegistryName.value)
CONTAINER_APP_NAME=$(echo $OUTPUTS | jq -r .postDeploymentInfo.value.containerApp)
ACR_LOGIN_SERVER=$(echo $OUTPUTS | jq -r .containerRegistryLoginServer.value)
CONTAINER_APP_URL=$(echo $OUTPUTS | jq -r .containerAppUrl.value)

echo "   Container Registry: $CONTAINER_REGISTRY_NAME"
echo "   Container App: $CONTAINER_APP_NAME"
echo "   Container App URL: $CONTAINER_APP_URL"

# Check if Docker is available for building the image
if command -v docker &> /dev/null; then
    echo -e "${BLUE}🐳 Building and deploying container image...${NC}"
    
    # Login to ACR
    az acr login --name "$CONTAINER_REGISTRY_NAME"
    
    # Build image
    IMAGE_NAME="$ACR_LOGIN_SERVER/mcp-toolkit:latest"
    docker build -t "$IMAGE_NAME" .
    
    if [ $? -ne 0 ]; then
        echo -e "${RED}❌ Docker build failed${NC}"
        exit 1
    fi
    
    # Push image
    docker push "$IMAGE_NAME"
    
    if [ $? -ne 0 ]; then
        echo -e "${RED}❌ Docker push failed${NC}"
        exit 1
    fi
    
    echo -e "${GREEN}✅ Image pushed: $IMAGE_NAME${NC}"
    
    # Update container app
    echo -e "${BLUE}🚀 Updating container app...${NC}"
    az containerapp update \
        --name "$CONTAINER_APP_NAME" \
        --resource-group "$RESOURCE_GROUP_NAME" \
        --image "$IMAGE_NAME"
    
    if [ $? -ne 0 ]; then
        echo -e "${RED}❌ Container app update failed${NC}"
        exit 1
    fi
    
    echo -e "${GREEN}✅ Container app updated successfully!${NC}"
else
    echo -e "${YELLOW}⚠️ Docker not found. You'll need to build and deploy the container image manually.${NC}"
    echo "   1. Build: docker build -t $ACR_LOGIN_SERVER/mcp-toolkit:latest ."
    echo "   2. Login: az acr login --name $CONTAINER_REGISTRY_NAME"
    echo "   3. Push: docker push $ACR_LOGIN_SERVER/mcp-toolkit:latest"
    echo "   4. Update: az containerapp update --name $CONTAINER_APP_NAME --resource-group $RESOURCE_GROUP_NAME --image $ACR_LOGIN_SERVER/mcp-toolkit:latest"
fi

# Display summary
echo ""
echo -e "${GREEN}🎉 Deployment Complete!${NC}"
echo "══════════════════════════════════════════════════════════════"
echo -e "${BLUE}📊 Resource Summary:${NC}"
echo "   Resource Group: $RESOURCE_GROUP_NAME"
echo "   Container App URL: $CONTAINER_APP_URL"
echo "   Health Check: $CONTAINER_APP_URL/health"
echo "   Using External Cosmos DB: $COSMOS_ENDPOINT"
echo "   Using External Azure OpenAI: $OPENAI_ENDPOINT"
echo ""

# Test health endpoint if Docker was available
if command -v docker &> /dev/null; then
    echo -e "${BLUE}🔍 Testing health endpoint (waiting 30 seconds for startup)...${NC}"
    sleep 30
    
    if curl -f -s "$CONTAINER_APP_URL/health" > /dev/null; then
        echo -e "${GREEN}✅ Health check passed!${NC}"
    else
        echo -e "${YELLOW}⚠️ Health check failed (container may still be starting)${NC}"
        echo "   Try again in a few minutes: $CONTAINER_APP_URL/health"
    fi
fi

echo ""
echo -e "${YELLOW}📋 VS Code MCP Configuration:${NC}"
echo "Add this to your .vscode/mcp.json file:"
echo ""
cat << EOF
{
  "servers": {
    "azure-cosmos-db-mcp": {
      "type": "http",
      "url": "$CONTAINER_APP_URL"
    }
  }
}
EOF

echo ""
echo -e "${YELLOW}🧪 Test Commands for GitHub Copilot:${NC}"
echo "After configuring VS Code MCP integration and setting up RBAC permissions:"
echo "- 'List all databases in my Cosmos DB account'"
echo "- 'Show containers in my database'"
echo "- 'Get recent documents from my container'"
echo "- 'Search for documents similar to [your query]'"

echo ""
echo -e "${YELLOW}⚠️ Next Steps Required:${NC}"
echo "1. Grant the Managed Identity access to your external Cosmos DB"
echo "2. Grant the Managed Identity access to your external Azure OpenAI"
echo "3. Test the health endpoint after RBAC setup"
echo ""
echo -e "${GREEN}✨ Your Azure MCP Toolkit Container App is now ready!${NC}"