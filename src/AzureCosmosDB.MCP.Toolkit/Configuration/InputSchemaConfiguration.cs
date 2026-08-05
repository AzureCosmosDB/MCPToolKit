using System.Text.Json.Serialization;

namespace AzureCosmosDB.MCP.Toolkit.Configuration;

/// <summary>Declarative input schema (a constrained subset of JSON Schema).</summary>
public sealed class InputSchemaConfiguration
{
    [JsonPropertyName("type")]
    public string Type { get; set; } = "object";

    [JsonPropertyName("required")]
    public List<string>? Required { get; set; }

    [JsonPropertyName("properties")]
    public Dictionary<string, PropertySchema>? Properties { get; set; }
}

/// <summary>A single input property definition with validation constraints.</summary>
public sealed class PropertySchema
{
    /// <summary>string, integer, number, boolean, object, array.</summary>
    [JsonPropertyName("type")]
    public string Type { get; set; } = "string";

    [JsonPropertyName("description")]
    public string? Description { get; set; }

    [JsonPropertyName("default")]
    public object? Default { get; set; }

    [JsonPropertyName("enum")]
    public List<object>? Enum { get; set; }

    [JsonPropertyName("minimum")]
    public double? Minimum { get; set; }

    [JsonPropertyName("maximum")]
    public double? Maximum { get; set; }

    [JsonPropertyName("minLength")]
    public int? MinLength { get; set; }

    [JsonPropertyName("maxLength")]
    public int? MaxLength { get; set; }

    [JsonPropertyName("pattern")]
    public string? Pattern { get; set; }

    [JsonPropertyName("minItems")]
    public int? MinItems { get; set; }

    [JsonPropertyName("maxItems")]
    public int? MaxItems { get; set; }

    /// <summary>Item schema for array types.</summary>
    [JsonPropertyName("items")]
    public PropertySchema? Items { get; set; }

    /// <summary>Nested properties for object types.</summary>
    [JsonPropertyName("properties")]
    public Dictionary<string, PropertySchema>? Properties { get; set; }

    [JsonPropertyName("required")]
    public List<string>? Required { get; set; }
}

/// <summary>Output shaping definition (projection, renaming, redaction, limits).</summary>
public sealed class OutputConfiguration
{
    /// <summary>Map of output field name to source field path (projection + rename).</summary>
    [JsonPropertyName("select")]
    public Dictionary<string, string>? Select { get; set; }

    /// <summary>Fields to remove from output entirely (redaction).</summary>
    [JsonPropertyName("redact")]
    public List<string>? Redact { get; set; }

    /// <summary>Optional hard cap on the number of returned items.</summary>
    [JsonPropertyName("maxItems")]
    public int? MaxItems { get; set; }
}

/// <summary>Per-tool authorization policy.</summary>
public sealed class AuthorizationConfiguration
{
    [JsonPropertyName("requiredScopes")]
    public List<string>? RequiredScopes { get; set; }

    [JsonPropertyName("requiredRoles")]
    public List<string>? RequiredRoles { get; set; }

    /// <summary>Claim type that carries the tenant identifier.</summary>
    [JsonPropertyName("tenantClaim")]
    public string? TenantClaim { get; set; }

    /// <summary>Document/partition field that must equal the caller tenant claim.</summary>
    [JsonPropertyName("tenantField")]
    public string? TenantField { get; set; }

    /// <summary>Additional claim equality rules (claim type =&gt; required value).</summary>
    [JsonPropertyName("claims")]
    public Dictionary<string, string>? Claims { get; set; }

    /// <summary>
    /// Input parameter whose value must be derived from identity (never trusted from the model)
    /// mapped to the claim it must equal. Used for partition-key restriction.
    /// </summary>
    [JsonPropertyName("partitionKeyFromClaim")]
    public Dictionary<string, string>? PartitionKeyFromClaim { get; set; }
}
