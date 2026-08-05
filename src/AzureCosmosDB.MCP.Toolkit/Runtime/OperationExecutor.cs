using System.Globalization;
using System.Text.Json.Nodes;
using AzureCosmosDB.MCP.Toolkit.Configuration;
using AzureCosmosDB.MCP.Toolkit.Providers;

namespace AzureCosmosDB.MCP.Toolkit.Runtime;

/// <summary>
/// Binds a declarative operation against the current invocation context and executes it through the
/// shared <see cref="ICosmosGateway"/>. Governance limits (max items, topK, cross-partition) are
/// enforced here; timeouts are enforced by the caller via a linked cancellation token.
/// </summary>
public sealed class OperationExecutor
{
    private readonly ICosmosGateway _gateway;

    public OperationExecutor(ICosmosGateway gateway) => _gateway = gateway;

    public async Task<JsonNode?> ExecuteAsync(
        OperationConfiguration op,
        string database,
        GovernanceConfiguration governance,
        BindingContext context,
        CancellationToken cancellationToken)
    {
        switch (op.Type.ToLowerInvariant())
        {
            case "point-read":
                return await _gateway.PointReadAsync(
                    database, op.Container!, RequireString(context, op.Id, "id"), RequireString(context, op.PartitionKey, "partitionKey"), cancellationToken);

            case "query":
                return await ExecuteQueryAsync(op, database, governance, context, cancellationToken);

            case "text-search":
                return await _gateway.TextSearchAsync(
                    database, op.Container!, op.Property!, RequireString(context, op.SearchText, "searchText"),
                    ResolveLimit(context, op.Limit, governance.MaxItems ?? 20, 20), cancellationToken);

            case "vector-search":
                return await _gateway.VectorSearchAsync(BuildSearch(op, database, governance, context), cancellationToken);

            case "hybrid-search":
                return await _gateway.HybridSearchAsync(BuildSearch(op, database, governance, context), cancellationToken);

            case "create":
                return await _gateway.CreateAsync(
                    database, op.Container!, BuildDocument(context, op.Document),
                    RequireString(context, op.PartitionKey, "partitionKey"), cancellationToken);

            case "replace":
                return await _gateway.ReplaceAsync(
                    database, op.Container!, RequireString(context, op.Id, "id"), BuildDocument(context, op.Document),
                    RequireString(context, op.PartitionKey, "partitionKey"), context.BindToString(op.Concurrency?.IfMatch), cancellationToken);

            case "patch":
                return await _gateway.PatchAsync(
                    database, op.Container!, RequireString(context, op.Id, "id"), RequireString(context, op.PartitionKey, "partitionKey"),
                    ResolvePatchOperations(context, op.Operations!), context.BindToString(op.Concurrency?.IfMatch), cancellationToken);

            case "delete":
                return await _gateway.DeleteAsync(
                    database, op.Container!, RequireString(context, op.Id, "id"), RequireString(context, op.PartitionKey, "partitionKey"),
                    context.BindToString(op.Concurrency?.IfMatch), cancellationToken);

            case "transactional-batch":
                return await _gateway.TransactionalBatchAsync(
                    database, op.Container!, RequireString(context, op.PartitionKey, "partitionKey"),
                    ResolveBatchSteps(context, op.Steps!), cancellationToken);

            case "sequence":
                return await ExecuteSequenceAsync(op, database, governance, context, cancellationToken);

            default:
                throw new InvalidOperationException($"Unsupported operation type '{op.Type}'.");
        }
    }

    private async Task<JsonNode?> ExecuteQueryAsync(OperationConfiguration op, string database, GovernanceConfiguration governance, BindingContext context, CancellationToken cancellationToken)
    {
        var parameters = new Dictionary<string, JsonNode?>(StringComparer.Ordinal);
        if (op.Parameters is not null)
        {
            foreach (var (name, template) in op.Parameters)
            {
                parameters[name] = context.BindTemplate(template);
            }
        }

        var request = new QueryRequest(
            database,
            op.Container!,
            op.Statement!,
            parameters,
            context.BindToString(op.PartitionKey),
            governance.MaxItems ?? 100,
            governance.AllowCrossPartition ?? false);

        return await _gateway.QueryAsync(request, cancellationToken);
    }

    private async Task<JsonNode?> ExecuteSequenceAsync(OperationConfiguration op, string database, GovernanceConfiguration governance, BindingContext context, CancellationToken cancellationToken)
    {
        JsonNode? last = null;
        foreach (var step in op.Steps!)
        {
            var stepType = step.EffectiveType.ToLowerInvariant();
            if (stepType == "assert")
            {
                if (!SafeExpressionEvaluator.Evaluate(step.Expression ?? "false", context, out var exprError))
                {
                    throw new AssertionFailedException(step.Message ?? exprError ?? $"Assertion '{step.Id}' failed.");
                }

                continue;
            }

            var stepOp = new OperationConfiguration
            {
                Type = stepType,
                Container = op.Container,
                Id = step.ItemId,
                PartitionKey = step.PartitionKey ?? op.PartitionKey,
                Document = step.Document,
                Operations = step.Operations,
                Concurrency = step.Concurrency,
            };

            var result = await ExecuteAsync(stepOp, database, governance, context, cancellationToken);
            context.SetStepOutput(step.Id, result);
            last = result;
        }

        return last;
    }

    private static SearchRequest BuildSearch(OperationConfiguration op, string database, GovernanceConfiguration governance, BindingContext context)
        => new(
            database,
            op.Container!,
            RequireString(context, op.SearchText, "searchText"),
            op.VectorPath!,
            op.TextPath,
            op.Select ?? new List<string>(),
            ResolveLimit(context, op.TopK, governance.MaxTopK ?? 50, governance.MaxTopK ?? 50),
            context.BindToString(op.PartitionKey));

    private static JsonObject BuildDocument(BindingContext context, Dictionary<string, object?>? document)
    {
        var result = new JsonObject();
        if (document is null)
        {
            return result;
        }

        foreach (var (key, value) in document)
        {
            result[key] = context.Bind(value);
        }

        return result;
    }

    private static List<ResolvedPatchOperation> ResolvePatchOperations(BindingContext context, List<PatchOperationConfiguration> operations)
        => operations
            .Select(o => new ResolvedPatchOperation(o.Op, o.Path, o.Op.Equals("remove", StringComparison.OrdinalIgnoreCase) ? null : context.Bind(o.Value)))
            .ToList();

    private static List<ResolvedBatchStep> ResolveBatchSteps(BindingContext context, List<StepConfiguration> steps)
        => steps.Select(s => new ResolvedBatchStep(
            s.Id,
            s.EffectiveType,
            context.BindToString(s.ItemId),
            s.Document is null ? null : BuildDocument(context, s.Document),
            s.Operations is null ? null : ResolvePatchOperations(context, s.Operations))).ToList();

    private static string RequireString(BindingContext context, string? template, string field)
    {
        var value = context.BindToString(template);
        if (string.IsNullOrEmpty(value))
        {
            throw new BindingFailedException($"Could not resolve a value for '{field}'.");
        }

        return value;
    }

    private static int ResolveLimit(BindingContext context, string? template, int fallback, int max)
    {
        var resolved = fallback;
        if (!string.IsNullOrWhiteSpace(template))
        {
            var node = context.BindTemplate(template);
            if (node is JsonValue jv)
            {
                if (jv.TryGetValue<int>(out var i))
                {
                    resolved = i;
                }
                else if (jv.TryGetValue<string>(out var s) && int.TryParse(s, NumberStyles.Any, CultureInfo.InvariantCulture, out var parsed))
                {
                    resolved = parsed;
                }
            }
        }

        if (resolved < 1)
        {
            resolved = 1;
        }

        return Math.Min(resolved, max);
    }
}

/// <summary>Raised when a bounded-composition assertion fails.</summary>
public sealed class AssertionFailedException : Exception
{
    public AssertionFailedException(string message) : base(message)
    {
    }
}

/// <summary>Raised when a required binding value cannot be resolved.</summary>
public sealed class BindingFailedException : Exception
{
    public BindingFailedException(string message) : base(message)
    {
    }
}
