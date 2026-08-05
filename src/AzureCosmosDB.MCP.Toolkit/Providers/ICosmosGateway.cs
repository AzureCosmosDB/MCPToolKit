using System.Text.Json.Nodes;

namespace AzureCosmosDB.MCP.Toolkit.Providers;

/// <summary>A patch operation with its value already resolved to a concrete node.</summary>
public sealed record ResolvedPatchOperation(string Op, string Path, JsonNode? Value);

/// <summary>A single resolved step within a transactional batch.</summary>
public sealed record ResolvedBatchStep(
    string Id,
    string Type,
    string? ItemId,
    JsonObject? Document,
    IReadOnlyList<ResolvedPatchOperation>? Operations);

/// <summary>Parameters for a query execution.</summary>
public sealed record QueryRequest(
    string Database,
    string Container,
    string Statement,
    IReadOnlyDictionary<string, JsonNode?> Parameters,
    string? PartitionKey,
    int MaxItems,
    bool AllowCrossPartition);

/// <summary>Parameters for a vector or hybrid search execution.</summary>
public sealed record SearchRequest(
    string Database,
    string Container,
    string SearchText,
    string VectorPath,
    string? TextPath,
    IReadOnlyList<string> Select,
    int TopK,
    string? PartitionKey);

/// <summary>
/// Shared abstraction over Cosmos DB data operations. Both the (existing) built-in tools' logic
/// and the (new) configured tools execute through the same provider surface.
/// The interface is fully mockable so the configuration runtime can be unit tested without a live account.
/// </summary>
public interface ICosmosGateway
{
    Task<JsonNode?> PointReadAsync(string database, string container, string id, string partitionKey, CancellationToken cancellationToken);

    Task<JsonArray> QueryAsync(QueryRequest request, CancellationToken cancellationToken);

    Task<JsonArray> TextSearchAsync(string database, string container, string property, string searchText, int maxItems, CancellationToken cancellationToken);

    Task<JsonArray> VectorSearchAsync(SearchRequest request, CancellationToken cancellationToken);

    Task<JsonArray> HybridSearchAsync(SearchRequest request, CancellationToken cancellationToken);

    Task<JsonNode?> CreateAsync(string database, string container, JsonObject document, string partitionKey, CancellationToken cancellationToken);

    Task<JsonNode?> ReplaceAsync(string database, string container, string id, JsonObject document, string partitionKey, string? ifMatch, CancellationToken cancellationToken);

    Task<JsonNode?> PatchAsync(string database, string container, string id, string partitionKey, IReadOnlyList<ResolvedPatchOperation> operations, string? ifMatch, CancellationToken cancellationToken);

    Task<JsonNode?> DeleteAsync(string database, string container, string id, string partitionKey, string? ifMatch, CancellationToken cancellationToken);

    Task<JsonArray> TransactionalBatchAsync(string database, string container, string partitionKey, IReadOnlyList<ResolvedBatchStep> steps, CancellationToken cancellationToken);
}
