using System.Diagnostics;
using System.Text.Json;
using System.Text.Json.Nodes;
using AzureCosmosDB.MCP.Toolkit.Providers;
using Microsoft.Azure.Cosmos;

namespace AzureCosmosDB.MCP.Toolkit.Runtime;

/// <summary>Structured outcome of executing a configured tool.</summary>
public sealed record ConfiguredToolExecutionResult(string Json, bool IsError, string? Category);

/// <summary>
/// The end-to-end execution pipeline for a configured tool:
/// input validation → authorization → identity overlay → binding → governed execution →
/// output shaping → telemetry. Never throws to the caller; all failures are returned as
/// structured, client-safe JSON.
/// </summary>
public sealed class ConfiguredToolExecutor
{
    private static readonly JsonSerializerOptions JsonOptions = new() { WriteIndented = false };

    private readonly ICosmosGateway _gateway;
    private readonly ILogger _logger;

    public ConfiguredToolExecutor(ICosmosGateway gateway, ILogger logger)
    {
        _gateway = gateway;
        _logger = logger;
    }

    public async Task<ConfiguredToolExecutionResult> ExecuteAsync(
        ConfiguredTool tool,
        IReadOnlyDictionary<string, JsonNode?> rawInput,
        CallerContext caller,
        CancellationToken cancellationToken)
    {
        var stopwatch = Stopwatch.StartNew();
        var category = "ok";
        try
        {
            var validation = InputValidator.Validate(tool.Config.Input, rawInput);
            if (!validation.IsValid)
            {
                category = "validation";
                return Error(category, "Input validation failed.", validation.Errors);
            }

            var auth = AuthorizationEvaluator.Authorize(tool.Config.Authorization, caller, validation.Values);
            if (!auth.Allowed)
            {
                category = "authorization";
                return Error(category, auth.Error ?? "Not authorized.");
            }

            var effectiveInput = AuthorizationEvaluator.ApplyIdentityDerivedInputs(tool.Config.Authorization, caller, validation.Values);
            var context = new BindingContext(effectiveInput);
            var executor = new OperationExecutor(_gateway);

            using var timeoutCts = CreateTimeoutScope(tool, cancellationToken, out var linkedToken);

            JsonNode? result;
            try
            {
                result = await executor.ExecuteAsync(tool.Config.Operation!, tool.Database, tool.Governance, context, linkedToken);
            }
            catch (OperationCanceledException) when (timeoutCts is not null && timeoutCts.IsCancellationRequested && !cancellationToken.IsCancellationRequested)
            {
                category = "timeout";
                return Error(category, $"Operation timed out after {tool.Governance.TimeoutMs}ms.");
            }

            var shaped = OutputProjector.Apply(result, tool.Config.Output);
            var json = shaped?.ToJsonString(JsonOptions) ?? "null";

            _logger.LogInformation(
                "Configured tool executed. Tool: {Tool} | Version: {Version} | Operation: {Operation} | Database: {Database} | Container: {Container} | LatencyMs: {Latency} | ResultCategory: {Category}",
                tool.Name, tool.Config.Version ?? "n/a", tool.Config.Operation!.Type, tool.Database, tool.Config.Operation.Container ?? "n/a", stopwatch.ElapsedMilliseconds, category);

            return new ConfiguredToolExecutionResult(json, false, category);
        }
        catch (AssertionFailedException ex)
        {
            category = "assertion";
            return Error(category, ex.Message);
        }
        catch (BindingFailedException ex)
        {
            category = "binding";
            return Error(category, ex.Message);
        }
        catch (CosmosBatchException ex)
        {
            category = ex.StatusCode == System.Net.HttpStatusCode.PreconditionFailed ? "conflict" : "cosmos";
            return Error(category, ex.Message);
        }
        catch (CosmosException ex)
        {
            category = ex.StatusCode switch
            {
                System.Net.HttpStatusCode.NotFound => "not_found",
                System.Net.HttpStatusCode.PreconditionFailed => "conflict",
                System.Net.HttpStatusCode.Conflict => "conflict",
                _ => "cosmos",
            };
            _logger.LogWarning(ex, "Configured tool '{Tool}' Cosmos error {StatusCode}.", tool.Name, ex.StatusCode);
            return Error(category, ex.Message, statusCode: (int)ex.StatusCode);
        }
        catch (Exception ex)
        {
            category = "internal";
            _logger.LogError(ex, "Configured tool '{Tool}' failed unexpectedly.", tool.Name);
            return Error(category, "An internal error occurred while executing the tool.");
        }
        finally
        {
            stopwatch.Stop();
        }
    }

    private static CancellationTokenSource? CreateTimeoutScope(ConfiguredTool tool, CancellationToken outer, out CancellationToken linked)
    {
        if (tool.Governance.TimeoutMs is int ms && ms > 0)
        {
            var cts = CancellationTokenSource.CreateLinkedTokenSource(outer);
            cts.CancelAfter(ms);
            linked = cts.Token;
            return cts;
        }

        linked = outer;
        return null;
    }

    private static ConfiguredToolExecutionResult Error(string category, string message, IEnumerable<string>? details = null, int? statusCode = null)
    {
        var payload = new JsonObject
        {
            ["error"] = message,
            ["category"] = category,
        };

        if (statusCode is int code)
        {
            payload["statusCode"] = code;
        }

        if (details is not null)
        {
            var arr = new JsonArray();
            foreach (var d in details)
            {
                arr.Add(d);
            }

            payload["details"] = arr;
        }

        return new ConfiguredToolExecutionResult(payload.ToJsonString(JsonOptions), true, category);
    }
}
