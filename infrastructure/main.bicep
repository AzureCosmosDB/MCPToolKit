@description('Location for all resources')
param location string = resourceGroup().location

@description('Name for the Azure Container App')
param containerAppName string = 'mcp-demo-app'

@description('Environment name for the Container Apps Environment')
param environmentName string = 'mcp-toolkit-env'

@description('Container registry name')
param containerRegistryName string = 'mcpdemo${uniqueString(resourceGroup().id)}'

@description('Use an existing Azure Container Registry instead of creating one in this resource group')
param useExistingAcr bool = false

@description('Existing ACR name (required when useExistingAcr=true)')
param existingAcrName string = ''

@description('Resource group that contains the existing ACR (optional, defaults to current resource group)')
param existingAcrResourceGroup string = ''

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

@description('Azure Cosmos DB endpoint URL')
param cosmosEndpoint string = ''

@description('Optional: Embedding service endpoint URL. Supports Azure AI Services, Azure AI Foundry, or OpenAI. Only needed for vector_search / hybrid_search tools.')
param azureAiServiceEndpoint string = ''

@description('Optional: Azure OpenAI embedding deployment name. Only needed for vector_search / hybrid_search tools.')
param embeddingDeploymentName string = ''

// NOTE: Entra App creation has been moved to the Setup-Permissions.ps1 script
// for better reliability. The script will create the app if it doesn't exist.

var resolvedAcrResourceGroup = empty(existingAcrResourceGroup) ? resourceGroup().name : existingAcrResourceGroup

// Container Registry
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
    type: 'SystemAssigned'
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
          server: useExistingAcr ? existingContainerRegistry!.properties.loginServer : containerRegistry!.properties.loginServer
          username: useExistingAcr ? existingContainerRegistry!.name : containerRegistry!.name
          passwordSecretRef: 'registry-password'
        }
      ]
      secrets: [
        {
          name: 'registry-password'
          value: useExistingAcr ? existingContainerRegistry!.listCredentials().passwords[0].value : containerRegistry!.listCredentials().passwords[0].value
        }
      ]
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
              name: 'AzureAd__TenantId'
              value: tenant().tenantId
            }
            {
              name: 'COSMOS_ENDPOINT'
              value: cosmosEndpoint
            }
            {
              name: 'OPENAI_ENDPOINT'
              value: azureAiServiceEndpoint
            }
            {
              name: 'OPENAI_EMBEDDING_DEPLOYMENT'
              value: embeddingDeploymentName
            }
            // NOTE: AzureAd__ClientId and AzureAd__Audience will be set by deployment script
            // after the Entra app is created
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
  tags: commonTags
}

// Outputs for azd and other consumers
output AZURE_LOCATION string = location
output AZURE_TENANT_ID string = tenant().tenantId
output AZURE_SUBSCRIPTION_ID string = subscription().subscriptionId

// Infrastructure outputs
output RESOURCE_GROUP_NAME string = resourceGroup().name
output CONTAINER_REGISTRY_LOGIN_SERVER string = useExistingAcr ? existingContainerRegistry!.properties.loginServer : containerRegistry!.properties.loginServer
output CONTAINER_REGISTRY_NAME string = useExistingAcr ? existingContainerRegistry!.name : containerRegistry!.name
output CONTAINER_APP_NAME string = containerApp.name
output CONTAINER_APP_URL string = 'https://${containerApp.properties.configuration.ingress.fqdn}'
output CONTAINER_APP_PRINCIPAL_ID string = containerApp.identity.principalId
output AZURE_CONTAINER_APP_ENVIRONMENT_ID string = containerAppEnvironment.id

// Note: Entra app outputs will be displayed by Setup-Permissions.ps1 script
