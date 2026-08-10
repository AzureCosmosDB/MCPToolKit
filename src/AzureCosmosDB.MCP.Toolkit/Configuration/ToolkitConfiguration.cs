using System.Text.Json.Serialization;

namespace AzureCosmosDB.MCP.Toolkit.Configuration;

/// <summary>
/// Root of the additive, opt-in declarative configuration model (vNext).
/// Deserialized from YAML or JSON. Existing GA deployments never require this model.
/// </summary>
public sealed class ToolkitConfiguration
{
    /// <summary>Schema version. Currently only "1.0" is supported.</summary>
    [JsonPropertyName("version")]
    public string? Version { get; set; }

    /// <summary>Named Cosmos DB sources referenced by tools.</summary>
    [JsonPropertyName("sources")]
    public Dictionary<string, SourceConfiguration> Sources { get; set; } = new(StringComparer.Ordinal);

    /// <summary>Global defaults applied to every tool unless overridden.</summary>
    [JsonPropertyName("defaults")]
    public DefaultsConfiguration? Defaults { get; set; }

    /// <summary>Business-facing tool definitions keyed by tool name.</summary>
    [JsonPropertyName("tools")]
    public Dictionary<string, ToolConfiguration> Tools { get; set; } = new(StringComparer.Ordinal);
}

/// <summary>A named Cosmos DB data source.</summary>
public sealed class SourceConfiguration
{
    /// <summary>Source type. Only "cosmos" is supported.</summary>
    [JsonPropertyName("type")]
    public string Type { get; set; } = "cosmos";

    /// <summary>Account endpoint. Supports ${ENV} substitution.</summary>
    [JsonPropertyName("endpoint")]
    public string? Endpoint { get; set; }

    /// <summary>Optional connection string (emulator/local). Supports ${ENV} substitution.</summary>
    [JsonPropertyName("connectionString")]
    public string? ConnectionString { get; set; }

    /// <summary>Default database for tools using this source.</summary>
    [JsonPropertyName("database")]
    public string? Database { get; set; }

    /// <summary>Authentication settings for this source.</summary>
    [JsonPropertyName("authentication")]
    public AuthenticationConfiguration? Authentication { get; set; }

    /// <summary>Optional connection mode: "gateway" or "direct".</summary>
    [JsonPropertyName("connectionMode")]
    public string? ConnectionMode { get; set; }
}

/// <summary>Authentication configuration for a source.</summary>
public sealed class AuthenticationConfiguration
{
    /// <summary>Authentication type: "managed-identity" (default), "default-azure-credential", or "connection-string".</summary>
    [JsonPropertyName("type")]
    public string Type { get; set; } = "managed-identity";
}

/// <summary>Global defaults.</summary>
public sealed class DefaultsConfiguration
{
    [JsonPropertyName("governance")]
    public GovernanceConfiguration? Governance { get; set; }

    /// <summary>Default source name applied to tools that do not specify one.</summary>
    [JsonPropertyName("source")]
    public string? Source { get; set; }
}

/// <summary>Per-tool (or default) governance controls. Fail-closed for writes.</summary>
public sealed class GovernanceConfiguration
{
    [JsonPropertyName("timeoutMs")]
    public int? TimeoutMs { get; set; }

    [JsonPropertyName("maxItems")]
    public int? MaxItems { get; set; }

    [JsonPropertyName("maxRequestUnits")]
    public double? MaxRequestUnits { get; set; }

    /// <summary>When true (the default), only read operations are permitted.</summary>
    [JsonPropertyName("readOnly")]
    public bool? ReadOnly { get; set; }

    /// <summary>Explicit opt-in required to permit delete operations.</summary>
    [JsonPropertyName("allowDelete")]
    public bool? AllowDelete { get; set; }

    /// <summary>Explicit opt-in required to permit cross-partition queries.</summary>
    [JsonPropertyName("allowCrossPartition")]
    public bool? AllowCrossPartition { get; set; }

    /// <summary>Upper bound for vector/hybrid topK.</summary>
    [JsonPropertyName("maxTopK")]
    public int? MaxTopK { get; set; }

    /// <summary>Allow-list of JSON patch paths. When set, patch ops must target one of these.</summary>
    [JsonPropertyName("allowedPatchPaths")]
    public List<string>? AllowedPatchPaths { get; set; }

    /// <summary>Merge this instance over a lower-precedence one (this wins where set).</summary>
    public GovernanceConfiguration MergedOver(GovernanceConfiguration? baseline)
    {
        if (baseline is null)
        {
            return this;
        }

        return new GovernanceConfiguration
        {
            TimeoutMs = TimeoutMs ?? baseline.TimeoutMs,
            MaxItems = MaxItems ?? baseline.MaxItems,
            MaxRequestUnits = MaxRequestUnits ?? baseline.MaxRequestUnits,
            ReadOnly = ReadOnly ?? baseline.ReadOnly,
            AllowDelete = AllowDelete ?? baseline.AllowDelete,
            AllowCrossPartition = AllowCrossPartition ?? baseline.AllowCrossPartition,
            MaxTopK = MaxTopK ?? baseline.MaxTopK,
            AllowedPatchPaths = AllowedPatchPaths ?? baseline.AllowedPatchPaths,
        };
    }
}
