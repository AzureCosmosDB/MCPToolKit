@description('Prefix for all resource names')
param resourcePrefix string = 'mcp-toolkit'

@description('Location for all resources')
param location string = resourceGroup().location

@description('Cosmos DB endpoint (external resource)')
param cosmosEndpoint string

@description('AI Foundry project endpoint (recommended) or legacy Azure OpenAI endpoint. Example: https://my-project.eastus.api.azureml.ms/ or https://my-openai.openai.azure.com/')
param aifProjectEndpoint string

@description('Embedding model deployment name in AI Foundry project or Azure OpenAI. Example: text-embedding-3-small or text-embedding-ada-002')
param embeddingDeploymentName string

@description('Embedding dimensions (optional). For text-embedding-3-large/small models. Leave as 0 or blank for text-embedding-ada-002.')
param embeddingDimensions int = 0

@description('Container app name')
param containerAppName string = '${resourcePrefix}-app'

@description('Container registry name')
param containerRegistryName string = '${replace(resourcePrefix, '-', '')}acr${uniqueString(resourceGroup().id)}'

@description('Entra App display name')
param entraAppDisplayName string = '${resourcePrefix}-entra-app'

@description('AI Foundry project resource ID (optional - only needed if assigning Entra App role to AIF project MI)')
param aifProjectResourceId string = ''

// Variables
var containerAppEnvName = '${resourcePrefix}-env'
var entraAppUniqueName = '${replace(toLower(entraAppDisplayName), ' ', '-')}-${uniqueString(deployment().name, resourceGroup().id)}'

// Common tags for all resources
var commonTags = {
  Environment: 'Production'
  Application: 'MCP-Toolkit'
}

// Built-in role definition IDs
var acrPullRoleId = '7f951dda-4ed3-4680-a7ca-43fe172d538d' // AcrPull

// Deploy Entra App
module entraApp 'modules/entra-app.bicep' = {
  name: 'entra-app-deployment'
  params: {
    entraAppDisplayName: entraAppDisplayName
    entraAppUniqueName: entraAppUniqueName
  }
}

// Create Container Registry
resource containerRegistry 'Microsoft.ContainerRegistry/registries@2023-07-01' = {
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
            // AI Foundry / Azure OpenAI configuration
            // OPENAI_ENDPOINT: AI Foundry project endpoint (recommended) or legacy Azure OpenAI endpoint
            // The Azure.AI.OpenAI SDK works seamlessly with both AI Foundry and legacy endpoints
            {
              name: 'OPENAI_ENDPOINT'
              value: aifProjectEndpoint
            }
            {
              name: 'OPENAI_EMBEDDING_DEPLOYMENT'
              value: embeddingDeploymentName
            }
            {
              name: 'OPENAI_EMBEDDING_DIMENSIONS'
              value: string(embeddingDimensions)
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
            // Entra App authentication configuration
            {
              name: 'AzureAd__TenantId'
              value: tenant().tenantId
            }
            {
              name: 'AzureAd__ClientId'
              value: entraApp.outputs.entraAppClientId
            }
            {
              name: 'AzureAd__Audience'
              value: entraApp.outputs.entraAppClientId
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
resource acrRoleAssignmentMI 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  scope: containerRegistry
  name: guid(containerRegistry.id, containerApp.id, acrPullRoleId)
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', acrPullRoleId)
    principalId: containerApp.identity.principalId
    principalType: 'ServicePrincipal'
  }
}

// Deploy Entra App role assignment for AIF project MI to access Container App (conditional)
module aifRoleAssignment 'modules/aif-role-assignment-entraapp.bicep' = if (!empty(aifProjectResourceId)) {
  name: 'aif-role-assignment'
  params: {
    aifProjectResourceId: aifProjectResourceId
    entraAppServicePrincipalObjectId: entraApp.outputs.entraAppServicePrincipalObjectId
    entraAppRoleId: entraApp.outputs.entraAppRoleId
  }
}

// Outputs
output containerAppUrl string = 'https://${containerApp.properties.configuration.ingress.fqdn}'
output containerRegistryName string = containerRegistry.name
output containerRegistryLoginServer string = containerRegistry.properties.loginServer
output managedIdentityPrincipalId string = containerApp.identity.principalId
output containerAppEnvironmentId string = containerAppEnvironment.id
output containerAppId string = containerApp.id
output resourceGroupName string = resourceGroup().name

// Entra App outputs
output entraAppClientId string = entraApp.outputs.entraAppClientId
output entraAppObjectId string = entraApp.outputs.entraAppObjectId
output entraAppServicePrincipalId string = entraApp.outputs.entraAppServicePrincipalObjectId
output entraAppRoleId string = entraApp.outputs.entraAppRoleId
output entraAppIdentifierUri string = entraApp.outputs.entraAppIdentifierUri
output entraAppRoleValue string = entraApp.outputs.entraAppRoleValue

// Resource configuration for post-deployment
output postDeploymentInfo object = {
  containerRegistry: containerRegistryName
  containerApp: containerAppName
  managedIdentityPrincipalId: containerApp.identity.principalId
  mcpServerUri: 'https://${containerApp.properties.configuration.ingress.fqdn}'
  entraAppClientId: entraApp.outputs.entraAppClientId
  entraAppRoleValue: entraApp.outputs.entraAppRoleValue
  entraAppRoleId: entraApp.outputs.entraAppRoleId
  entraAppServicePrincipalObjectId: entraApp.outputs.entraAppServicePrincipalObjectId
}
