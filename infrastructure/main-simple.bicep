@description('Location for all resources')
param location string = resourceGroup().location

@description('Name for the Azure Container App')
param containerAppName string = 'mcp-demo-app'

@description('Environment name for the Container Apps Environment')
param environmentName string = 'mcp-toolkit-env'

@description('Display name for the Entra App')
param entraAppDisplayName string = 'Azure Cosmos DB MCP Toolkit API'

@description('Container registry name')
param containerRegistryName string = 'mcpdemo${uniqueString(resourceGroup().id)}'

@description('Container image name')
param containerImage string = 'mcr.microsoft.com/azuredocs/containerapps-helloworld:latest'

@description('Number of CPU cores allocated to the container')
param cpuCores string = '0.5'

@description('Amount of memory allocated to the container')
param memorySize string = '1Gi'

@description('Minimum number of replicas')
param minReplicas int = 1

@description('Maximum number of replicas')
param maxReplicas int = 3

@description('Common tags for all resources')
param commonTags object = {
  Environment: 'Production'
  Application: 'MCP-Toolkit'
}

// Container Registry
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
  name: '${containerAppName}-identity'
  location: location
  tags: commonTags
}

// Assign AcrPull role to managed identity
resource acrPullRole 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(containerRegistry.id, managedIdentity.id, 'AcrPull')
  scope: containerRegistry
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', '7f951dda-4ed3-4680-a7ca-43fe172d538d')
    principalId: managedIdentity.properties.principalId
    principalType: 'ServicePrincipal'
  }
}

// Create Container App Environment
resource containerAppEnvironment 'Microsoft.App/managedEnvironments@2024-03-01' = {
  name: environmentName
  location: location
  properties: {
    zoneRedundant: false
  }
  tags: commonTags
}

// Create Container App
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
      activeRevisionsMode: 'Single'
      ingress: {
        external: true
        targetPort: 8080
        allowInsecure: false
        transport: 'http'
        traffic: [
          {
            weight: 100
            latestRevision: true
          }
        ]
      }
      registries: [
        {
          server: containerRegistry.properties.loginServer
          identity: managedIdentity.id
        }
      ]
      secrets: []
    }
    template: {
      containers: [
        {
          image: containerImage
          name: containerAppName
          resources: {
            cpu: json(cpuCores)
            memory: memorySize
          }
          env: [
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
          ]
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
        minReplicas: minReplicas
        maxReplicas: maxReplicas
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
  dependsOn: [
    acrPullRole
  ]
  tags: commonTags
}

// Outputs for azd and other consumers
output AZURE_LOCATION string = location
output AZURE_TENANT_ID string = tenant().tenantId
output AZURE_SUBSCRIPTION_ID string = subscription().subscriptionId

// Infrastructure outputs
output RESOURCE_GROUP_NAME string = resourceGroup().name
output CONTAINER_REGISTRY_LOGIN_SERVER string = containerRegistry.properties.loginServer
output CONTAINER_REGISTRY_NAME string = containerRegistry.name
output CONTAINER_APP_NAME string = containerApp.name
output CONTAINER_APP_URL string = 'https://${containerApp.properties.configuration.ingress.fqdn}'
output CONTAINER_APP_PRINCIPAL_ID string = managedIdentity.properties.principalId
output AZURE_CONTAINER_APP_ENVIRONMENT_ID string = containerAppEnvironment.id
