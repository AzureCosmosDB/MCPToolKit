@description('Prefix for all resource names')
param resourcePrefix string = 'mcp-toolkit'

@description('Location for all resources')
param location string = resourceGroup().location

@description('Cosmos DB endpoint (external resource)')
param cosmosEndpoint string

@description('Optional: Embedding service endpoint URL. Supports Azure AI Services, Azure AI Foundry, or OpenAI. Only needed for vector_search / hybrid_search tools.')
param azureAiServiceEndpoint string = ''

@description('Optional: Embedding model deployment name in AI Foundry project or Azure OpenAI. Only needed for vector_search / hybrid_search tools.')
param embeddingDeploymentName string = ''

@description('Enable Entra ID authentication for inbound MCP requests. When false, the server accepts unauthenticated requests.')
param enableAuth bool = false

@description('Container app name')
param containerAppName string = '${resourcePrefix}-app'

@description('Container registry name')
param containerRegistryName string = '${replace(resourcePrefix, '-', '')}acr${uniqueString(resourceGroup().id)}'

@description('Use an existing Azure Container Registry instead of creating one in this resource group')
param useExistingAcr bool = false

@description('Existing ACR name (required when useExistingAcr=true)')
param existingAcrName string = ''

@description('Resource group that contains the existing ACR (optional, defaults to current resource group)')
param existingAcrResourceGroup string = ''

@description('Entra App display name')
param entraAppDisplayName string = '${resourcePrefix}-entra-app'

@description('Microsoft Foundry project resource ID (optional - only needed if assigning Entra App role to AIF project MI)')
param aifProjectResourceId string = ''

// Variables
var containerAppEnvName = '${resourcePrefix}-env'
var entraAppUniqueName = '${replace(toLower(entraAppDisplayName), ' ', '-')}-${uniqueString(deployment().name, resourceGroup().id)}'
var resolvedAcrResourceGroup = empty(existingAcrResourceGroup) ? resourceGroup().name : existingAcrResourceGroup

// Common tags for all resources
var commonTags = {
  Environment: 'Production'
  Application: 'MCP-Toolkit'
}

// Built-in role definition IDs
var acrPullRoleId = '7f951dda-4ed3-4680-a7ca-43fe172d538d' // AcrPull

// Deploy Entra App (only when authentication is enabled)
module entraApp 'modules/entra-app.bicep' = if (enableAuth) {
  name: 'entra-app-deployment'
  params: {
    entraAppDisplayName: entraAppDisplayName
    entraAppUniqueName: entraAppUniqueName
  }
}

// Create Container Registry
resource containerRegistry 'Microsoft.ContainerRegistry/registries@2023-07-01' = if (!useExistingAcr) {
  name: containerRegistryName
  location: location
  sku: {
    name: 'Basic'
  }
  properties: {
    adminUserEnabled: true
  }
  tags: commonTags
}

resource existingContainerRegistry 'Microsoft.ContainerRegistry/registries@2023-07-01' existing = if (useExistingAcr) {
  name: existingAcrName
  scope: resourceGroup(resolvedAcrResourceGroup)
}

// Create Container App Environment (without Log Analytics)
resource containerAppEnvironment 'Microsoft.App/managedEnvironments@2024-03-01' = {
  name: containerAppEnvName
  location: location
  properties: {
    zoneRedundant: false
  }
  tags: commonTags
}

// Create Container App (will be updated later with actual image)
resource containerApp 'Microsoft.App/containerApps@2024-03-01' = {
  name: containerAppName
  location: location
  identity: {
    type: 'SystemAssigned'
  }
  properties: {
    managedEnvironmentId: containerAppEnvironment.id
    configuration: {
      ingress: {
        external: true
        targetPort: 8080
        transport: 'http'
        allowInsecure: false
        traffic: [
          {
            weight: 100
            latestRevision: true
          }
        ]
      }
      secrets: []
      activeRevisionsMode: 'Single'
    }
    template: {
      containers: [
        {
          image: 'mcr.microsoft.com/azuredocs/containerapps-helloworld:latest' // Placeholder image
          name: containerAppName
          env: [
            // Cosmos DB configuration
            {
              name: 'COSMOS_ENDPOINT'
              value: cosmosEndpoint
            }
            // Microsoft Foundry / Azure OpenAI configuration
            // OPENAI_ENDPOINT: Microsoft Foundry project endpoint (recommended) or legacy Azure OpenAI endpoint
            // The Azure.AI.OpenAI SDK works seamlessly with both Microsoft Foundry and legacy endpoints
            {
              name: 'OPENAI_ENDPOINT'
              value: azureAiServiceEndpoint
            }
            {
              name: 'OPENAI_EMBEDDING_DEPLOYMENT'
              value: embeddingDeploymentName
            }
            // ASP.NET Core configuration
            {
              name: 'ASPNETCORE_ENVIRONMENT'
              value: 'Production'
            }
            {
              name: 'ASPNETCORE_URLS'
              value: 'http://+:8080'
            }
            // Entra App authentication configuration (only set when auth is enabled)
            {
              name: 'AzureAd__TenantId'
              value: enableAuth ? tenant().tenantId : ''
            }
            {
              name: 'AzureAd__ClientId'
              value: enableAuth ? entraApp.outputs.entraAppClientId : ''
            }
            {
              name: 'AzureAd__Audience'
              value: enableAuth ? entraApp.outputs.entraAppClientId : ''
            }
          ]
          resources: {
            cpu: json('0.5')
            memory: '1Gi'
          }
          probes: [
            {
              type: 'Readiness'
              httpGet: {
                path: '/health'
                port: 8080
                scheme: 'HTTP'
              }
              initialDelaySeconds: 10
              periodSeconds: 10
              timeoutSeconds: 5
              successThreshold: 1
              failureThreshold: 3
            }
            {
              type: 'Liveness'
              httpGet: {
                path: '/health'
                port: 8080
                scheme: 'HTTP'
              }
              initialDelaySeconds: 30
              periodSeconds: 30
              timeoutSeconds: 5
              successThreshold: 1
              failureThreshold: 3
            }
          ]
        }
      ]
      scale: {
        minReplicas: 1
        maxReplicas: 3
        rules: [
          {
            name: 'http-requests'
            http: {
              metadata: {
                concurrentRequests: '10'
              }
            }
          }
        ]
      }
    }
  }
  tags: commonTags
}

// RBAC Assignments

// Assign ACR Pull role to container app's system-assigned managed identity
resource acrRoleAssignmentMI 'Microsoft.Authorization/roleAssignments@2022-04-01' = if (!useExistingAcr) {
  scope: containerRegistry
  name: guid(containerRegistry.id, containerApp.id, acrPullRoleId)
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', acrPullRoleId)
    principalId: containerApp.identity.principalId
    principalType: 'ServicePrincipal'
  }
}

// Deploy Entra App role assignment for AIF project MI to access Container App (conditional)
module aifRoleAssignment 'modules/aif-role-assignment-entraapp.bicep' = if (enableAuth && !empty(aifProjectResourceId)) {
  name: 'aif-role-assignment'
  params: {
    aifProjectResourceId: aifProjectResourceId
    entraAppServicePrincipalObjectId: entraApp.outputs.entraAppServicePrincipalObjectId
    entraAppRoleId: entraApp.outputs.entraAppRoleId
  }
}

// Outputs
output containerAppUrl string = 'https://${containerApp.properties.configuration.ingress.fqdn}'
output containerRegistryName string = useExistingAcr ? existingContainerRegistry!.name : containerRegistry!.name
output containerRegistryLoginServer string = useExistingAcr ? existingContainerRegistry!.properties.loginServer : containerRegistry!.properties.loginServer
output managedIdentityPrincipalId string = containerApp.identity.principalId
output containerAppEnvironmentId string = containerAppEnvironment.id
output containerAppId string = containerApp.id
output resourceGroupName string = resourceGroup().name

// Entra App outputs (empty when auth is disabled)
output entraAppClientId string = enableAuth ? entraApp.outputs.entraAppClientId : ''
output entraAppObjectId string = enableAuth ? entraApp.outputs.entraAppObjectId : ''
output entraAppServicePrincipalId string = enableAuth ? entraApp.outputs.entraAppServicePrincipalObjectId : ''
output entraAppRoleId string = enableAuth ? entraApp.outputs.entraAppRoleId : ''
output entraAppIdentifierUri string = enableAuth ? entraApp.outputs.entraAppIdentifierUri : ''
output entraAppRoleValue string = enableAuth ? entraApp.outputs.entraAppRoleValue : ''

// Resource configuration for post-deployment
output postDeploymentInfo object = {
  containerRegistry: containerRegistryName
  containerApp: containerAppName
  managedIdentityPrincipalId: containerApp.identity.principalId
  mcpServerUri: 'https://${containerApp.properties.configuration.ingress.fqdn}'
  entraAppClientId: enableAuth ? entraApp.outputs.entraAppClientId : ''
  entraAppRoleValue: enableAuth ? entraApp.outputs.entraAppRoleValue : ''
  entraAppRoleId: enableAuth ? entraApp.outputs.entraAppRoleId : ''
  entraAppServicePrincipalObjectId: enableAuth ? entraApp.outputs.entraAppServicePrincipalObjectId : ''
}
