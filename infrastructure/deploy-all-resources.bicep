@description('Prefix for all resource names')
param resourcePrefix string = 'mcp-toolkit'

@description('Location for all resources')
param location string = resourceGroup().location

@description('The Azure AD Object ID of the user/service principal that will have access to the external resources (for manual RBAC assignment)')
param principalId string

@description('The type of principal (User, ServicePrincipal, or Group) for external resource access')
@allowed([
  'User'
  'ServicePrincipal'
  'Group'
])
param principalType string = 'User'

@description('Owner tag value (optional)')
param ownerTag string = 'mcp-toolkit-user'

@description('Cosmos DB endpoint (external resource)')
param cosmosEndpoint string

@description('Azure OpenAI endpoint (external resource)')
param openaiEndpoint string

@description('Azure OpenAI embedding deployment name')
param openaiEmbeddingDeployment string

@description('Container app name')
param containerAppName string = '${resourcePrefix}-app'

@description('Container registry name')
param containerRegistryName string = '${replace(resourcePrefix, '-', '')}acr${uniqueString(resourceGroup().id)}'

@description('Entra App display name')
param entraAppDisplayName string = '${resourcePrefix}-entra-app'

@description('AI Foundry project resource ID (optional - only needed if assigning Entra App role to AIF project MI)')
param aifProjectResourceId string = ''

// Variables
var managedIdentityName = '${containerAppName}-identity'
var containerAppEnvName = '${resourcePrefix}-env'
var entraAppUniqueName = '${replace(toLower(entraAppDisplayName), ' ', '-')}-${uniqueString(deployment().name, resourceGroup().id)}'

// Common tags for all resources
var commonTags = {
  Environment: 'Production'
  Application: 'MCP-Toolkit'
  owner: ownerTag
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

// Create user-assigned managed identity
resource managedIdentity 'Microsoft.ManagedIdentity/userAssignedIdentities@2023-01-31' = {
  name: managedIdentityName
  location: location
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
    type: 'UserAssigned'
    userAssignedIdentities: {
      '${managedIdentity.id}': {}
    }
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
            {
              name: 'COSMOS_ENDPOINT'
              value: cosmosEndpoint
            }
            {
              name: 'OPENAI_ENDPOINT'
              value: openaiEndpoint
            }
            {
              name: 'OPENAI_EMBEDDING_DEPLOYMENT'
              value: openaiEmbeddingDeployment
            }
            {
              name: 'ASPNETCORE_ENVIRONMENT'
              value: 'Production'
            }
            {
              name: 'ASPNETCORE_URLS'
              value: 'http://+:8080'
            }
            {
              name: 'AZURE_CLIENT_ID'
              value: managedIdentity.properties.clientId
            }
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

// Assign ACR Pull role to managed identity
resource acrRoleAssignmentMI 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  scope: containerRegistry
  name: guid(containerRegistry.id, managedIdentity.id, acrPullRoleId)
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', acrPullRoleId)
    principalId: managedIdentity.properties.principalId
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
output managedIdentityPrincipalId string = managedIdentity.properties.principalId
output managedIdentityClientId string = managedIdentity.properties.clientId
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
  managedIdentityPrincipalId: managedIdentity.properties.principalId
  mcpServerUri: 'https://${containerApp.properties.configuration.ingress.fqdn}'
  entraAppClientId: entraApp.outputs.entraAppClientId
  entraAppRoleValue: entraApp.outputs.entraAppRoleValue
  entraAppRoleId: entraApp.outputs.entraAppRoleId
  entraAppServicePrincipalObjectId: entraApp.outputs.entraAppServicePrincipalObjectId
}