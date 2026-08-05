using System.Text.Json.Nodes;
using AzureCosmosDB.MCP.Toolkit.Providers;

namespace AzureCosmosDB.MCP.Toolkit.Tests.Configured;

/// <summary>
/// In-memory <see cref="ICosmosGateway"/> used to unit test the configuration runtime without a live account.
/// Records the last call for each operation so tests can assert on bound values (ids, partition keys,
/// query parameters) and injection resistance.
/// </summary>
public sealed class FakeCosmosGateway : ICosmosGateway
{
    public JsonNode? PointReadResult { get; set; }
    public JsonArray QueryResult { get; set; } = new();
    public JsonArray SearchResult { get; set; } = new();
    public JsonNode? CreateResult { get; set; }
    public JsonNode? PatchResult { get; set; }

    public string? LastId { get; private set; }
    public string? LastPartitionKey { get; private set; }
    public string? LastContainer { get; private set; }
    public QueryRequest? LastQuery { get; private set; }
    public SearchRequest? LastSearch { get; private set; }
    public JsonObject? LastDocument { get; private set; }
    public IReadOnlyList<ResolvedPatchOperation>? LastPatch { get; private set; }
    public string? LastIfMatch { get; private set; }
    public IReadOnlyList<ResolvedBatchStep>? LastBatch { get; private set; }

    public Func<string, JsonNode?>? PointReadHandler { get; set; }

    public Task<JsonNode?> PointReadAsync(string database, string container, string id, string partitionKey, CancellationToken cancellationToken)
    {
        LastContainer = container;
        LastId = id;
        LastPartitionKey = partitionKey;
        return Task.FromResult(PointReadHandler is not null ? PointReadHandler(id) : PointReadResult);
    }

    public Task<JsonArray> QueryAsync(QueryRequest request, CancellationToken cancellationToken)
    {
        LastQuery = request;
        LastContainer = request.Container;
        return Task.FromResult(QueryResult);
    }

    public Task<JsonArray> TextSearchAsync(string database, string container, string property, string searchText, int maxItems, CancellationToken cancellationToken)
    {
        LastContainer = container;
        return Task.FromResult(SearchResult);
    }

    public Task<JsonArray> VectorSearchAsync(SearchRequest request, CancellationToken cancellationToken)
    {
        LastSearch = request;
        return Task.FromResult(SearchResult);
    }

    public Task<JsonArray> HybridSearchAsync(SearchRequest request, CancellationToken cancellationToken)
    {
        LastSearch = request;
        return Task.FromResult(SearchResult);
    }

    public Task<JsonNode?> CreateAsync(string database, string container, JsonObject document, string partitionKey, CancellationToken cancellationToken)
    {
        LastContainer = container;
        LastDocument = document;
        LastPartitionKey = partitionKey;
        return Task.FromResult(CreateResult ?? (JsonNode?)document.DeepClone());
    }

    public Task<JsonNode?> ReplaceAsync(string database, string container, string id, JsonObject document, string partitionKey, string? ifMatch, CancellationToken cancellationToken)
    {
        LastContainer = container;
        LastId = id;
        LastDocument = document;
        LastPartitionKey = partitionKey;
        LastIfMatch = ifMatch;
        return Task.FromResult((JsonNode?)document.DeepClone());
    }

    public Task<JsonNode?> PatchAsync(string database, string container, string id, string partitionKey, IReadOnlyList<ResolvedPatchOperation> operations, string? ifMatch, CancellationToken cancellationToken)
    {
        LastContainer = container;
        LastId = id;
        LastPartitionKey = partitionKey;
        LastPatch = operations;
        LastIfMatch = ifMatch;
        return Task.FromResult<JsonNode?>(PatchResult ?? new JsonObject { ["id"] = id, ["patched"] = true });
    }

    public Task<JsonNode?> DeleteAsync(string database, string container, string id, string partitionKey, string? ifMatch, CancellationToken cancellationToken)
    {
        LastContainer = container;
        LastId = id;
        LastPartitionKey = partitionKey;
        LastIfMatch = ifMatch;
        return Task.FromResult<JsonNode?>(new JsonObject { ["id"] = id, ["deleted"] = true });
    }

    public Task<JsonArray> TransactionalBatchAsync(string database, string container, string partitionKey, IReadOnlyList<ResolvedBatchStep> steps, CancellationToken cancellationToken)
    {
        LastContainer = container;
        LastPartitionKey = partitionKey;
        LastBatch = steps;
        var results = new JsonArray();
        foreach (var step in steps)
        {
            results.Add(new JsonObject { ["stepId"] = step.Id, ["statusCode"] = 200 });
        }

        return Task.FromResult(results);
    }
}
