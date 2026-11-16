using System.Globalization;
using System.Net.Http.Json;
using System.Text.Json;

namespace AzureCosmosDB.MCP.Toolkit.Services;

/// <summary>
/// Sends an agentic_search request to the agentic retrieval service (POST /agentic_search)
/// and returns its JSON response. Failures to reach the service, timeouts and empty
/// responses return an { "error": ... } JSON object instead.
/// </summary>
/// <remarks>
/// Reads COSMOS_RETRIEVER_URL (default http://127.0.0.1:9000) and
/// COSMOS_RETRIEVER_TIMEOUT_S (default 600) on every call.
/// </remarks>
public static class AgenticSearchExecutor
{
    public const string BaseUrlEnvVar = "COSMOS_RETRIEVER_URL";

    public const string TimeoutEnvVar = "COSMOS_RETRIEVER_TIMEOUT_S";

    public const string DefaultBaseUrl = "http://127.0.0.1:9000";

    public const int DefaultTimeoutSeconds = 600;

    private const int BodyTruncateChars = 4096;

    // Reuse one HttpClient (avoids socket exhaustion). No global timeout —
    // each request sets its own timeout instead.
    private static readonly HttpClient HttpClient = new()
    {
        Timeout = Timeout.InfiniteTimeSpan,
    };

    /// <summary>
    /// Send one question to the agentic retrieval service.
    /// </summary>
    /// <param name="query">Natural-language question.</param>
    /// <param name="maxDocuments">Maximum number of supporting documents to return (1-50).</param>
    /// <param name="logger">Logger for request lifecycle events.</param>
    /// <param name="database">Database to search, or null to let the agent choose.</param>
    /// <param name="container">Container to search, or null to let the agent choose.</param>
    /// <param name="cancellationToken">A token the caller can trip to abort the request early.</param>
    /// <returns>
    /// The service's response body with surrounding whitespace removed.
    /// Connection failures, request timeouts, and empty responses return a
    /// serialised <c>{ "error": "...", ... }</c> envelope. Non-success responses
    /// that look like JSON are passed through, otherwise they are wrapped in an
    /// error envelope. Response bodies are not validated as JSON.
    /// </returns>
    public static async Task<string> RunAsync(
        string query,
        int maxDocuments,
        ILogger logger,
        string? database = null,
        string? container = null,
        CancellationToken cancellationToken = default)
    {
        var baseUrl = ResolveString(BaseUrlEnvVar, DefaultBaseUrl).TrimEnd('/');
        var timeoutSeconds = ResolveInt(TimeoutEnvVar, DefaultTimeoutSeconds);
        if (!Uri.TryCreate(baseUrl, UriKind.Absolute, out var serviceUri) ||
            (serviceUri.Scheme != Uri.UriSchemeHttp && serviceUri.Scheme != Uri.UriSchemeHttps))
        {
            return ErrorEnvelope($"{BaseUrlEnvVar} must be an absolute HTTP or HTTPS URL.");
        }
        var requestUri = $"{baseUrl}/agentic_search";

        var payload = new Dictionary<string, object?>
        {
            ["query"] = query,
            ["maxDocuments"] = maxDocuments,
        };
        if (!string.IsNullOrWhiteSpace(database)) payload["database"] = database;
        if (!string.IsNullOrWhiteSpace(container)) payload["container"] = container;

        logger.LogInformation(
            "agentic_search: POST {RequestUri} (database={Database} container={Container} timeout={Timeout}s)",
            requestUri, database ?? "<any>", container ?? "<any>", timeoutSeconds);

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
                hint: $"Increase {TimeoutEnvVar} or check that the agentic retrieval service at {baseUrl} is responsive.");
        }
        catch (HttpRequestException ex)
        {
            logger.LogError(ex,
                "agentic_search: failed to reach the agentic retrieval service at {BaseUrl}.", baseUrl);
            return ErrorEnvelope(
                $"Failed to reach the agentic retrieval service: {ex.Message}",
                hint: $"Check that the agentic retrieval service is running and set {BaseUrlEnvVar} to its base URL (default {DefaultBaseUrl}).");
        }

        using (response)
        {
            var body = (await response.Content.ReadAsStringAsync(cancellationToken).ConfigureAwait(false)).Trim();

            if (!response.IsSuccessStatusCode)
            {
                logger.LogWarning(
                    "agentic_search: service returned {StatusCode}. body tail: {Body}",
                    (int)response.StatusCode, TruncateTail(body, 512));

                // The service returns JSON errors; pass them through, wrap anything else.
                if (LooksLikeJson(body))
                {
                    return body;
                }
                return ErrorEnvelope(
                    $"agentic_search service returned HTTP {(int)response.StatusCode}.",
                    bodyTail: TruncateTail(body, BodyTruncateChars));
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
