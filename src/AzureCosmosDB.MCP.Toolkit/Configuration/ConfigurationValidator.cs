namespace AzureCosmosDB.MCP.Toolkit.Configuration;

/// <summary>Validation diagnostics.</summary>
public sealed class ConfigurationValidationResult
{
    public List<string> Errors { get; } = new();
    public List<string> Warnings { get; } = new();
}

/// <summary>
/// Startup/schema validator. Fails closed: unknown operation types, missing required fields,
/// and write operations that are not explicitly enabled all produce errors.
/// </summary>
public static class ConfigurationValidator
{
    private static readonly HashSet<string> SupportedVersions = new(StringComparer.Ordinal) { "1.0" };

    private static readonly HashSet<string> ReadOperations = new(StringComparer.OrdinalIgnoreCase)
    {
        "point-read", "query", "text-search", "vector-search", "hybrid-search",
    };

    private static readonly HashSet<string> WriteOperations = new(StringComparer.OrdinalIgnoreCase)
    {
        "create", "replace", "patch", "delete", "transactional-batch", "sequence",
    };

    private static readonly HashSet<string> PatchOps = new(StringComparer.OrdinalIgnoreCase)
    {
        "set", "replace", "add", "remove", "increment",
    };

    public static ConfigurationValidationResult Validate(ToolkitConfiguration config)
    {
        var result = new ConfigurationValidationResult();

        if (string.IsNullOrWhiteSpace(config.Version))
        {
            result.Errors.Add("Top-level 'version' is required.");
        }
        else if (!SupportedVersions.Contains(config.Version))
        {
            result.Errors.Add($"Unsupported configuration version '{config.Version}'. Supported: {string.Join(", ", SupportedVersions)}.");
        }

        if (config.Sources.Count == 0)
        {
            result.Errors.Add("At least one entry under 'sources' is required.");
        }

        foreach (var (name, source) in config.Sources)
        {
            if (!string.Equals(source.Type, "cosmos", StringComparison.OrdinalIgnoreCase))
            {
                result.Errors.Add($"Source '{name}': unsupported type '{source.Type}'. Only 'cosmos' is supported.");
            }

            if (string.IsNullOrWhiteSpace(source.Endpoint) && string.IsNullOrWhiteSpace(source.ConnectionString))
            {
                result.Errors.Add($"Source '{name}': either 'endpoint' or 'connectionString' is required.");
            }

            if (string.IsNullOrWhiteSpace(source.Database))
            {
                result.Warnings.Add($"Source '{name}': no default 'database' set; tools must resolve a database another way.");
            }
        }

        if (config.Tools.Count == 0)
        {
            result.Warnings.Add("No tools are defined; the declarative layer will register nothing.");
        }

        foreach (var (key, tool) in config.Tools)
        {
            ValidateTool(key, tool, config, result);
        }

        return result;
    }

    private static void ValidateTool(string key, ToolConfiguration tool, ToolkitConfiguration config, ConfigurationValidationResult result)
    {
        var name = tool.Name ?? key;

        if (string.IsNullOrWhiteSpace(tool.Description))
        {
            result.Warnings.Add($"Tool '{name}': no description provided.");
        }

        var sourceName = tool.Source ?? config.Defaults?.Source;
        if (string.IsNullOrWhiteSpace(sourceName))
        {
            result.Errors.Add($"Tool '{name}': no 'source' specified and no default source configured.");
        }
        else if (!config.Sources.ContainsKey(sourceName))
        {
            result.Errors.Add($"Tool '{name}': references unknown source '{sourceName}'.");
        }

        if (tool.Operation is null)
        {
            result.Errors.Add($"Tool '{name}': 'operation' is required.");
            return;
        }

        var opType = tool.Operation.Type;
        if (string.IsNullOrWhiteSpace(opType))
        {
            result.Errors.Add($"Tool '{name}': 'operation.type' is required.");
            return;
        }

        var isRead = ReadOperations.Contains(opType);
        var isWrite = WriteOperations.Contains(opType);
        if (!isRead && !isWrite)
        {
            result.Errors.Add($"Tool '{name}': unknown operation type '{opType}'.");
            return;
        }

        // Effective governance: tool over defaults, with readOnly defaulting to true.
        var governance = (tool.Governance ?? new GovernanceConfiguration()).MergedOver(config.Defaults?.Governance);
        var readOnly = governance.ReadOnly ?? true;

        if (isWrite && readOnly)
        {
            result.Errors.Add(
                $"Tool '{name}': operation '{opType}' performs writes but governance.readOnly is not disabled. " +
                "Set governance.readOnly: false to explicitly enable writes (fail-closed default).");
        }

        if (string.Equals(opType, "delete", StringComparison.OrdinalIgnoreCase) && governance.AllowDelete != true)
        {
            result.Errors.Add($"Tool '{name}': delete requires governance.allowDelete: true.");
        }

        ValidateOperationShape(name, tool.Operation, governance, result);
    }

    private static void ValidateOperationShape(string name, OperationConfiguration op, GovernanceConfiguration governance, ConfigurationValidationResult result)
    {
        switch (op.Type.ToLowerInvariant())
        {
            case "point-read":
                Require(op.Container, $"Tool '{name}': point-read requires 'container'.", result);
                Require(op.Id, $"Tool '{name}': point-read requires 'id'.", result);
                RequirePartitionKey(name, op, "point-read", result);
                break;
            case "query":
                Require(op.Container, $"Tool '{name}': query requires 'container'.", result);
                Require(op.Statement, $"Tool '{name}': query requires 'statement'.", result);
                break;
            case "text-search":
                Require(op.Container, $"Tool '{name}': text-search requires 'container'.", result);
                Require(op.Property, $"Tool '{name}': text-search requires 'property'.", result);
                Require(op.SearchText, $"Tool '{name}': text-search requires 'searchText'.", result);
                break;
            case "vector-search":
                Require(op.Container, $"Tool '{name}': vector-search requires 'container'.", result);
                Require(op.VectorPath, $"Tool '{name}': vector-search requires 'vectorPath'.", result);
                Require(op.SearchText, $"Tool '{name}': vector-search requires 'searchText'.", result);
                RequireSelect(name, op, result);
                break;
            case "hybrid-search":
                Require(op.Container, $"Tool '{name}': hybrid-search requires 'container'.", result);
                Require(op.VectorPath, $"Tool '{name}': hybrid-search requires 'vectorPath'.", result);
                Require(op.TextPath, $"Tool '{name}': hybrid-search requires 'textPath'.", result);
                Require(op.SearchText, $"Tool '{name}': hybrid-search requires 'searchText'.", result);
                RequireSelect(name, op, result);
                break;
            case "create":
                Require(op.Container, $"Tool '{name}': create requires 'container'.", result);
                RequirePartitionKey(name, op, "create", result);
                if (op.Document is null || op.Document.Count == 0)
                {
                    result.Errors.Add($"Tool '{name}': create requires a non-empty 'document'.");
                }
                break;
            case "replace":
                Require(op.Container, $"Tool '{name}': replace requires 'container'.", result);
                Require(op.Id, $"Tool '{name}': replace requires 'id'.", result);
                RequirePartitionKey(name, op, "replace", result);
                if (op.Document is null || op.Document.Count == 0)
                {
                    result.Errors.Add($"Tool '{name}': replace requires a non-empty 'document'.");
                }
                break;
            case "patch":
                Require(op.Container, $"Tool '{name}': patch requires 'container'.", result);
                Require(op.Id, $"Tool '{name}': patch requires 'id'.", result);
                RequirePartitionKey(name, op, "patch", result);
                ValidatePatchOperations(name, op.Operations, governance, result);
                break;
            case "delete":
                Require(op.Container, $"Tool '{name}': delete requires 'container'.", result);
                Require(op.Id, $"Tool '{name}': delete requires 'id'.", result);
                RequirePartitionKey(name, op, "delete", result);
                break;
            case "transactional-batch":
                Require(op.Container, $"Tool '{name}': transactional-batch requires 'container'.", result);
                RequirePartitionKey(name, op, "transactional-batch", result);
                if (op.Steps is null || op.Steps.Count == 0)
                {
                    result.Errors.Add($"Tool '{name}': transactional-batch requires at least one step.");
                }
                else
                {
                    foreach (var step in op.Steps)
                    {
                        if (string.Equals(step.EffectiveType, "patch", StringComparison.OrdinalIgnoreCase))
                        {
                            ValidatePatchOperations(name, step.Operations, governance, result);
                        }
                    }
                }
                break;
            case "sequence":
                if (op.Steps is null || op.Steps.Count == 0)
                {
                    result.Errors.Add($"Tool '{name}': sequence requires at least one step.");
                }
                break;
        }
    }

    private static void ValidatePatchOperations(string name, List<PatchOperationConfiguration>? operations, GovernanceConfiguration governance, ConfigurationValidationResult result)
    {
        if (operations is null || operations.Count == 0)
        {
            result.Errors.Add($"Tool '{name}': patch requires at least one operation.");
            return;
        }

        foreach (var patch in operations)
        {
            if (!PatchOps.Contains(patch.Op))
            {
                result.Errors.Add($"Tool '{name}': unsupported patch op '{patch.Op}'. Supported: {string.Join(", ", PatchOps)}.");
            }

            if (string.IsNullOrWhiteSpace(patch.Path) || !patch.Path.StartsWith('/'))
            {
                result.Errors.Add($"Tool '{name}': patch path '{patch.Path}' must be a JSON pointer beginning with '/'.");
            }
            else if (governance.AllowedPatchPaths is { Count: > 0 } allowed &&
                     !allowed.Contains(patch.Path, StringComparer.Ordinal))
            {
                result.Errors.Add($"Tool '{name}': patch path '{patch.Path}' is not in governance.allowedPatchPaths.");
            }
        }
    }

    private static void RequireSelect(string name, OperationConfiguration op, ConfigurationValidationResult result)
    {
        if (op.Select is null || op.Select.Count == 0)
        {
            result.Errors.Add($"Tool '{name}': {op.Type} requires an explicit 'select' list (wildcard projection is not permitted).");
            return;
        }

        if (op.Select.Any(s => s.Contains('*')))
        {
            result.Errors.Add($"Tool '{name}': 'select' may not contain '*' wildcards.");
        }
    }

    private static void Require(string? value, string error, ConfigurationValidationResult result)
    {
        if (string.IsNullOrWhiteSpace(value))
        {
            result.Errors.Add(error);
        }
    }

    private static void RequirePartitionKey(string name, OperationConfiguration op, string opName, ConfigurationValidationResult result)
    {
        var hasSingle = !string.IsNullOrWhiteSpace(op.PartitionKey);
        var hasHierarchical = op.PartitionKeys is { Count: > 0 };
        if (!hasSingle && !hasHierarchical)
        {
            result.Errors.Add($"Tool '{name}': {opName} requires 'partitionKey' or 'partitionKeys'.");
        }
    }
}
