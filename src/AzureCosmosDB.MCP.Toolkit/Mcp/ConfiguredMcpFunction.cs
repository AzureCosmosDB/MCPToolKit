using System.Text.Json;
using System.Text.Json.Nodes;
using AzureCosmosDB.MCP.Toolkit.Providers;
using AzureCosmosDB.MCP.Toolkit.Runtime;
using Microsoft.AspNetCore.Http;
using Microsoft.Extensions.AI;

namespace AzureCosmosDB.MCP.Toolkit.Mcp;

/// <summary>
/// Adapts a <see cref="ConfiguredTool"/> to a Microsoft.Extensions.AI <see cref="AIFunction"/> with a
/// fully custom (closed) input schema. Services are resolved per-invocation from
/// <see cref="AIFunctionArguments.Services"/>, so the same tool instance is safe as a singleton.
/// </summary>
public sealed class ConfiguredMcpFunction : AIFunction
{
    private readonly ConfiguredTool _tool;

    public ConfiguredMcpFunction(ConfiguredTool tool) => _tool = tool;

    public override string Name => _tool.Name;

    public override string Description => _tool.Description ?? string.Empty;

    public override JsonElement JsonSchema => _tool.InputSchema;

    protected override async ValueTask<object?> InvokeCoreAsync(AIFunctionArguments arguments, CancellationToken cancellationToken)
    {
        var services = arguments.Services
            ?? throw new InvalidOperationException("Configured tools require a request service provider.");

        var gateway = (ICosmosGateway?)services.GetService(typeof(ICosmosGateway))
            ?? throw new InvalidOperationException("ICosmosGateway is not registered.");
        var loggerFactory = (ILoggerFactory?)services.GetService(typeof(ILoggerFactory));
        var logger = loggerFactory?.CreateLogger<ConfiguredMcpFunction>()
            ?? Microsoft.Extensions.Logging.Abstractions.NullLogger<ConfiguredMcpFunction>.Instance;

        var caller = ResolveCaller(services);
        var input = Normalize(arguments);

        var executor = new ConfiguredToolExecutor(gateway, logger);
        var result = await executor.ExecuteAsync(_tool, input, caller, cancellationToken);
        return result.Json;
    }

    private static CallerContext ResolveCaller(IServiceProvider services)
    {
        var bypass = Environment.GetEnvironmentVariable("DEV_BYPASS_AUTH") == "true";
        var httpContextAccessor = (IHttpContextAccessor?)services.GetService(typeof(IHttpContextAccessor));
        var user = httpContextAccessor?.HttpContext?.User;
        return CallerContext.FromPrincipal(user, bypass);
    }

    private static Dictionary<string, JsonNode?> Normalize(AIFunctionArguments arguments)
    {
        var result = new Dictionary<string, JsonNode?>(StringComparer.Ordinal);
        foreach (var (key, value) in arguments)
        {
            result[key] = value switch
            {
                null => null,
                JsonNode node => node.DeepClone(),
                JsonElement element => JsonSerializer.SerializeToNode(element),
                _ => JsonSerializer.SerializeToNode(value),
            };
        }

        return result;
    }
}
