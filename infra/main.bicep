targetScope = 'resourceGroup'

@minLength(3)
@maxLength(12)
param baseName string = 'maint'
param location string = resourceGroup().location
param owner string = 'Rajdev-teach'
param costCenter string = 'learning'
param chatModel string = 'gpt-4o-mini'
param chatModelVersion string = '2024-07-18'
param embeddingModel string = 'text-embedding-3-small'
param embeddingModelVersion string = '1'
param chatDeployment string = 'rag-chat'
param embeddingDeployment string = 'rag-embed'
@allowed(['Standard', 'GlobalStandard'])
param modelSku string = 'Standard'
@minValue(1)
param modelCapacity int = 1
param embeddingDimensions int = 1536
param imageTag string
@secure()
@minLength(24)
param apiAuthToken string

var suffix = uniqueString(subscription().subscriptionId, resourceGroup().id)
var tags = {
  owner: owner
  'cost-center': costCenter
  project: 'manufacturing-maintenance-rag'
  environment: 'lab'
}

resource openai 'Microsoft.CognitiveServices/accounts@2024-10-01' = {
  name: '${baseName}-ai-${suffix}'
  location: location
  kind: 'OpenAI'
  sku: { name: 'S0' }
  tags: tags
  properties: {
    customSubDomainName: '${baseName}-ai-${suffix}'
    publicNetworkAccess: 'Enabled'
    disableLocalAuth: false
  }
}

resource chat 'Microsoft.CognitiveServices/accounts/deployments@2024-10-01' = {
  parent: openai
  name: chatDeployment
  sku: { name: modelSku, capacity: modelCapacity }
  properties: {
    model: { format: 'OpenAI', name: chatModel, version: chatModelVersion }
    versionUpgradeOption: 'NoAutoUpgrade'
  }
}

resource embedding 'Microsoft.CognitiveServices/accounts/deployments@2024-10-01' = {
  parent: openai
  name: embeddingDeployment
  sku: { name: modelSku, capacity: modelCapacity }
  properties: {
    model: { format: 'OpenAI', name: embeddingModel, version: embeddingModelVersion }
    versionUpgradeOption: 'NoAutoUpgrade'
  }
  // The management API serializes deployment changes on an OpenAI account.
  dependsOn: [chat]
}

resource search 'Microsoft.Search/searchServices@2023-11-01' = {
  name: '${baseName}-search-${suffix}'
  location: location
  tags: tags
  sku: { name: 'basic' }
  properties: {
    replicaCount: 1
    partitionCount: 1
    hostingMode: 'default'
    publicNetworkAccess: 'enabled'
    disableLocalAuth: false
  }
}

resource registry 'Microsoft.ContainerRegistry/registries@2023-07-01' = {
  name: '${baseName}acr${suffix}'
  location: location
  tags: tags
  sku: { name: 'Basic' }
  properties: { adminUserEnabled: true }
}

resource plan 'Microsoft.Web/serverfarms@2023-12-01' = {
  name: '${baseName}-plan-${suffix}'
  location: location
  tags: tags
  kind: 'linux'
  sku: { name: 'B1', tier: 'Basic', capacity: 1 }
  properties: { reserved: true }
}

resource web 'Microsoft.Web/sites@2023-12-01' = {
  name: '${baseName}-api-${suffix}'
  location: location
  tags: tags
  kind: 'app,linux,container'
  properties: {
    serverFarmId: plan.id
    httpsOnly: true
    siteConfig: {
      linuxFxVersion: 'DOCKER|${registry.properties.loginServer}/rag-api:${imageTag}'
      alwaysOn: true
      healthCheckPath: '/health'
      minTlsVersion: '1.2'
      ftpsState: 'Disabled'
      appSettings: [
        { name: 'WEBSITES_PORT', value: '8000' }
        { name: 'WEBSITES_ENABLE_APP_SERVICE_STORAGE', value: 'false' }
        { name: 'DOCKER_REGISTRY_SERVER_URL', value: 'https://${registry.properties.loginServer}' }
        { name: 'DOCKER_REGISTRY_SERVER_USERNAME', value: registry.listCredentials().username }
        { name: 'DOCKER_REGISTRY_SERVER_PASSWORD', value: registry.listCredentials().passwords[0].value }
        { name: 'RAG_BACKEND', value: 'azure' }
        { name: 'SERVICE_VERSION', value: imageTag }
        { name: 'MLFLOW_TRACKING_ENABLED', value: 'false' }
        { name: 'API_AUTH_TOKEN', value: apiAuthToken }
        { name: 'AZURE_OPENAI_ENDPOINT', value: openai.properties.endpoint }
        { name: 'AZURE_OPENAI_API_KEY', value: openai.listKeys().key1 }
        { name: 'AZURE_OPENAI_API_VERSION', value: '2024-10-21' }
        { name: 'AZURE_OPENAI_CHAT_DEPLOYMENT', value: chat.name }
        { name: 'AZURE_OPENAI_EMBED_DEPLOYMENT', value: embedding.name }
        { name: 'AZURE_SEARCH_ENDPOINT', value: 'https://${search.name}.search.windows.net' }
        { name: 'AZURE_SEARCH_ADMIN_KEY', value: search.listAdminKeys().primaryKey }
        { name: 'AZURE_SEARCH_INDEX', value: 'maintenance-rag' }
        { name: 'EMBED_DIM', value: string(embeddingDimensions) }
      ]
    }
  }
}

output resourceGroup string = resourceGroup().name
output subscriptionId string = subscription().subscriptionId
output openaiName string = openai.name
output searchName string = search.name
output acrName string = registry.name
output acrLoginServer string = registry.properties.loginServer
output appServiceName string = web.name
output publicUrl string = 'https://${web.properties.defaultHostName}'
output deployedImage string = '${registry.properties.loginServer}/rag-api:${imageTag}'
