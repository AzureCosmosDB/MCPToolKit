using System.Text.Json.Serialization;

namespace AzureCosmosDB.MCP.Toolkit.Configuration;

/// <summary>A single business-facing tool definition.</summary>
public sealed class ToolConfiguration
{
    /// <summary>Optional explicit name. Defaults to the dictionary key.</summary>
    [JsonPropertyName("name")]
    public string? Name { get; set; }

    [JsonPropertyName("description")]
    public string? Description { get; set; }

    [JsonPropertyName("version")]
    public string? Version { get; set; }

    /// <summary>When false, the tool is not registered. Defaults to true.</summary>
    [JsonPropertyName("enabled")]
    public bool? Enabled { get; set; }

    [JsonPropertyName("tags")]
    public List<string>? Tags { get; set; }

    [JsonPropertyName("examples")]
    public List<string>? Examples { get; set; }

    /// <summary>Name of the source this tool binds to.</summary>
    [JsonPropertyName("source")]
    public string? Source { get; set; }

    [JsonPropertyName("operation")]
    public OperationConfiguration? Operation { get; set; }

    [JsonPropertyName("input")]
    public InputSchemaConfiguration? Input { get; set; }

    [JsonPropertyName("output")]
    public OutputConfiguration? Output { get; set; }

    [JsonPropertyName("authorization")]
    public AuthorizationConfiguration? Authorization { get; set; }

    [JsonPropertyName("governance")]
    public GovernanceConfiguration? Governance { get; set; }
}

/// <summary>Declarative operation definition. The <see cref="Type"/> selects the provider.</summary>
public sealed class OperationConfiguration
{
    /// <summary>
    /// One of: point-read, query, text-search, vector-search, hybrid-search,
    /// create, replace, patch, delete, transactional-batch, sequence.
    /// </summary>
    [JsonPropertyName("type")]
    public string Type { get; set; } = string.Empty;

    [JsonPropertyName("container")]
    public string? Container { get; set; }

    // point-read / patch / replace / delete
    [JsonPropertyName("id")]
    public string? Id { get; set; }

    [JsonPropertyName("partitionKey")]
    public string? PartitionKey { get; set; }

    /// <summary>Hierarchical (subpartitioned) partition key components. Takes precedence over <see cref="PartitionKey"/>.</summary>
    [JsonPropertyName("partitionKeys")]
    public List<string>? PartitionKeys { get; set; }

    // query
    [JsonPropertyName("statement")]
    public string? Statement { get; set; }

    [JsonPropertyName("parameters")]
    public Dictionary<string, string>? Parameters { get; set; }

    // text-search
    [JsonPropertyName("property")]
    public string? Property { get; set; }

    [JsonPropertyName("searchText")]
    public string? SearchText { get; set; }

    [JsonPropertyName("limit")]
    public string? Limit { get; set; }

    // vector-search / hybrid-search
    [JsonPropertyName("vectorPath")]
    public string? VectorPath { get; set; }

    [JsonPropertyName("textPath")]
    public string? TextPath { get; set; }

    [JsonPropertyName("select")]
    public List<string>? Select { get; set; }

    [JsonPropertyName("topK")]
    public string? TopK { get; set; }

    // create / replace
    [JsonPropertyName("document")]
    public Dictionary<string, object?>? Document { get; set; }

    // patch
    [JsonPropertyName("operations")]
    public List<PatchOperationConfiguration>? Operations { get; set; }

    [JsonPropertyName("concurrency")]
    public ConcurrencyConfiguration? Concurrency { get; set; }

    // transactional-batch / sequence
    [JsonPropertyName("steps")]
    public List<StepConfiguration>? Steps { get; set; }
}

/// <summary>A JSON Patch style operation.</summary>
public sealed class PatchOperationConfiguration
{
    /// <summary>One of: set, replace, add, remove, increment.</summary>
    [JsonPropertyName("op")]
    public string Op { get; set; } = string.Empty;

    [JsonPropertyName("path")]
    public string Path { get; set; } = string.Empty;

    [JsonPropertyName("value")]
    public object? Value { get; set; }
}

/// <summary>Optimistic concurrency control.</summary>
public sealed class ConcurrencyConfiguration
{
    /// <summary>ETag value or binding expression for If-Match.</summary>
    [JsonPropertyName("ifMatch")]
    public string? IfMatch { get; set; }
}

/// <summary>A step within a transactional-batch or bounded sequence.</summary>
public sealed class StepConfiguration
{
    [JsonPropertyName("id")]
    public string Id { get; set; } = string.Empty;

    /// <summary>Operation kind for the step (patch, create, replace, delete, point-read, assert).</summary>
    [JsonPropertyName("type")]
    public string Type { get; set; } = string.Empty;

    /// <summary>Alias used by some examples ("use") — treated as a synonym for type.</summary>
    [JsonPropertyName("use")]
    public string? Use { get; set; }

    [JsonPropertyName("itemId")]
    public string? ItemId { get; set; }

    [JsonPropertyName("partitionKey")]
    public string? PartitionKey { get; set; }

    [JsonPropertyName("partitionKeys")]
    public List<string>? PartitionKeys { get; set; }

    [JsonPropertyName("operations")]
    public List<PatchOperationConfiguration>? Operations { get; set; }

    [JsonPropertyName("document")]
    public Dictionary<string, object?>? Document { get; set; }

    /// <summary>Boolean expression for assert steps. Fails fast when false.</summary>
    [JsonPropertyName("expression")]
    public string? Expression { get; set; }

    /// <summary>Error message surfaced when an assert step fails.</summary>
    [JsonPropertyName("message")]
    public string? Message { get; set; }

    [JsonPropertyName("concurrency")]
    public ConcurrencyConfiguration? Concurrency { get; set; }

    public string EffectiveType => string.IsNullOrWhiteSpace(Use) ? Type : Use!;
}
