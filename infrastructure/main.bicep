@description('The name of the container app')
param containerAppName string = 'mcp-toolkit'

@description('The name of the container app environment')
param environmentName string = 'mcp-toolkit-env'

@description('The location for all resources')
param location string = resourceGroup().location

@description('The container image to deploy')
param containerImage string

@description('Cosmos DB endpoint')
param cosmosEndpoint string

@description('Azure OpenAI endpoint')
param openaiEndpoint string

@description('Azure OpenAI embedding deployment name')
param openaiEmbeddingDeployment string

@description('The name of the user-assigned managed identity')
param managedIdentityName string = '${containerAppName}-identity'

@description('Container app CPU and memory configuration')
param containerResources object = {
  cpu: json('0.5')
  memory: '1Gi'
}

@description('Scaling configuration')
param scalingConfig object = {
  minReplicas: 1
  maxReplicas: 3
  concurrentRequests: 10
}

// Create user-assigned managed identity
resource managedIdentity 'Microsoft.ManagedIdentity/userAssignedIdentities@2023-01-31' = {
  name: managedIdentityName
  location: location
  tags: {
    Environment: 'Production'
    Application: 'MCP-Toolkit'
  }
}

// Create Log Analytics workspace
resource logAnalytics 'Microsoft.OperationalInsights/workspaces@2022-10-01' = {
  name: '${containerAppName}-logs'
  location: location
  properties: {
    sku: {
      name: 'PerGB2018'
    }
    retentionInDays: 30
    features: {
      enableLogAccessUsingOnlyResourcePermissions: true
    }
  }
  tags: {
    Environment: 'Production'
    Application: 'MCP-Toolkit'
  }
}

// Create Container App Environment
resource containerAppEnvironment 'Microsoft.App/managedEnvironments@2024-03-01' = {
  name: environmentName
  location: location
  properties: {
    appLogsConfiguration: {
      destination: 'log-analytics'
      logAnalyticsConfiguration: {
        customerId: logAnalytics.properties.customerId
        sharedKey: logAnalytics.listKeys().primarySharedKey
      }
    }
    zoneRedundant: false
  }
  tags: {
    Environment: 'Production'
    Application: 'MCP-Toolkit'
  }
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
          image: containerImage
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
          ]
          resources: containerResources
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
        minReplicas: scalingConfig.minReplicas
        maxReplicas: scalingConfig.maxReplicas
        rules: [
          {
            name: 'http-requests'
            http: {
              metadata: {
                concurrentRequests: string(scalingConfig.concurrentRequests)
              }
            }
          }
        ]
      }
      revisionSuffix: ''
    }
  }
  tags: {
    Environment: 'Production'
    Application: 'MCP-Toolkit'
  }
}

// Outputs
output containerAppUrl string = 'https://${containerApp.properties.configuration.ingress.fqdn}'
output managedIdentityPrincipalId string = managedIdentity.properties.principalId
output managedIdentityClientId string = managedIdentity.properties.clientId
output logAnalyticsWorkspaceId string = logAnalytics.id
output containerAppEnvironmentId string = containerAppEnvironment.id
output containerAppId string = containerApp.id