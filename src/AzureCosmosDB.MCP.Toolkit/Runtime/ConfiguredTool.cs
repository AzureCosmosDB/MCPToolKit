using System.Text.Json;
using AzureCosmosDB.MCP.Toolkit.Configuration;

namespace AzureCosmosDB.MCP.Toolkit.Runtime;

/// <summary>A validated, fully-resolved tool ready to be registered and executed.</summary>
public sealed class ConfiguredTool
{
    public required string Name { get; init; }
    public string? Description { get; init; }
    public required ToolConfiguration Config { get; init; }
    public required string Database { get; init; }
    public required GovernanceConfiguration Governance { get; init; }
    public required JsonElement InputSchema { get; init; }

    private static readonly HashSet<string> WriteTypes = new(StringComparer.OrdinalIgnoreCase)
    {
        "create", "replace", "patch", "delete", "transactional-batch", "sequence",
    };

    public bool IsWrite => Config.Operation is not null && WriteTypes.Contains(Config.Operation.Type);

    public bool IsDestructive => string.Equals(Config.Operation?.Type, "delete", StringComparison.OrdinalIgnoreCase);
}

/// <summary>Builds the set of <see cref="ConfiguredTool"/> instances from a validated configuration.</summary>
public static class ConfiguredToolSet
{
    public static IReadOnlyList<ConfiguredTool> Build(ToolkitConfiguration config)
    {
        var tools = new List<ConfiguredTool>();

        foreach (var (key, toolConfig) in config.Tools)
        {
            if (toolConfig.Enabled == false)
            {
                continue;
            }

            var sourceName = toolConfig.Source ?? config.Defaults?.Source;
            if (sourceName is null || !config.Sources.TryGetValue(sourceName, out var source))
            {
                continue;
            }

            var database = source.Database
                ?? throw new InvalidOperationException($"Source '{sourceName}' used by tool '{key}' has no database configured.");

            var governance = (toolConfig.Governance ?? new GovernanceConfiguration())
                .MergedOver(config.Defaults?.Governance);
            governance.ReadOnly ??= true;

            tools.Add(new ConfiguredTool
            {
                Name = toolConfig.Name ?? key,
                Description = toolConfig.Description,
                Config = toolConfig,
                Database = database,
                Governance = governance,
                InputSchema = JsonSchemaGenerator.Generate(toolConfig.Input),
            });
        }

        return tools;
    }
}
