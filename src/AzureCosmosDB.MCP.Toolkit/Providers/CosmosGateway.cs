using System.Text;
using System.Text.Json;
using System.Text.Json.Nodes;
using AzureCosmosDB.MCP.Toolkit.Services;
using Microsoft.Azure.Cosmos;

namespace AzureCosmosDB.MCP.Toolkit.Providers;

/// <summary>
/// Cosmos DB implementation of <see cref="ICosmosGateway"/>. Uses stream APIs for reads/writes to
/// avoid POCO coupling, binds all caller-derived values as parameters, and never concatenates input
/// into SQL. Vector/hybrid SQL is built only from configuration-controlled (validated) paths.
/// </summary>
public sealed class CosmosGateway : ICosmosGateway
{
    private static readonly JsonSerializerOptions JsonOptions = new();

    private readonly CosmosClient _client;
    private readonly IConfiguration _configuration;
    private readonly ILogger<CosmosGateway> _logger;

    public CosmosGateway(CosmosClient client, IConfiguration configuration, ILogger<CosmosGateway> logger)
    {
        _client = client;
        _configuration = configuration;
        _logger = logger;
    }

    private Container GetContainer(string database, string container) => _client.GetContainer(database, container);

    private static PartitionKey ToPartitionKey(IReadOnlyList<string> components)
    {
        if (components.Count == 1)
        {
            return new PartitionKey(components[0]);
        }

        var builder = new PartitionKeyBuilder();
        foreach (var component in components)
        {
            builder.Add(component);
        }

        return builder.Build();
    }

    public async Task<JsonNode?> PointReadAsync(string database, string container, string id, IReadOnlyList<string> partitionKey, CancellationToken cancellationToken)
    {
        var c = GetContainer(database, container);
        using var response = await c.ReadItemStreamAsync(id, ToPartitionKey(partitionKey), cancellationToken: cancellationToken);
        if (response.StatusCode == System.Net.HttpStatusCode.NotFound)
        {
            return null;
        }

        response.EnsureSuccessStatusCode();
        return await ParseStreamAsync(response.Content, cancellationToken);
    }

    public async Task<JsonArray> QueryAsync(QueryRequest request, CancellationToken cancellationToken)
    {
        var c = GetContainer(request.Database, request.Container);
        var query = new QueryDefinition(request.Statement);
        foreach (var (name, value) in request.Parameters)
        {
            query.WithParameter(name.StartsWith('@') ? name : "@" + name, ToParameterValue(value));
        }

        var options = new QueryRequestOptions { MaxItemCount = request.MaxItems };
        if (!request.AllowCrossPartition && request.PartitionKey is { Count: > 0 })
        {
            options.PartitionKey = ToPartitionKey(request.PartitionKey);
        }

        using var iterator = c.GetItemQueryStreamIterator(query, requestOptions: options);
        return await DrainAsync(iterator, request.MaxItems, cancellationToken);
    }

    public async Task<JsonArray> TextSearchAsync(string database, string container, string property, string searchText, int maxItems, CancellationToken cancellationToken)
    {
        var c = GetContainer(database, container);
        // 'property' originates from configuration and is validated as a safe identifier path.
        var statement = $"SELECT TOP {maxItems} * FROM c WHERE FullTextContains(c.{property}, @searchPhrase)";
        var query = new QueryDefinition(statement).WithParameter("@searchPhrase", searchText);
        using var iterator = c.GetItemQueryStreamIterator(query, requestOptions: new QueryRequestOptions { MaxItemCount = maxItems });
        return await DrainAsync(iterator, maxItems, cancellationToken);
    }

    public async Task<JsonArray> VectorSearchAsync(SearchRequest request, CancellationToken cancellationToken)
    {
        var embedding = await GenerateEmbeddingAsync(request.SearchText, cancellationToken);
        var c = GetContainer(request.Database, request.Container);
        var select = string.Join(", ", request.Select.Select(p => $"c.{p}"));
        var statement = $"SELECT TOP @topK {select}, VectorDistance(c.{request.VectorPath}, @embedding) AS score " +
                        $"FROM c ORDER BY VectorDistance(c.{request.VectorPath}, @embedding)";
        var query = new QueryDefinition(statement)
            .WithParameter("@topK", request.TopK)
            .WithParameter("@embedding", embedding);
        using var iterator = c.GetItemQueryStreamIterator(query, requestOptions: new QueryRequestOptions { MaxItemCount = request.TopK });
        return await DrainAsync(iterator, request.TopK, cancellationToken);
    }

    public async Task<JsonArray> HybridSearchAsync(SearchRequest request, CancellationToken cancellationToken)
    {
        var embedding = await GenerateEmbeddingAsync(request.SearchText, cancellationToken);
        var c = GetContainer(request.Database, request.Container);
        var select = string.Join(", ", request.Select.Select(p => $"c.{p}"));
        var statement = $"SELECT TOP @topK {select} FROM c " +
                        $"ORDER BY RANK RRF(VectorDistance(c.{request.VectorPath}, @embedding), FullTextScore(c.{request.TextPath}, @searchText))";
        var query = new QueryDefinition(statement)
            .WithParameter("@topK", request.TopK)
            .WithParameter("@embedding", embedding)
            .WithParameter("@searchText", request.SearchText);
        using var iterator = c.GetItemQueryStreamIterator(query, requestOptions: new QueryRequestOptions { MaxItemCount = request.TopK });
        return await DrainAsync(iterator, request.TopK, cancellationToken);
    }

    public async Task<JsonNode?> CreateAsync(string database, string container, JsonObject document, IReadOnlyList<string> partitionKey, CancellationToken cancellationToken)
    {
        var c = GetContainer(database, container);
        using var stream = ToStream(document);
        using var response = await c.CreateItemStreamAsync(stream, ToPartitionKey(partitionKey), cancellationToken: cancellationToken);
        response.EnsureSuccessStatusCode();
        return await ParseStreamAsync(response.Content, cancellationToken) ?? document.DeepClone();
    }

    public async Task<JsonNode?> ReplaceAsync(string database, string container, string id, JsonObject document, IReadOnlyList<string> partitionKey, string? ifMatch, CancellationToken cancellationToken)
    {
        var c = GetContainer(database, container);
        using var stream = ToStream(document);
        var options = ifMatch is null ? null : new ItemRequestOptions { IfMatchEtag = ifMatch };
        using var response = await c.ReplaceItemStreamAsync(stream, id, ToPartitionKey(partitionKey), options, cancellationToken);
        response.EnsureSuccessStatusCode();
        return await ParseStreamAsync(response.Content, cancellationToken) ?? document.DeepClone();
    }

    public async Task<JsonNode?> PatchAsync(string database, string container, string id, IReadOnlyList<string> partitionKey, IReadOnlyList<ResolvedPatchOperation> operations, string? ifMatch, CancellationToken cancellationToken)
    {
        var c = GetContainer(database, container);
        var patchOps = operations.Select(ToCosmosPatch).ToList();
        var options = new PatchItemRequestOptions();
        if (ifMatch is not null)
        {
            options.IfMatchEtag = ifMatch;
        }

        using var response = await c.PatchItemStreamAsync(id, ToPartitionKey(partitionKey), patchOps, options, cancellationToken);
        response.EnsureSuccessStatusCode();
        return await ParseStreamAsync(response.Content, cancellationToken);
    }

    public async Task<JsonNode?> DeleteAsync(string database, string container, string id, IReadOnlyList<string> partitionKey, string? ifMatch, CancellationToken cancellationToken)
    {
        var c = GetContainer(database, container);
        var options = ifMatch is null ? null : new ItemRequestOptions { IfMatchEtag = ifMatch };
        using var response = await c.DeleteItemStreamAsync(id, ToPartitionKey(partitionKey), options, cancellationToken);
        if (response.StatusCode is not System.Net.HttpStatusCode.NoContent and not System.Net.HttpStatusCode.OK)
        {
            response.EnsureSuccessStatusCode();
        }

        return new JsonObject { ["id"] = id, ["deleted"] = true };
    }

    public async Task<JsonArray> TransactionalBatchAsync(string database, string container, IReadOnlyList<string> partitionKey, IReadOnlyList<ResolvedBatchStep> steps, CancellationToken cancellationToken)
    {
        var c = GetContainer(database, container);
        var batch = c.CreateTransactionalBatch(ToPartitionKey(partitionKey));

        foreach (var step in steps)
        {
            switch (step.Type.ToLowerInvariant())
            {
                case "create":
                    if (step.Document is null)
                    {
                        throw new InvalidOperationException($"Batch step '{step.Id}' (create) requires a document.");
                    }

                    batch.CreateItemStream(ToStream(step.Document));
                    break;
                case "replace":
                    if (step.Document is null || step.ItemId is null)
                    {
                        throw new InvalidOperationException($"Batch step '{step.Id}' (replace) requires itemId and document.");
                    }

                    batch.ReplaceItemStream(step.ItemId, ToStream(step.Document));
                    break;
                case "patch":
                    if (step.ItemId is null || step.Operations is null)
                    {
                        throw new InvalidOperationException($"Batch step '{step.Id}' (patch) requires itemId and operations.");
                    }

                    batch.PatchItem(step.ItemId, step.Operations.Select(ToCosmosPatch).ToList());
                    break;
                case "delete":
                    if (step.ItemId is null)
                    {
                        throw new InvalidOperationException($"Batch step '{step.Id}' (delete) requires itemId.");
                    }

                    batch.DeleteItem(step.ItemId);
                    break;
                default:
                    throw new InvalidOperationException($"Unsupported batch step type '{step.Type}'.");
            }
        }

        using var response = await batch.ExecuteAsync(cancellationToken);
        if (!response.IsSuccessStatusCode)
        {
            throw new CosmosBatchException(response.StatusCode, response.ErrorMessage);
        }

        var results = new JsonArray();
        for (var i = 0; i < response.Count; i++)
        {
            var stepResult = response[i];
            results.Add(new JsonObject
            {
                ["stepId"] = steps[i].Id,
                ["statusCode"] = (int)stepResult.StatusCode,
            });
        }

        return results;
    }

    private async Task<float[]> GenerateEmbeddingAsync(string text, CancellationToken cancellationToken)
    {
        var deployment = _configuration["OPENAI_EMBEDDING_DEPLOYMENT"]
            ?? Environment.GetEnvironmentVariable("OPENAI_EMBEDDING_DEPLOYMENT");
        if (string.IsNullOrWhiteSpace(deployment))
        {
            throw new InvalidOperationException("OPENAI_EMBEDDING_DEPLOYMENT is required for vector/hybrid search.");
        }

        var embeddingClient = EmbeddingClientFactory.CreateEmbeddingClient(_configuration, _logger);
        return await embeddingClient.GenerateEmbeddingAsync(text, deployment, cancellationToken);
    }

    private static PatchOperation ToCosmosPatch(ResolvedPatchOperation op)
    {
        var value = op.Value;
        return op.Op.ToLowerInvariant() switch
        {
            "set" => PatchOperation.Set(op.Path, ToPatchValue(value)),
            "replace" => PatchOperation.Replace(op.Path, ToPatchValue(value)),
            "add" => PatchOperation.Add(op.Path, ToPatchValue(value)),
            "remove" => PatchOperation.Remove(op.Path),
            "increment" => PatchOperation.Increment(op.Path, ToDouble(value)),
            _ => throw new InvalidOperationException($"Unsupported patch op '{op.Op}'."),
        };
    }

    private static object? ToPatchValue(JsonNode? node)
        => node is null ? null : JsonSerializer.Deserialize<JsonElement>(node.ToJsonString());

    private static double ToDouble(JsonNode? node)
    {
        if (node is System.Text.Json.Nodes.JsonValue jv)
        {
            if (jv.TryGetValue<double>(out var d))
            {
                return d;
            }

            if (jv.TryGetValue<string>(out var s) && double.TryParse(s, System.Globalization.NumberStyles.Any, System.Globalization.CultureInfo.InvariantCulture, out var parsed))
            {
                return parsed;
            }
        }

        throw new InvalidOperationException("Increment patch value must be numeric.");
    }

    private static object ToParameterValue(JsonNode? node)
    {
        if (node is null)
        {
            return null!;
        }

        return JsonSerializer.Deserialize<JsonElement>(node.ToJsonString());
    }

    private static MemoryStream ToStream(JsonObject document)
    {
        var bytes = Encoding.UTF8.GetBytes(document.ToJsonString(JsonOptions));
        return new MemoryStream(bytes);
    }

    private static async Task<JsonNode?> ParseStreamAsync(Stream stream, CancellationToken cancellationToken)
    {
        if (stream is null || stream.CanSeek && stream.Length == 0)
        {
            return null;
        }

        using var doc = await JsonDocument.ParseAsync(stream, cancellationToken: cancellationToken);
        return JsonNode.Parse(doc.RootElement.GetRawText());
    }

    private static async Task<JsonArray> DrainAsync(FeedIterator iterator, int maxItems, CancellationToken cancellationToken)
    {
        var results = new JsonArray();
        while (iterator.HasMoreResults && results.Count < maxItems)
        {
            using var response = await iterator.ReadNextAsync(cancellationToken);
            using var doc = await JsonDocument.ParseAsync(response.Content, cancellationToken: cancellationToken);
            if (doc.RootElement.TryGetProperty("Documents", out var documents))
            {
                foreach (var item in documents.EnumerateArray())
                {
                    results.Add(JsonNode.Parse(item.GetRawText()));
                    if (results.Count >= maxItems)
                    {
                        break;
                    }
                }
            }
        }

        return results;
    }
}

/// <summary>Raised when a transactional batch fails, carrying the Cosmos status code.</summary>
public sealed class CosmosBatchException : Exception
{
    public CosmosBatchException(System.Net.HttpStatusCode statusCode, string? message)
        : base($"Transactional batch failed with status {(int)statusCode}: {message}")
    {
        StatusCode = statusCode;
    }

    public System.Net.HttpStatusCode StatusCode { get; }
}
