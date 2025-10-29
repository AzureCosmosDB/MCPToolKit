using Microsoft.Azure.Cosmos;
using System.Text.Json;
using Azure.Identity;
using System.Text.RegularExpressions;
using Azure.AI.OpenAI;

namespace AzureCosmosDB.MCP.Toolkit.Services;

public class CosmosDbToolsService
{
    private readonly ILogger<CosmosDbToolsService> _logger;

    public CosmosDbToolsService(ILogger<CosmosDbToolsService> logger)
    {
        _logger = logger;
    }

    public async Task<object> ListDatabases()
    {
        try
        {
            var endpoint = Environment.GetEnvironmentVariable("COSMOS_ENDPOINT");
            if (string.IsNullOrWhiteSpace(endpoint))
            {
                return new { error = "Missing required environment variable COSMOS_ENDPOINT." };
            }

            var credential = new DefaultAzureCredential();
            using var client = new CosmosClient(endpoint, credential, new CosmosClientOptions
            {
                ApplicationName = "AzureCosmosDBMCP"
            });

            var results = new List<string>();
            var iterator = client.GetDatabaseQueryIterator<DatabaseProperties>();
            while (iterator.HasMoreResults)
            {
                var page = await iterator.ReadNextAsync();
                foreach (var db in page)
                {
                    results.Add(db.Id);
                }
            }

            return results;
        }
        catch (CosmosException cex)
        {
            return new { error = cex.Message, statusCode = (int)cex.StatusCode };
        }
        catch (Exception ex)
        {
            return new { error = ex.Message };
        }
    }

    public async Task<object> ListCollections(string databaseId)
    {
        try
        {
            var endpoint = Environment.GetEnvironmentVariable("COSMOS_ENDPOINT");
            if (string.IsNullOrWhiteSpace(endpoint))
            {
                return new { error = "Missing required environment variable COSMOS_ENDPOINT." };
            }

            if (string.IsNullOrWhiteSpace(databaseId))
            {
                return new { error = "Parameter 'databaseId' is required." };
            }

            var credential = new DefaultAzureCredential();
            using var client = new CosmosClient(endpoint, credential, new CosmosClientOptions
            {
                ApplicationName = "AzureCosmosDBMCP"
            });

            var db = client.GetDatabase(databaseId);
            var results = new List<string>();
            var iterator = db.GetContainerQueryIterator<ContainerProperties>();
            while (iterator.HasMoreResults)
            {
                var page = await iterator.ReadNextAsync();
                foreach (var c in page)
                {
                    results.Add(c.Id);
                }
            }

            return results;
        }
        catch (CosmosException cex)
        {
            return new { error = cex.Message, statusCode = (int)cex.StatusCode };
        }
        catch (Exception ex)
        {
            return new { error = ex.Message };
        }
    }

    public async Task<object> GetRecentDocuments(string databaseId, string containerId, int n)
    {
        try
        {
            var endpoint = Environment.GetEnvironmentVariable("COSMOS_ENDPOINT");
            if (string.IsNullOrWhiteSpace(endpoint))
            {
                return new { error = "Missing required environment variable COSMOS_ENDPOINT." };
            }
            if (string.IsNullOrWhiteSpace(databaseId) || string.IsNullOrWhiteSpace(containerId))
            {
                return new { error = "Parameters 'databaseId' and 'containerId' are required." };
            }
            if (n < 1 || n > 20)
            {
                return new { error = "Parameter 'n' must be a whole number between 1 and 20." };
            }

            var credential = new DefaultAzureCredential();
            using var client = new CosmosClient(endpoint, credential, new CosmosClientOptions
            {
                ApplicationName = "AzureCosmosDBMCP"
            });

            var container = client.GetContainer(databaseId, containerId);
            var queryText = $"SELECT TOP {n} * FROM c ORDER BY c._ts DESC";
            var iterator = container.GetItemQueryIterator<dynamic>(
                new QueryDefinition(queryText),
                requestOptions: new QueryRequestOptions { MaxItemCount = n }
            );

            var results = new List<object>();
            while (iterator.HasMoreResults && results.Count < n)
            {
                var page = await iterator.ReadNextAsync();
                foreach (var doc in page)
                {
                    results.Add(doc);
                    if (results.Count >= n) break;
                }
            }

            return results;
        }
        catch (CosmosException cex)
        {
            return new { error = cex.Message, statusCode = (int)cex.StatusCode };
        }
        catch (Exception ex)
        {
            return new { error = ex.Message };
        }
    }

    public async Task<object> FindDocumentByID(string databaseId, string containerId, string id)
    {
        try
        {
            var endpoint = Environment.GetEnvironmentVariable("COSMOS_ENDPOINT");
            if (string.IsNullOrWhiteSpace(endpoint))
            {
                return new { error = "Missing required environment variable COSMOS_ENDPOINT." };
            }
            if (string.IsNullOrWhiteSpace(databaseId) || string.IsNullOrWhiteSpace(containerId))
            {
                return new { error = "Parameters 'databaseId' and 'containerId' are required." };
            }
            if (string.IsNullOrWhiteSpace(id))
            {
                return new { error = "Parameter 'id' is required." };
            }

            var credential = new DefaultAzureCredential();
            using var client = new CosmosClient(endpoint, credential, new CosmosClientOptions
            {
                ApplicationName = "AzureCosmosDBMCP"
            });

            var container = client.GetContainer(databaseId, containerId);
            var queryText = "SELECT * FROM c WHERE c.id = @id";
            var query = new QueryDefinition(queryText).WithParameter("@id", id);

            var iterator = container.GetItemQueryIterator<dynamic>(query, requestOptions: new QueryRequestOptions { MaxItemCount = 1 });

            while (iterator.HasMoreResults)
            {
                var page = await iterator.ReadNextAsync();
                foreach (var doc in page)
                {
                    return doc;
                }
            }

            return new { message = "No document found with the specified id." };
        }
        catch (CosmosException cex)
        {
            return new { error = cex.Message, statusCode = (int)cex.StatusCode };
        }
        catch (Exception ex)
        {
            return new { error = ex.Message };
        }
    }

    public async Task<object> TextSearch(string databaseId, string containerId, string property, string searchPhrase, int n)
    {
        try
        {
            var endpoint = Environment.GetEnvironmentVariable("COSMOS_ENDPOINT");
            if (string.IsNullOrWhiteSpace(endpoint))
            {
                return new { error = "Missing required environment variable COSMOS_ENDPOINT." };
            }
            if (string.IsNullOrWhiteSpace(databaseId) || string.IsNullOrWhiteSpace(containerId))
            {
                return new { error = "Parameters 'databaseId' and 'containerId' are required." };
            }
            if (string.IsNullOrWhiteSpace(property))
            {
                return new { error = "Parameter 'property' is required." };
            }
            if (n < 1 || n > 20)
            {
                return new { error = "Parameter 'n' must be a whole number between 1 and 20." };
            }

            var propPattern = new Regex(@"^[A-Za-z_][A-Za-z0-9_]*(\.[A-Za-z_][A-Za-z0-9_]*)*$");
            if (!propPattern.IsMatch(property))
            {
                return new { error = "Invalid property name. Use dot notation with letters, digits, and underscores only (e.g., name or profile.name)." };
            }

            var credential = new DefaultAzureCredential();
            using var client = new CosmosClient(endpoint, credential, new CosmosClientOptions
            {
                ApplicationName = "AzureCosmosDBMCP"
            });

            var container = client.GetContainer(databaseId, containerId);
            var queryText = $"SELECT TOP {n} * FROM c WHERE FullTextContains(c.{property}, @searchPhrase) ";
            var query = new QueryDefinition(queryText).WithParameter("@searchPhrase", searchPhrase);

            var iterator = container.GetItemQueryIterator<dynamic>(query, requestOptions: new QueryRequestOptions { MaxItemCount = n });

            var results = new List<object>();
            while (iterator.HasMoreResults && results.Count < n)
            {
                var page = await iterator.ReadNextAsync();
                foreach (var doc in page)
                {
                    results.Add(doc);
                    if (results.Count >= n) break;
                }
            }

            return results;
        }
        catch (CosmosException cex)
        {
            return new { error = cex.Message, statusCode = (int)cex.StatusCode };
        }
        catch (Exception ex)
        {
            return new { error = ex.Message };
        }
    }

    public async Task<object> VectorSearch(string databaseId, string containerId, string searchText, string vectorProperty, string selectProperties, int topN)
    {
        try
        {
            var cosmosEndpoint = Environment.GetEnvironmentVariable("COSMOS_ENDPOINT");
            // OPENAI_ENDPOINT can be either an AI Foundry project endpoint or legacy Azure OpenAI endpoint
            // AI Foundry projects expose OpenAI-compatible endpoints (recommended)
            var openaiEndpoint = Environment.GetEnvironmentVariable("OPENAI_ENDPOINT");
            var embeddingDeployment = Environment.GetEnvironmentVariable("OPENAI_EMBEDDING_DEPLOYMENT");

            if (string.IsNullOrWhiteSpace(cosmosEndpoint))
            {
                return new { error = "Missing required environment variable COSMOS_ENDPOINT." };
            }
            if (string.IsNullOrWhiteSpace(openaiEndpoint))
            {
                return new { error = "Missing required environment variable OPENAI_ENDPOINT." };
            }
            if (string.IsNullOrWhiteSpace(embeddingDeployment))
            {
                return new { error = "Missing required environment variable OPENAI_EMBEDDING_DEPLOYMENT." };
            }

            if (string.IsNullOrWhiteSpace(databaseId) || string.IsNullOrWhiteSpace(containerId))
            {
                return new { error = "Parameters 'databaseId' and 'containerId' are required." };
            }
            if (string.IsNullOrWhiteSpace(searchText))
            {
                return new { error = "Parameter 'searchText' is required." };
            }
            if (string.IsNullOrWhiteSpace(vectorProperty))
            {
                return new { error = "Parameter 'vectorProperty' is required." };
            }
            if (string.IsNullOrWhiteSpace(selectProperties))
            {
                return new { error = "Parameter 'selectProperties' is required." };
            }
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

            var credential = new DefaultAzureCredential();

            float[] embedding;
            try
            {
                var openaiClient = new AzureOpenAIClient(new Uri(openaiEndpoint), credential);
                var embeddingClient = openaiClient.GetEmbeddingClient(embeddingDeployment);
                var embeddingResponse = await embeddingClient.GenerateEmbeddingAsync(searchText);
                embedding = embeddingResponse.Value.ToFloats().ToArray();
            }
            catch (Exception ex)
            {
                return new { error = $"Failed to generate embedding: {ex.Message}" };
            }

            using var cosmosClient = new CosmosClient(cosmosEndpoint, credential, new CosmosClientOptions
            {
                ApplicationName = "AzureCosmosDBMCP"
            });

            var container = cosmosClient.GetContainer(databaseId, containerId);

            var selectClause = string.Join(", ", properties.Select(p => $"c.{p}"));

            var queryText = $@"
                SELECT TOP @topN {selectClause}, VectorDistance(c.{vectorProperty}, @embedding) as _score
                FROM c
                ORDER BY VectorDistance(c.{vectorProperty}, @embedding)";

            var queryDefinition = new QueryDefinition(queryText)
                .WithParameter("@topN", topN)
                .WithParameter("@embedding", embedding);

            var iterator = container.GetItemQueryIterator<dynamic>(
                queryDefinition,
                requestOptions: new QueryRequestOptions { MaxItemCount = topN }
            );

            var results = new List<object>();
            while (iterator.HasMoreResults && results.Count < topN)
            {
                var page = await iterator.ReadNextAsync();
                foreach (var doc in page)
                {
                    results.Add(doc);
                    if (results.Count >= topN) break;
                }
            }

            return results;
        }
        catch (CosmosException cex)
        {
            return new { error = cex.Message, statusCode = (int)cex.StatusCode };
        }
        catch (Exception ex)
        {
            return new { error = ex.Message };
        }
    }

    public async Task<object> GetApproximateSchema(string databaseId, string containerId)
    {
        try
        {
            var endpoint = Environment.GetEnvironmentVariable("COSMOS_ENDPOINT");
            if (string.IsNullOrWhiteSpace(endpoint))
            {
                return new { error = "Missing required environment variable COSMOS_ENDPOINT." };
            }
            if (string.IsNullOrWhiteSpace(databaseId) || string.IsNullOrWhiteSpace(containerId))
            {
                return new { error = "Parameters 'databaseId' and 'containerId' are required." };
            }

            var credential = new DefaultAzureCredential();
            using var client = new CosmosClient(endpoint, credential, new CosmosClientOptions
            {
                ApplicationName = "AzureCosmosDBMCP"
            });

            var container = client.GetContainer(databaseId, containerId);
            var queryText = "SELECT TOP 10 * FROM c";
            var iterator = container.GetItemQueryIterator<dynamic>(
                new QueryDefinition(queryText),
                requestOptions: new QueryRequestOptions { MaxItemCount = 10 }
            );

            var typeMap = new Dictionary<string, HashSet<string>>(StringComparer.OrdinalIgnoreCase);
            var countMap = new Dictionary<string, int>(StringComparer.OrdinalIgnoreCase);
            int sampleCount = 0;

            while (iterator.HasMoreResults && sampleCount < 10)
            {
                var page = await iterator.ReadNextAsync();
                foreach (var doc in page)
                {
                    var json = doc?.ToString();
                    if (string.IsNullOrWhiteSpace(json)) continue;

                    try
                    {
                        using var parsed = JsonDocument.Parse(json);
                        if (parsed.RootElement.ValueKind != JsonValueKind.Object) continue;
                        sampleCount++;
                        
                        foreach (var prop in parsed.RootElement.EnumerateObject())
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
                    }
                    catch
                    {
                        // Ignore malformed JSON rows
                    }

                    if (sampleCount >= 10) break;
                }
            }

            if (sampleCount == 0)
            {
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

            var result = new { sampleSize = sampleCount, properties };
            return result;
        }
        catch (CosmosException cex)
        {
            return new { error = cex.Message, statusCode = (int)cex.StatusCode };
        }
        catch (Exception ex)
        {
            return new { error = ex.Message };
        }
    }
}