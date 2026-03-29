using System.Net.Http.Headers;
using System.Text;
using System.Text.Json;
using Azure.Identity;

namespace AzureCosmosDB.MCP.Toolkit.Services;

/// <summary>
/// Service for managing Cosmos DB container copy jobs via the ARM copyJobs REST API.
/// Uses DefaultAzureCredential for ARM authentication.
/// </summary>
public class CopyJobService
{
    private readonly IHttpClientFactory _httpClientFactory;
    private readonly ILogger<CopyJobService> _logger;
    private readonly IConfiguration _configuration;

    private const string ApiVersion = "2025-05-01-preview";
    private const string ArmScope = "https://management.azure.com/.default";

    public CopyJobService(
        IHttpClientFactory httpClientFactory,
        ILogger<CopyJobService> logger,
        IConfiguration configuration)
    {
        _httpClientFactory = httpClientFactory ?? throw new ArgumentNullException(nameof(httpClientFactory));
        _logger = logger ?? throw new ArgumentNullException(nameof(logger));
        _configuration = configuration ?? throw new ArgumentNullException(nameof(configuration));
    }

    /// <summary>
    /// Extracts the Cosmos DB account name from the COSMOS_ENDPOINT environment variable.
    /// e.g., "https://myaccount.documents.azure.com:443/" → "myaccount"
    /// </summary>
    private string GetAccountName()
    {
        var endpoint = Environment.GetEnvironmentVariable("COSMOS_ENDPOINT")
            ?? _configuration["Cosmos:Endpoint"]
            ?? throw new InvalidOperationException("COSMOS_ENDPOINT is not configured.");

        var uri = new Uri(endpoint);
        var host = uri.Host; // e.g., "myaccount.documents.azure.com"
        var accountName = host.Split('.')[0];
        return accountName;
    }

    /// <summary>
    /// Gets an ARM access token using DefaultAzureCredential.
    /// </summary>
    private async Task<string> GetArmTokenAsync(CancellationToken cancellationToken)
    {
        var credential = new DefaultAzureCredential();
        var tokenResult = await credential.GetTokenAsync(
            new Azure.Core.TokenRequestContext([ArmScope]),
            cancellationToken);
        return tokenResult.Token;
    }

    /// <summary>
    /// Creates an authenticated HttpRequestMessage for ARM REST API calls.
    /// </summary>
    private async Task<HttpRequestMessage> CreateArmRequestAsync(
        HttpMethod method, string url,
        HttpContent? content = null,
        CancellationToken cancellationToken = default)
    {
        var token = await GetArmTokenAsync(cancellationToken);
        var request = new HttpRequestMessage(method, url) { Content = content };
        request.Headers.Authorization = new AuthenticationHeaderValue("Bearer", token);
        request.Headers.Accept.Add(new MediaTypeWithQualityHeaderValue("application/json"));
        return request;
    }

    /// <summary>
    /// Discovers the ARM resource ID for the Cosmos DB account by listing accounts in the subscription.
    /// </summary>
    private async Task<string> GetAccountResourceIdAsync(string subscriptionId, CancellationToken cancellationToken)
    {
        var accountName = GetAccountName();
        var client = _httpClientFactory.CreateClient();
        var url = $"https://management.azure.com/subscriptions/{Uri.EscapeDataString(subscriptionId)}" +
                  $"/providers/Microsoft.DocumentDB/databaseAccounts?api-version=2024-05-15";

        using var request = await CreateArmRequestAsync(HttpMethod.Get, url, cancellationToken: cancellationToken);
        var response = await client.SendAsync(request, cancellationToken);
        var body = await response.Content.ReadAsStringAsync(cancellationToken);

        if (!response.IsSuccessStatusCode)
        {
            throw new HttpRequestException($"Failed to list Cosmos DB accounts (HTTP {(int)response.StatusCode}): {body}");
        }

        using var doc = JsonDocument.Parse(body);
        if (doc.RootElement.TryGetProperty("value", out var accounts))
        {
            foreach (var account in accounts.EnumerateArray())
            {
                if (account.TryGetProperty("name", out var nameProp) &&
                    string.Equals(nameProp.GetString(), accountName, StringComparison.OrdinalIgnoreCase))
                {
                    return account.GetProperty("id").GetString()!;
                }
            }
        }

        throw new InvalidOperationException(
            $"Cosmos DB account '{accountName}' not found in subscription '{subscriptionId}'.");
    }

    private string BuildCopyJobsUrl(string accountResourceId, string? jobName = null)
    {
        var url = $"https://management.azure.com{accountResourceId}/copyJobs";
        if (!string.IsNullOrEmpty(jobName))
        {
            url += $"/{Uri.EscapeDataString(jobName)}";
        }
        url += $"?api-version={ApiVersion}";
        return url;
    }

    public async Task<object> CreateCopyJob(
        string subscriptionId, string jobName, string jobPropertiesJson,
        string? mode = null, int? workerCount = null,
        CancellationToken cancellationToken = default)
    {
        try
        {
            if (string.IsNullOrWhiteSpace(subscriptionId))
                throw new ArgumentException("Parameter 'subscriptionId' is required.", nameof(subscriptionId));
            if (string.IsNullOrWhiteSpace(jobName))
                throw new ArgumentException("Parameter 'jobName' is required.", nameof(jobName));
            if (string.IsNullOrWhiteSpace(jobPropertiesJson))
                throw new ArgumentException("Parameter 'jobProperties' is required.", nameof(jobPropertiesJson));

            // Parse and validate job properties
            JsonElement jobProps;
            try
            {
                using var propsDoc = JsonDocument.Parse(jobPropertiesJson);
                jobProps = propsDoc.RootElement.Clone();
            }
            catch (JsonException ex)
            {
                throw new ArgumentException($"Invalid JSON in jobProperties: {ex.Message}", ex);
            }

            var accountResourceId = await GetAccountResourceIdAsync(subscriptionId, cancellationToken);

            // Build request body
            var properties = new Dictionary<string, object> { ["jobProperties"] = jobProps };
            if (!string.IsNullOrEmpty(mode))
                properties["mode"] = mode;
            if (workerCount.HasValue)
                properties["workerCount"] = workerCount.Value;

            var body = JsonSerializer.Serialize(new { properties });

            var client = _httpClientFactory.CreateClient();
            var url = BuildCopyJobsUrl(accountResourceId, jobName);

            _logger.LogInformation("Creating copy job '{JobName}' on account", jobName);

            using var request = await CreateArmRequestAsync(
                HttpMethod.Put, url,
                new StringContent(body, Encoding.UTF8, "application/json"),
                cancellationToken);
            var response = await client.SendAsync(request, cancellationToken);
            var responseBody = await response.Content.ReadAsStringAsync(cancellationToken);

            if (!response.IsSuccessStatusCode)
            {
                return new { error = $"Failed to create copy job (HTTP {(int)response.StatusCode}): {responseBody}" };
            }

            using var doc = JsonDocument.Parse(responseBody);
            return doc.RootElement.Clone();
        }
        catch (Exception ex) when (ex is not ArgumentException)
        {
            _logger.LogError(ex, "Error creating copy job");
            return new { error = ex.Message };
        }
    }

    public async Task<object> GetCopyJob(
        string subscriptionId, string jobName,
        CancellationToken cancellationToken = default)
    {
        try
        {
            if (string.IsNullOrWhiteSpace(subscriptionId))
                throw new ArgumentException("Parameter 'subscriptionId' is required.", nameof(subscriptionId));
            if (string.IsNullOrWhiteSpace(jobName))
                throw new ArgumentException("Parameter 'jobName' is required.", nameof(jobName));

            var accountResourceId = await GetAccountResourceIdAsync(subscriptionId, cancellationToken);
            var client = _httpClientFactory.CreateClient();
            var url = BuildCopyJobsUrl(accountResourceId, jobName);

            using var request = await CreateArmRequestAsync(HttpMethod.Get, url, cancellationToken: cancellationToken);
            var response = await client.SendAsync(request, cancellationToken);
            var responseBody = await response.Content.ReadAsStringAsync(cancellationToken);

            if (!response.IsSuccessStatusCode)
            {
                return new { error = $"Failed to get copy job (HTTP {(int)response.StatusCode}): {responseBody}" };
            }

            using var doc = JsonDocument.Parse(responseBody);
            return doc.RootElement.Clone();
        }
        catch (Exception ex) when (ex is not ArgumentException)
        {
            _logger.LogError(ex, "Error getting copy job");
            return new { error = ex.Message };
        }
    }

    public async Task<object> ListCopyJobs(
        string subscriptionId,
        CancellationToken cancellationToken = default)
    {
        try
        {
            if (string.IsNullOrWhiteSpace(subscriptionId))
                throw new ArgumentException("Parameter 'subscriptionId' is required.", nameof(subscriptionId));

            var accountResourceId = await GetAccountResourceIdAsync(subscriptionId, cancellationToken);
            var client = _httpClientFactory.CreateClient();
            var jobs = new List<JsonElement>();
            var url = BuildCopyJobsUrl(accountResourceId);

            while (!string.IsNullOrEmpty(url))
            {
                using var request = await CreateArmRequestAsync(HttpMethod.Get, url, cancellationToken: cancellationToken);
                var response = await client.SendAsync(request, cancellationToken);
                var responseBody = await response.Content.ReadAsStringAsync(cancellationToken);

                if (!response.IsSuccessStatusCode)
                {
                    return new { error = $"Failed to list copy jobs (HTTP {(int)response.StatusCode}): {responseBody}" };
                }

                using var doc = JsonDocument.Parse(responseBody);
                if (doc.RootElement.TryGetProperty("value", out var valueArray))
                {
                    foreach (var item in valueArray.EnumerateArray())
                    {
                        jobs.Add(item.Clone());
                    }
                }

                url = doc.RootElement.TryGetProperty("nextLink", out var nextLink)
                    ? nextLink.GetString()
                    : null;
            }

            return jobs;
        }
        catch (Exception ex) when (ex is not ArgumentException)
        {
            _logger.LogError(ex, "Error listing copy jobs");
            return new { error = ex.Message };
        }
    }

    public async Task<object> CopyJobAction(
        string subscriptionId, string jobName, string action,
        CancellationToken cancellationToken = default)
    {
        try
        {
            if (string.IsNullOrWhiteSpace(subscriptionId))
                throw new ArgumentException("Parameter 'subscriptionId' is required.", nameof(subscriptionId));
            if (string.IsNullOrWhiteSpace(jobName))
                throw new ArgumentException("Parameter 'jobName' is required.", nameof(jobName));

            var accountResourceId = await GetAccountResourceIdAsync(subscriptionId, cancellationToken);
            var client = _httpClientFactory.CreateClient();
            var url = $"https://management.azure.com{accountResourceId}/copyJobs" +
                      $"/{Uri.EscapeDataString(jobName)}/{action}?api-version={ApiVersion}";

            _logger.LogInformation("{Action} copy job '{JobName}'", action, jobName);

            using var request = await CreateArmRequestAsync(
                HttpMethod.Post, url,
                new StringContent("{}", Encoding.UTF8, "application/json"),
                cancellationToken);
            var response = await client.SendAsync(request, cancellationToken);
            var responseBody = await response.Content.ReadAsStringAsync(cancellationToken);

            if (!response.IsSuccessStatusCode)
            {
                return new { error = $"Failed to {action} copy job (HTTP {(int)response.StatusCode}): {responseBody}" };
            }

            if (string.IsNullOrWhiteSpace(responseBody))
            {
                return new { status = $"{action} accepted", jobName };
            }

            using var doc = JsonDocument.Parse(responseBody);
            return doc.RootElement.Clone();
        }
        catch (Exception ex) when (ex is not ArgumentException)
        {
            _logger.LogError(ex, "Error performing {Action} on copy job", action);
            return new { error = ex.Message };
        }
    }
}
