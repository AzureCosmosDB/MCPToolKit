using AzureCosmosDB.MCP.Toolkit.Configuration;
using AzureCosmosDB.MCP.Toolkit.Providers;
using AzureCosmosDB.MCP.Toolkit.Runtime;
using Microsoft.Extensions.DependencyInjection;
using ModelContextProtocol.Server;

namespace AzureCosmosDB.MCP.Toolkit.Mcp;

/// <summary>
/// Opt-in registration for the declarative, business-facing tool layer (vNext).
/// If no configuration file is present the toolkit behaves exactly as before, so this method is a no-op.
/// </summary>
/// <remarks>
/// EXPERIMENTAL: this declarative layer is experimental and may change in a future release. It is
/// additive and opt-in (dormant unless a configuration file is supplied). Review the security,
/// authorization, tenant-isolation, and governance settings before using it in production.
/// </remarks>
public static class ConfiguredToolsRegistration
{
    /// <summary>Environment variable / configuration key that points at the declarative config file.</summary>
    public const string ConfigPathEnvironmentVariable = "COSMOS_TOOLS_CONFIG";

    public static IMcpServerBuilder AddConfiguredCosmosTools(
        this IMcpServerBuilder builder,
        IConfiguration configuration,
        ILogger? logger = null)
    {
        var path = ResolveConfigPath(configuration);
        if (string.IsNullOrWhiteSpace(path))
        {
            logger?.LogInformation("No declarative tool configuration provided; only built-in GA tools are active.");
            return builder;
        }

        if (!File.Exists(path))
        {
            // A path was explicitly requested but is missing: fail closed rather than silently ignore.
            throw new InvalidOperationException($"Declarative tool configuration '{path}' was specified but not found.");
        }

        var loader = new ConfigurationLoader();
        var result = loader.LoadFromFile(path);

        foreach (var warning in result.Warnings)
        {
            logger?.LogWarning("Tool configuration warning: {Warning}", warning);
        }

        if (!result.IsValid)
        {
            // Fail closed: do not start with an invalid declarative configuration.
            throw new InvalidOperationException(
                $"Declarative tool configuration '{path}' is invalid:{Environment.NewLine}" +
                string.Join(Environment.NewLine, result.Errors));
        }

        var tools = ConfiguredToolSet.Build(result.Configuration!);
        logger?.LogInformation("Loaded {Count} configured business tool(s) from '{Path}'.", tools.Count, path);
        logger?.LogWarning(
            "[EXPERIMENTAL] The declarative business-tools layer is experimental and may change in a future " +
            "release. Review its security, authorization, tenant-isolation, and governance settings before production use.");

        // Shared provider surface used by the configured tools.
        builder.Services.AddSingleton<ICosmosGateway, CosmosGateway>();

        var serverTools = tools.Select(CreateServerTool).ToList();
        if (serverTools.Count > 0)
        {
            builder.WithTools(serverTools);
        }

        return builder;
    }

    private static McpServerTool CreateServerTool(ConfiguredTool tool)
    {
        var function = new ConfiguredMcpFunction(tool);
        var options = new McpServerToolCreateOptions
        {
            Name = tool.Name,
            Description = tool.Description,
            ReadOnly = !tool.IsWrite,
            Destructive = tool.IsDestructive,
            Idempotent = !tool.IsWrite,
        };

        return McpServerTool.Create(function, options);
    }

    private static string? ResolveConfigPath(IConfiguration configuration)
    {
        var fromEnv = Environment.GetEnvironmentVariable(ConfigPathEnvironmentVariable);
        if (!string.IsNullOrWhiteSpace(fromEnv))
        {
            return fromEnv;
        }

        var fromConfig = configuration["CosmosMcp:ToolsConfigPath"];
        return string.IsNullOrWhiteSpace(fromConfig) ? null : fromConfig;
    }
}
