using System.Globalization;
using System.Net.Http.Json;
using System.Text.Json;

namespace AzureCosmosDB.MCP.Toolkit.Services;

/// <summary>
/// Calls the long-lived <c>cosmos-retriever</c> FastAPI service over HTTP and
/// returns its response body (a single JSON document) verbatim.
/// </summary>
/// <remarks>
/// <para>
/// The Python helper runs a multi-turn retrieval agent against an Azure Cosmos
/// DB corpus and returns a JSON document of curated, ranked results. It is
/// started once (<c>python -m cosmos_retriever serve</c>) and kept warm so the
/// heavy clients (Cosmos SDK, embeddings, model encoder) are not re-initialised
/// on every call.
/// </para>
///
/// <para>Host environment variables (read on every call):</para>
/// <list type="table">
///   <listheader><term>Variable</term><description>Default / purpose</description></listheader>
///   <item>
///     <term><see cref="BaseUrlEnvVar"/> (COSMOS_RETRIEVER_URL)</term>
///     <description>Base URL of the cosmos-retriever FastAPI service.
///       Defaults to <see cref="DefaultBaseUrl"/>.</description>
///   </item>
///   <item>
///     <term><see cref="TimeoutEnvVar"/> (COSMOS_RETRIEVER_TIMEOUT_S)</term>
///     <description>Per-request wall-clock cap in seconds; the request is
///       abandoned if it exceeds the timeout. Defaults to
///       <see cref="DefaultTimeoutSeconds"/>.</description>
///   </item>
/// </list>
///
/// <para>
/// The retriever service owns its own configuration (model endpoint,
/// <c>ACCOUNT_URI</c>, <c>COSMOS_DATABASE</c>, <c>COSMOS_CORPUS_CONTAINER</c>,
/// <c>CORPUS_REGISTRY_FILE</c>, <c>AZURE_OPENAI_*</c>, etc.) read from its own
/// environment / <c>.env</c> file; none of it flows through this process.
/// </para>
/// </remarks>
public static class AgenticSearchExecutor
{
    public const string BaseUrlEnvVar = "COSMOS_RETRIEVER_URL";

    /// <summary>
    /// Optional JSON map of <c>{ "&lt;database&gt;": "&lt;retriever base url&gt;" }</c>.
    /// When a request targets a database present in this map, that retriever
    /// endpoint is used instead of <see cref="BaseUrlEnvVar"/>. Lets different
    /// databases be served by different retriever deployments.
    /// </summary>
    public const string BaseUrlMapEnvVar = "COSMOS_RETRIEVER_URL_MAP";

    public const string TimeoutEnvVar = "COSMOS_RETRIEVER_TIMEOUT_S";

    public const string DefaultBaseUrl = "http://127.0.0.1:9000";

    public const int DefaultTimeoutSeconds = 600;

    private const int BodyTruncateBytes = 4096;

    // A single shared HttpClient with no built-in timeout — each call drives
    // its own deadline via a linked CancellationTokenSource.
    private static readonly HttpClient HttpClient = new()
    {
        Timeout = Timeout.InfiniteTimeSpan,
    };

    /// <summary>
    /// Run a single <c>cosmos-retriever</c> search by calling the FastAPI
    /// <c>POST /search</c> endpoint.
    /// </summary>
    /// <param name="query">Natural-language information need.</param>
    /// <param name="maxDocuments">Cap on the number of curated docs returned (1–50).</param>
    /// <param name="logger">Logger for request lifecycle events.</param>
    /// <param name="database">Optional Cosmos database override.</param>
    /// <param name="container">Optional Cosmos container override.</param>
    /// <param name="temperature">Optional LLM sampling temperature (0.0–2.0).</param>
    /// <param name="maxTurns">Optional cap on agent reasoning turns (1–200).</param>
    /// <param name="reasoningEffort">Optional reasoning effort ("low"/"medium"/"high").</param>
    /// <param name="schemaOverride">Optional schema override as a JSON object (keys:
    /// document_id_path, chunk_id_path, chunk_order_path, title_path, source_path,
    /// item_id_path, use_dunder_codec), or "none" for pure discovery.</param>
    /// <param name="searchDisplayLimit">Optional cap on hits surfaced per search (1–50).</param>
    /// <param name="accountUri">Optional Cosmos account endpoint override for this call.</param>
    /// <param name="embeddingModel">Optional embedding model/deployment override for this call.</param>
    /// <param name="embeddingEndpoint">Optional embedding endpoint base URL override for this call.</param>
    /// <param name="cancellationToken">Cooperative cancellation.</param>
    /// <returns>
    /// The service's response body, expected to be a single JSON document. On
    /// any failure (service unreachable, timed out, non-success status, empty
    /// body) returns a serialised <c>{ "error": "...", ... }</c> envelope so
    /// the MCP tool always returns parseable JSON to the caller.
    /// </returns>
    /// <remarks>
    /// The optional tuning knobs are forwarded to the retriever service as a
    /// per-request <c>overrides</c> object (mapping to the Python
    /// <c>RuntimeConfig</c>). Only non-null values are sent; anything omitted
    /// falls back to the retriever's own configured defaults.
    /// </remarks>
    public static async Task<string> RunAsync(
        string query,
        int maxDocuments,
        ILogger logger,
        string? database = null,
        string? container = null,
        double? temperature = null,
        int? maxTurns = null,
        string? reasoningEffort = null,
        string? schemaOverride = null,
        int? searchDisplayLimit = null,
        string? accountUri = null,
        string? embeddingModel = null,
        string? embeddingEndpoint = null,
        CancellationToken cancellationToken = default)
    {
        var baseUrl = ResolveBaseUrl(database).TrimEnd('/');
        var timeoutSeconds = ResolveInt(TimeoutEnvVar, DefaultTimeoutSeconds);
        var requestUri = $"{baseUrl}/search";

        var payload = new Dictionary<string, object?>
        {
            ["query"] = query,
            ["maxDocuments"] = maxDocuments,
        };
        if (!string.IsNullOrWhiteSpace(database)) payload["database"] = database;
        if (!string.IsNullOrWhiteSpace(container)) payload["container"] = container;

        // Per-request tuning knobs -> the retriever's RuntimeConfig overrides.
        // Only include knobs the caller actually set; omit the rest so the
        // service applies its own defaults.
        var overrides = new Dictionary<string, object?>();
        if (temperature is not null) overrides["chat_temperature"] = temperature;
        if (maxTurns is not null) overrides["chat_max_turns"] = maxTurns;
        if (!string.IsNullOrWhiteSpace(reasoningEffort)) overrides["chat_reasoning_effort"] = reasoningEffort;
        if (!string.IsNullOrWhiteSpace(schemaOverride) && !string.Equals(schemaOverride, "none", StringComparison.OrdinalIgnoreCase))
        {
            // Forward the schema override as a nested JSON object so the retriever
            // receives a structured override (its RuntimeConfig coerces it).
            try
            {
                using var doc = JsonDocument.Parse(schemaOverride);
                overrides["schema_override"] = doc.RootElement.Clone();
            }
            catch (JsonException)
            {
                overrides["schema_override"] = schemaOverride;
            }
        }
        if (searchDisplayLimit is not null) overrides["search_display_limit"] = searchDisplayLimit;
        if (!string.IsNullOrWhiteSpace(accountUri)) overrides["account_uri"] = accountUri;
        if (!string.IsNullOrWhiteSpace(embeddingModel)) overrides["openai_embedding_model"] = embeddingModel;
        if (!string.IsNullOrWhiteSpace(embeddingEndpoint)) overrides["embed_endpoint"] = embeddingEndpoint;
        if (overrides.Count > 0) payload["overrides"] = overrides;

        logger.LogInformation(
            "agentic_search: POST {RequestUri} (database={Database} container={Container} timeout={Timeout}s overrides={OverrideCount})",
            requestUri, database ?? "<env>", container ?? "<env>", timeoutSeconds, overrides.Count);

        using var timeoutCts = CancellationTokenSource.CreateLinkedTokenSource(cancellationToken);
        timeoutCts.CancelAfter(TimeSpan.FromSeconds(timeoutSeconds));

        HttpResponseMessage response;
        try
        {
            using var content = JsonContent.Create(payload);
            response = await HttpClient
                .PostAsync(requestUri, content, timeoutCts.Token)
                .ConfigureAwait(false);
        }
        catch (OperationCanceledException) when (timeoutCts.IsCancellationRequested && !cancellationToken.IsCancellationRequested)
        {
            logger.LogWarning("agentic_search: request exceeded {Timeout}s.", timeoutSeconds);
            return ErrorEnvelope(
                $"agentic_search timed out after {timeoutSeconds}s.",
                hint: $"Increase {TimeoutEnvVar} or check that the cosmos-retriever service at {baseUrl} is responsive.");
        }
        catch (HttpRequestException ex)
        {
            logger.LogError(ex,
                "agentic_search: failed to reach the cosmos-retriever service at {BaseUrl}.", baseUrl);
            return ErrorEnvelope(
                $"Failed to reach the cosmos-retriever service: {ex.Message}",
                hint: $"Start it with 'python -m cosmos_retriever serve' and set {BaseUrlEnvVar} to its base URL (default {DefaultBaseUrl}).");
        }

        using (response)
        {
            var body = (await response.Content.ReadAsStringAsync(cancellationToken).ConfigureAwait(false)).Trim();

            if (!response.IsSuccessStatusCode)
            {
                logger.LogWarning(
                    "agentic_search: service returned {StatusCode}. body tail: {Body}",
                    (int)response.StatusCode, TruncateTail(body, 512));

                // The FastAPI service emits its own JSON error envelope on most
                // failures; pass it through verbatim if so, otherwise wrap it.
                if (LooksLikeJson(body))
                {
                    return body;
                }
                return ErrorEnvelope(
                    $"agentic_search service returned HTTP {(int)response.StatusCode}.",
                    bodyTail: TruncateTail(body, BodyTruncateBytes));
            }

            if (string.IsNullOrWhiteSpace(body))
            {
                return ErrorEnvelope("agentic_search service produced no output.");
            }

            return body;
        }
    }

    private static string ResolveString(string envVar, string defaultValue)
    {
        var value = Environment.GetEnvironmentVariable(envVar);
        return string.IsNullOrWhiteSpace(value) ? defaultValue : value;
    }

    // Resolve the retriever base URL for a request, preferring a per-database
    // override from COSMOS_RETRIEVER_URL_MAP (JSON {"<db>":"<url>"}) and falling
    // back to COSMOS_RETRIEVER_URL / the built-in default.
    private static string ResolveBaseUrl(string? database)
    {
        if (!string.IsNullOrWhiteSpace(database))
        {
            var raw = Environment.GetEnvironmentVariable(BaseUrlMapEnvVar);
            if (!string.IsNullOrWhiteSpace(raw) && LooksLikeJson(raw))
            {
                try
                {
                    var map = JsonSerializer.Deserialize<Dictionary<string, string>>(
                        raw, new JsonSerializerOptions { PropertyNameCaseInsensitive = true });
                    if (map is not null)
                    {
                        foreach (var kv in map)
                        {
                            if (string.Equals(kv.Key, database, StringComparison.OrdinalIgnoreCase)
                                && !string.IsNullOrWhiteSpace(kv.Value))
                            {
                                return kv.Value;
                            }
                        }
                    }
                }
                catch (JsonException)
                {
                    // Malformed map -> fall through to the default endpoint.
                }
            }
        }
        return ResolveString(BaseUrlEnvVar, defaultValue: DefaultBaseUrl);
    }

    private static int ResolveInt(string envVar, int defaultValue)
    {
        var raw = Environment.GetEnvironmentVariable(envVar);
        if (!string.IsNullOrWhiteSpace(raw) && int.TryParse(raw, NumberStyles.Integer, CultureInfo.InvariantCulture, out var parsed) && parsed > 0)
        {
            return parsed;
        }
        return defaultValue;
    }

    private static bool LooksLikeJson(string s) =>
        s.Length > 0 && (s[0] == '{' || s[0] == '[');

    private static string ErrorEnvelope(string error, string? hint = null, string? bodyTail = null)
    {
        var payload = new Dictionary<string, object?> { ["error"] = error };
        if (hint is not null) payload["hint"] = hint;
        if (bodyTail is not null) payload["body"] = bodyTail;
        return JsonSerializer.Serialize(payload);
    }

    private static string TruncateTail(string s, int maxChars)
    {
        if (string.IsNullOrEmpty(s) || s.Length <= maxChars) return s ?? string.Empty;
        return "..." + s[^maxChars..];
    }
}
