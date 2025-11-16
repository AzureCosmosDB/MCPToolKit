using Microsoft.Azure.Cosmos;
using System.Text.Json;
using Azure.Identity;
using System.Text.RegularExpressions;
using Azure.AI.OpenAI;

namespace AzureCosmosDB.MCP.Toolkit.Services;

public class CosmosDbToolsService
{
    private readonly CosmosClient _cosmosClient;
    private readonly ILogger<CosmosDbToolsService> _logger;
    private readonly IConfiguration _configuration;

    public CosmosDbToolsService(
        CosmosClient cosmosClient, 
        ILogger<CosmosDbToolsService> logger,
        IConfiguration configuration)
    {
        _cosmosClient = cosmosClient ?? throw new ArgumentNullException(nameof(cosmosClient));
        _logger = logger ?? throw new ArgumentNullException(nameof(logger));
        _configuration = configuration ?? throw new ArgumentNullException(nameof(configuration));
    }
    
    // Helper method to validate required parameter
    private void ValidateRequiredParameter(string value, string paramName)
    {
        if (string.IsNullOrWhiteSpace(value))
        {
            throw new ArgumentException($"Parameter '{paramName}' is required.", paramName);
        }
    }

    public async Task<object> ListDatabases(CancellationToken cancellationToken = default)
    {
        try
        {
            _logger.LogInformation("Listing databases from Cosmos DB");

            var results = new List<string>();
            var iterator = _cosmosClient.GetDatabaseQueryIterator<DatabaseProperties>();
            while (iterator.HasMoreResults)
            {
                var page = await iterator.ReadNextAsync(cancellationToken);
                foreach (var db in page)
                {
                    results.Add(db.Id);
                }
            }

            _logger.LogInformation("Successfully retrieved {Count} databases", results.Count);
            return results;
        }
        catch (CosmosException cex)
        {
            _logger.LogError(cex, "Cosmos DB error listing databases: {StatusCode}", cex.StatusCode);
            return new { error = cex.Message, statusCode = (int)cex.StatusCode };
        }
        catch (Exception ex)
        {
            _logger.LogError(ex, "Error listing databases");
            return new { error = ex.Message };
        }
    }

    public async Task<object> ListCollections(string databaseId, CancellationToken cancellationToken = default)
    {
        try
        {
            ValidateRequiredParameter(databaseId, nameof(databaseId));

            _logger.LogInformation("Listing collections for database: {DatabaseId}", databaseId);

            var db = _cosmosClient.GetDatabase(databaseId);
            var results = new List<string>();
            var iterator = db.GetContainerQueryIterator<ContainerProperties>();
            while (iterator.HasMoreResults)
            {
                var page = await iterator.ReadNextAsync(cancellationToken);
                foreach (var c in page)
                {
                    results.Add(c.Id);
                }
            }

            _logger.LogInformation("Successfully retrieved {Count} collections from database {DatabaseId}", results.Count, databaseId);
            return results;
        }
        catch (ArgumentException ex)
        {
            _logger.LogWarning(ex, "Invalid parameter: {Message}", ex.Message);
            return new { error = ex.Message };
        }
        catch (CosmosException cex)
        {
            _logger.LogError(cex, "Cosmos DB error listing collections for database {DatabaseId}: {StatusCode}", databaseId, cex.StatusCode);
            return new { error = cex.Message, statusCode = (int)cex.StatusCode };
        }
        catch (Exception ex)
        {
            _logger.LogError(ex, "Error listing collections for database {DatabaseId}", databaseId);
            return new { error = ex.Message };
        }
    }

    public async Task<object> GetRecentDocuments(string databaseId, string containerId, int n, CancellationToken cancellationToken = default)
    {
        try
        {
            ValidateRequiredParameter(databaseId, nameof(databaseId));
            ValidateRequiredParameter(containerId, nameof(containerId));
            
            if (n < 1 || n > 20)
            {
                return new { error = "Parameter 'n' must be a whole number between 1 and 20." };
            }

            _logger.LogInformation("Getting {Count} recent documents from {DatabaseId}/{ContainerId}", n, databaseId, containerId);

            var container = _cosmosClient.GetContainer(databaseId, containerId);
            var queryText = $"SELECT TOP {n} * FROM c ORDER BY c._ts DESC";
            
            using var streamIterator = container.GetItemQueryStreamIterator(
                new QueryDefinition(queryText),
                requestOptions: new QueryRequestOptions { MaxItemCount = n }
            );

            var results = new List<System.Text.Json.JsonElement>();
            while (streamIterator.HasMoreResults && results.Count < n)
            {
                using var response = await streamIterator.ReadNextAsync(cancellationToken);
                using var stream = response.Content;
                using var document = await System.Text.Json.JsonDocument.ParseAsync(stream, cancellationToken: cancellationToken);
                
                var documents = document.RootElement.GetProperty("Documents");
                foreach (var doc in documents.EnumerateArray())
                {
                    results.Add(doc.Clone());
                    if (results.Count >= n) break;
                }
            }

            _logger.LogInformation("Successfully retrieved {Count} recent documents", results.Count);
            return results;
        }
        catch (ArgumentException ex)
        {
            _logger.LogWarning(ex, "Invalid parameter: {Message}", ex.Message);
            return new { error = ex.Message };
        }
        catch (CosmosException cex)
        {
            _logger.LogError(cex, "Cosmos DB error getting recent documents: {StatusCode}", cex.StatusCode);
            return new { error = cex.Message, statusCode = (int)cex.StatusCode };
        }
        catch (Exception ex)
        {
            _logger.LogError(ex, "Error getting recent documents");
            return new { error = ex.Message };
        }
    }

    public async Task<object> FindDocumentByID(string databaseId, string containerId, string id, CancellationToken cancellationToken = default)
    {
        try
        {
            ValidateRequiredParameter(databaseId, nameof(databaseId));
            ValidateRequiredParameter(containerId, nameof(containerId));
            ValidateRequiredParameter(id, nameof(id));

            _logger.LogInformation("Finding document by ID {Id} in {DatabaseId}/{ContainerId}", id, databaseId, containerId);

            var container = _cosmosClient.GetContainer(databaseId, containerId);
            var queryText = "SELECT * FROM c WHERE c.id = @id";
            var query = new QueryDefinition(queryText).WithParameter("@id", id);

            using var streamIterator = container.GetItemQueryStreamIterator(
                query,
                requestOptions: new QueryRequestOptions { MaxItemCount = 1 }
            );

            while (streamIterator.HasMoreResults)
            {
                using var response = await streamIterator.ReadNextAsync(cancellationToken);
                using var stream = response.Content;
                using var document = await System.Text.Json.JsonDocument.ParseAsync(stream, cancellationToken: cancellationToken);
                
                var documents = document.RootElement.GetProperty("Documents");
                if (documents.GetArrayLength() > 0)
                {
                    _logger.LogInformation("Document found with ID {Id}", id);
                    return documents[0].Clone();
                }
            }

            _logger.LogInformation("No document found with ID {Id}", id);
            return new { message = "No document found with the specified id." };
        }
        catch (ArgumentException ex)
        {
            _logger.LogWarning(ex, "Invalid parameter: {Message}", ex.Message);
            return new { error = ex.Message };
        }
        catch (CosmosException cex)
        {
            _logger.LogError(cex, "Cosmos DB error finding document: {StatusCode}", cex.StatusCode);
            return new { error = cex.Message, statusCode = (int)cex.StatusCode };
        }
        catch (Exception ex)
        {
            _logger.LogError(ex, "Error finding document");
            return new { error = ex.Message };
        }
    }

    public async Task<object> TextSearch(string databaseId, string containerId, string property, string searchPhrase, int n, CancellationToken cancellationToken = default)
    {
        try
        {
            ValidateRequiredParameter(databaseId, nameof(databaseId));
            ValidateRequiredParameter(containerId, nameof(containerId));
            ValidateRequiredParameter(property, nameof(property));
            
            if (n < 1 || n > 20)
            {
                return new { error = "Parameter 'n' must be a whole number between 1 and 20." };
            }

            var propPattern = new Regex(@"^[A-Za-z_][A-Za-z0-9_]*(\.[A-Za-z_][A-Za-z0-9_]*)*$");
            if (!propPattern.IsMatch(property))
            {
                return new { error = "Invalid property name. Use dot notation with letters, digits, and underscores only (e.g., name or profile.name)." };
            }

            _logger.LogInformation("Text search for '{SearchPhrase}' in {DatabaseId}/{ContainerId} property {Property}", searchPhrase, databaseId, containerId, property);

            var container = _cosmosClient.GetContainer(databaseId, containerId);
            var queryText = $"SELECT TOP {n} * FROM c WHERE FullTextContains(c.{property}, @searchPhrase) ";
            var query = new QueryDefinition(queryText).WithParameter("@searchPhrase", searchPhrase);

            using var streamIterator = container.GetItemQueryStreamIterator(
                query,
                requestOptions: new QueryRequestOptions { MaxItemCount = n }
            );

            var results = new List<System.Text.Json.JsonElement>();
            while (streamIterator.HasMoreResults && results.Count < n)
            {
                using var response = await streamIterator.ReadNextAsync(cancellationToken);
                using var stream = response.Content;
                using var document = await System.Text.Json.JsonDocument.ParseAsync(stream, cancellationToken: cancellationToken);
                
                var documents = document.RootElement.GetProperty("Documents");
                foreach (var doc in documents.EnumerateArray())
                {
                    results.Add(doc.Clone());
                    if (results.Count >= n) break;
                }
            }

            _logger.LogInformation("Text search returned {Count} results", results.Count);
            return results;
        }
        catch (ArgumentException ex)
        {
            _logger.LogWarning(ex, "Invalid parameter: {Message}", ex.Message);
            return new { error = ex.Message };
        }
        catch (CosmosException cex)
        {
            _logger.LogError(cex, "Cosmos DB error in text search: {StatusCode}", cex.StatusCode);
            return new { error = cex.Message, statusCode = (int)cex.StatusCode };
        }
        catch (Exception ex)
        {
            _logger.LogError(ex, "Error in text search");
            return new { error = ex.Message };
        }
    }

    public async Task<object> VectorSearch(string databaseId, string containerId, string searchText, string vectorProperty, string selectProperties, int topN, CancellationToken cancellationToken = default)
    {
        try
        {
            // Get configuration values
            var openaiEndpoint = _configuration["OPENAI_ENDPOINT"] ?? Environment.GetEnvironmentVariable("OPENAI_ENDPOINT");
            var embeddingDeployment = _configuration["OPENAI_EMBEDDING_DEPLOYMENT"] ?? Environment.GetEnvironmentVariable("OPENAI_EMBEDDING_DEPLOYMENT");
            var embeddingDimensionsStr = _configuration["OPENAI_EMBEDDING_DIMENSIONS"] ?? Environment.GetEnvironmentVariable("OPENAI_EMBEDDING_DIMENSIONS");

            // Validate environment variables
            if (string.IsNullOrWhiteSpace(openaiEndpoint))
            {
                return new { error = "Missing required environment variable OPENAI_ENDPOINT." };
            }
            if (string.IsNullOrWhiteSpace(embeddingDeployment))
            {
                return new { error = "Missing required environment variable OPENAI_EMBEDDING_DEPLOYMENT." };
            }

            // Parse embedding dimensions if provided (must be a positive number to be valid)
            int? embeddingDimensions = null;
            if (!string.IsNullOrWhiteSpace(embeddingDimensionsStr) && int.TryParse(embeddingDimensionsStr, out int parsedDimensions) && parsedDimensions > 0)
            {
                embeddingDimensions = parsedDimensions;
            }

            // Validate parameters
            ValidateRequiredParameter(databaseId, nameof(databaseId));
            ValidateRequiredParameter(containerId, nameof(containerId));
            ValidateRequiredParameter(searchText, nameof(searchText));
            ValidateRequiredParameter(vectorProperty, nameof(vectorProperty));
            ValidateRequiredParameter(selectProperties, nameof(selectProperties));
            
            if (topN < 1 || topN > 50)
            {
                return new { error = "Parameter 'topN' must be a whole number between 1 and 50." };
            }

            if (selectProperties.Trim() == "*" || selectProperties.Contains("*"))
            {
                return new { error = "Parameter 'selectProperties' cannot contain '*' wildcard. Please specify explicit property names separated by commas." };
            }

            var propPattern = new Regex(@"^[A-Za-z_][A-Za-z0-9_]*(\.[A-Za-z_][A-Za-z0-9_]*)*$");
            
            if (!propPattern.IsMatch(vectorProperty))
            {
                return new { error = "Invalid vectorProperty name. Use dot notation with letters, digits, and underscores only (e.g., 'vector' or 'embeddings')." };
            }

            var properties = selectProperties.Split(',', StringSplitOptions.RemoveEmptyEntries)
                .Select(p => p.Trim())
                .ToArray();
            
            foreach (var prop in properties)
            {
                if (!propPattern.IsMatch(prop))
                {
                    return new { error = $"Invalid property name '{prop}' in selectProperties. Use dot notation with letters, digits, and underscores only (e.g., 'id', 'title', 'metadata.author')." };
                }
            }

            _logger.LogInformation("Vector search for '{SearchText}' in {DatabaseId}/{ContainerId}", searchText, databaseId, containerId);

            // Generate embedding using Azure OpenAI
            float[] embedding;
            try
            {
                _logger.LogInformation("OpenAI Endpoint: {Endpoint}, Deployment: {Deployment}", openaiEndpoint, embeddingDeployment);
                
                var credential = new DefaultAzureCredential();
                var openaiClient = new AzureOpenAIClient(new Uri(openaiEndpoint), credential);
                
                _logger.LogInformation("Getting embedding client for deployment: {Deployment}", embeddingDeployment);
                var embeddingClient = openaiClient.GetEmbeddingClient(embeddingDeployment);
                
                _logger.LogInformation("Generating embedding for text: {Text}{DimensionsInfo}", 
                    searchText, 
                    embeddingDimensions.HasValue ? $" with {embeddingDimensions.Value} dimensions" : "");
                // Generate embedding with optional dimensions parameter
                var embeddingResponse = embeddingDimensions.HasValue
                    ? await embeddingClient.GenerateEmbeddingAsync(searchText, new OpenAI.Embeddings.EmbeddingGenerationOptions { Dimensions = embeddingDimensions.Value }, cancellationToken)
                    : await embeddingClient.GenerateEmbeddingAsync(searchText, cancellationToken: cancellationToken);
                
                embedding = embeddingResponse.Value.ToFloats().ToArray();
                _logger.LogInformation("Generated embedding with {Dimensions} dimensions", embedding.Length);
            }
            catch (Exception ex)
            {
                _logger.LogError(ex, "Failed to generate embedding. Endpoint: {Endpoint}, Deployment: {Deployment}", openaiEndpoint, embeddingDeployment);
                return new { error = $"Failed to generate embedding: {ex.Message}" };
            }

            var container = _cosmosClient.GetContainer(databaseId, containerId);

            var selectClause = string.Join(", ", properties.Select(p => $"c.{p}"));

            var queryText = $@"
                SELECT TOP @topN {selectClause}, VectorDistance(c.{vectorProperty}, @embedding) as _score
                FROM c
                ORDER BY VectorDistance(c.{vectorProperty}, @embedding)";

            var queryDefinition = new QueryDefinition(queryText)
                .WithParameter("@topN", topN)
                .WithParameter("@embedding", embedding);

            using var streamIterator = container.GetItemQueryStreamIterator(
                queryDefinition,
                requestOptions: new QueryRequestOptions { MaxItemCount = topN }
            );

            var results = new List<System.Text.Json.JsonElement>();
            while (streamIterator.HasMoreResults && results.Count < topN)
            {
                using var response = await streamIterator.ReadNextAsync(cancellationToken);
                using var stream = response.Content;
                using var document = await System.Text.Json.JsonDocument.ParseAsync(stream, cancellationToken: cancellationToken);
                
                var documents = document.RootElement.GetProperty("Documents");
                foreach (var doc in documents.EnumerateArray())
                {
                    results.Add(doc.Clone());
                    if (results.Count >= topN) break;
                }
            }

            _logger.LogInformation("Vector search returned {Count} results", results.Count);
            return results;
        }
        catch (ArgumentException ex)
        {
            _logger.LogWarning(ex, "Invalid parameter: {Message}", ex.Message);
            return new { error = ex.Message };
        }
        catch (CosmosException cex)
        {
            _logger.LogError(cex, "Cosmos DB error in vector search: {StatusCode}", cex.StatusCode);
            return new { error = cex.Message, statusCode = (int)cex.StatusCode };
        }
        catch (Exception ex)
        {
            _logger.LogError(ex, "Error in vector search");
            return new { error = ex.Message };
        }
    }

    public async Task<object> GetApproximateSchema(string databaseId, string containerId, CancellationToken cancellationToken = default)
    {
        try
        {
            ValidateRequiredParameter(databaseId, nameof(databaseId));
            ValidateRequiredParameter(containerId, nameof(containerId));

            _logger.LogInformation("Getting approximate schema for {DatabaseId}/{ContainerId}", databaseId, containerId);

            var container = _cosmosClient.GetContainer(databaseId, containerId);
            var queryText = "SELECT TOP 10 * FROM c";
            using var streamIterator = container.GetItemQueryStreamIterator(
                new QueryDefinition(queryText),
                requestOptions: new QueryRequestOptions { MaxItemCount = 10 }
            );

            var typeMap = new Dictionary<string, HashSet<string>>(StringComparer.OrdinalIgnoreCase);
            var countMap = new Dictionary<string, int>(StringComparer.OrdinalIgnoreCase);
            int sampleCount = 0;

            while (streamIterator.HasMoreResults && sampleCount < 10)
            {
                using var response = await streamIterator.ReadNextAsync(cancellationToken);
                using var stream = response.Content;
                using var document = await System.Text.Json.JsonDocument.ParseAsync(stream, cancellationToken: cancellationToken);
                
                var documents = document.RootElement.GetProperty("Documents");
                foreach (var doc in documents.EnumerateArray())
                {
                    if (doc.ValueKind != JsonValueKind.Object) continue;
                    sampleCount++;
                        
                    foreach (var prop in doc.EnumerateObject())
                        {
                            var name = prop.Name;
                            var kind = prop.Value.ValueKind;
                            string type = kind switch
                            {
                                JsonValueKind.String => "string",
                                JsonValueKind.Number => "number",
                                JsonValueKind.True => "boolean",
                                JsonValueKind.False => "boolean",
                                JsonValueKind.Object => "object",
                                JsonValueKind.Array => "array",
                                JsonValueKind.Null => "null",
                                _ => "unknown"
                            };

                            if (!typeMap.TryGetValue(name, out HashSet<string>? set))
                            {
                                set = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
                                typeMap[name] = set;
                            }
                            set!.Add(type);

                            countMap.TryGetValue(name, out int current);
                            countMap[name] = current + 1;
                        }

                    if (sampleCount >= 10) break;
                }
            }

            if (sampleCount == 0)
            {
                _logger.LogWarning("No documents found to infer schema");
                return new { message = "No documents found to infer schema." };
            }

            var properties = new List<object>();
            foreach (var kvp in typeMap.OrderBy(k => k.Key, StringComparer.OrdinalIgnoreCase))
            {
                var name = kvp.Key;
                var types = kvp.Value.OrderBy(t => t).ToArray();
                var typeStr = string.Join(" | ", types);
                countMap.TryGetValue(name, out int appearCount);
                var description = $"Appears in {appearCount}/{sampleCount} sampled documents.";
                properties.Add(new { name, type = typeStr, description });
            }

            _logger.LogInformation("Schema approximation complete. Found {PropertyCount} unique properties from {SampleCount} documents", properties.Count, sampleCount);
            var result = new { sampleSize = sampleCount, properties };
            return result;
        }
        catch (ArgumentException ex)
        {
            _logger.LogWarning(ex, "Invalid parameter: {Message}", ex.Message);
            return new { error = ex.Message };
        }
        catch (CosmosException cex)
        {
            _logger.LogError(cex, "Cosmos DB error getting approximate schema: {StatusCode}", cex.StatusCode);
            return new { error = cex.Message, statusCode = (int)cex.StatusCode };
        }
        catch (Exception ex)
        {
            _logger.LogError(ex, "Error getting approximate schema");
            return new { error = ex.Message };
        }
    }
}
