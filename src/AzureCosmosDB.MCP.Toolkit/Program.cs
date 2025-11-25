// Program.cs
using ModelContextProtocol.Server;
using System.ComponentModel;
using Microsoft.Azure.Cosmos;
using System.Text.Json;
using Azure.Identity;
using System.Text.RegularExpressions;
using Azure.AI.OpenAI;
using Microsoft.AspNetCore.Authentication.JwtBearer;
using Microsoft.AspNetCore.Authorization;
using Microsoft.AspNetCore.HttpOverrides;
using Microsoft.IdentityModel.Tokens;
using System.IdentityModel.Tokens.Jwt;

var builder = WebApplication.CreateBuilder(args);

// Add controllers
builder.Services.AddControllers();

// Disable default claim mapping for cleaner token handling
JwtSecurityTokenHandler.DefaultMapInboundClaims = false;

// Configure for container environment
builder.WebHost.ConfigureKestrel(options =>
{
    // Container Apps expects port 8080
    options.ListenAnyIP(8080);
});

// Get Azure AD configuration from appsettings
var azureAd = builder.Configuration.GetSection("AzureAd");
var tenantId = azureAd["TenantId"];
var clientId = azureAd["ClientId"];
var audienceConfig = azureAd["Audience"];

// Check if authentication should be bypassed for development
var devBypassAuth = Environment.GetEnvironmentVariable("DEV_BYPASS_AUTH") == "true" || 
                   builder.Configuration.GetValue<bool>("DevelopmentMode:BypassAuthentication");
var isDevelopment = builder.Environment.IsDevelopment();

if (!devBypassAuth && !string.IsNullOrEmpty(tenantId) && !string.IsNullOrEmpty(clientId))
{
    // Build list of valid audiences
    var validAudiences = new List<string> { clientId, $"api://{clientId}" };
    
    // Add audiences from configuration (supports comma-separated values)
    if (!string.IsNullOrEmpty(audienceConfig))
    {
        var configuredAudiences = audienceConfig.Split(',', StringSplitOptions.RemoveEmptyEntries | StringSplitOptions.TrimEntries);
        foreach (var aud in configuredAudiences)
        {
            if (!validAudiences.Contains(aud))
            {
                validAudiences.Add(aud);
            }
        }
    }
    
    // Add JWT Bearer authentication only if configuration is available
    builder.Services
        .AddAuthentication(JwtBearerDefaults.AuthenticationScheme)
        .AddJwtBearer(options =>
        {
            options.Authority = $"https://login.microsoftonline.com/{tenantId}/v2.0";

            options.TokenValidationParameters = new TokenValidationParameters
            {
                // Multi-tenant support: Accept tokens from any Azure AD tenant
                ValidateIssuer = true,
                // Accept both v1.0 and v2.0 tokens from any tenant
                IssuerValidator = (issuer, securityToken, validationParameters) =>
                {
                    // Accept issuers matching either pattern from any tenant:
                    // v2.0: https://login.microsoftonline.com/{tenantId}/v2.0
                    // v1.0: https://sts.windows.net/{tenantId}/
                    if (issuer.StartsWith("https://login.microsoftonline.com/") && issuer.EndsWith("/v2.0") ||
                        issuer.StartsWith("https://sts.windows.net/") && issuer.EndsWith("/"))
                    {
                        return issuer;
                    }
                    throw new SecurityTokenInvalidIssuerException($"Invalid issuer: {issuer}");
                },

                ValidateAudience = true,
                ValidAudiences = validAudiences,

                ValidateLifetime = true,
                ValidateIssuerSigningKey = true,
                ClockSkew = TimeSpan.FromMinutes(2),
                RoleClaimType = "roles",
            };

            options.MapInboundClaims = false;
            options.RefreshOnIssuerKeyNotFound = true;

            // Add detailed logging for authentication events
            options.Events = new JwtBearerEvents
            {
                OnMessageReceived = context =>
                {
                    var logger = context.HttpContext.RequestServices.GetRequiredService<ILogger<Program>>();
                    
                    // Check query parameter first (Container Apps doesn't strip this)
                    if (string.IsNullOrEmpty(context.Token))
                    {
                        var accessToken = context.Request.Query["access_token"].FirstOrDefault();
                        if (!string.IsNullOrEmpty(accessToken))
                        {
                            context.Token = accessToken;
                            logger.LogInformation("Token retrieved from query parameter");
                        }
                    }
                    
                    // Workaround: Azure Container Apps ingress may strip Authorization header
                    // Check for custom header as fallback
                    if (string.IsNullOrEmpty(context.Token))
                    {
                        // Try multiple header names since Azure Container Apps may strip some
                        if (context.Request.Headers.TryGetValue("X-MS-TOKEN-AAD-ACCESS-TOKEN", out var tokenValue))
                        {
                            context.Token = tokenValue;
                            logger.LogInformation("Token retrieved from X-MS-TOKEN-AAD-ACCESS-TOKEN header");
                        }
                        else if (context.Request.Headers.TryGetValue("X-Access-Token", out var customTokenValue))
                        {
                            context.Token = customTokenValue;
                            logger.LogInformation("Token retrieved from X-Access-Token header");
                        }
                        else if (context.Request.Headers.TryGetValue("X-Auth-Token", out var authTokenValue))
                        {
                            context.Token = authTokenValue;
                            logger.LogInformation("Token retrieved from X-Auth-Token header");
                        }
                    }
                    
                    var hasAuth = context.Request.Headers.ContainsKey("Authorization");
                    var hasCustom = context.Request.Headers.ContainsKey("X-MS-TOKEN-AAD-ACCESS-TOKEN");
                    var hasQuery = !string.IsNullOrEmpty(context.Request.Query["access_token"].FirstOrDefault());
                    logger.LogInformation("Message received. Has Authorization header: {HasAuth}, Has X-MS-TOKEN-AAD-ACCESS-TOKEN: {HasCustom}, Has Query Token: {HasQuery}", hasAuth, hasCustom, hasQuery);
                    
                    return Task.CompletedTask;
                },
                OnAuthenticationFailed = context =>
                {
                    var logger = context.HttpContext.RequestServices.GetRequiredService<ILogger<Program>>();
                    logger.LogError("Authentication failed: {Error}", context.Exception.Message);
                    logger.LogError("Exception details: {Details}", context.Exception.ToString());
                    return Task.CompletedTask;
                },
                OnTokenValidated = context =>
                {
                    var logger = context.HttpContext.RequestServices.GetRequiredService<ILogger<Program>>();
                    logger.LogInformation("Token validated successfully for user: {User}", context.Principal?.Identity?.Name ?? "Unknown");
                    return Task.CompletedTask;
                },
                OnChallenge = context =>
                {
                    var logger = context.HttpContext.RequestServices.GetRequiredService<ILogger<Program>>();
                    logger.LogWarning("Authentication challenge: {Error}, {ErrorDescription}", context.Error, context.ErrorDescription);
                    
                    // Log ALL headers to debug
                    logger.LogWarning("All request headers:");
                    foreach (var header in context.Request.Headers)
                    {
                        logger.LogWarning("  {Key}: {Value}", header.Key, header.Value);
                    }
                    return Task.CompletedTask;
                }
            };
        });

    // Add authorization with policy for MCP Tool Executor role
    builder.Services.AddAuthorization(options =>
    {
        options.AddPolicy("McpToolExecutor", p => p.RequireRole("Mcp.Tool.Executor"));

        options.DefaultPolicy = new AuthorizationPolicyBuilder()
            .RequireAuthenticatedUser()
            .Build();
    });
}
else
{
    // Development mode - bypass authentication
    builder.Services.AddAuthorization(options =>
    {
        options.AddPolicy("McpToolExecutor", policy => policy.RequireAssertion(_ => true));
        options.DefaultPolicy = new AuthorizationPolicyBuilder()
            .RequireAssertion(_ => true)
            .Build();
    });
}

// Add HTTP context accessor for authentication
builder.Services.AddHttpContextAccessor();

// Add CORS for external MCP access
builder.Services.AddCors(options =>
{
    options.AddPolicy("MCPPolicy", policy =>
    {
        policy.AllowAnyOrigin()
              .AllowAnyMethod()
              .AllowAnyHeader()
              .WithExposedHeaders("Cross-Origin-Opener-Policy", "Cross-Origin-Embedder-Policy");
    });
});

// Add health checks for Azure Container Apps
builder.Services.AddHealthChecks();

// Register Cosmos DB Client as a singleton for dependency injection
builder.Services.AddSingleton(sp =>
{
    var endpoint = Environment.GetEnvironmentVariable("COSMOS_ENDPOINT");
    if (string.IsNullOrWhiteSpace(endpoint))
    {
        throw new InvalidOperationException("COSMOS_ENDPOINT environment variable is required.");
    }
    
    var credential = new DefaultAzureCredential();
    
    return new CosmosClient(endpoint, credential, new CosmosClientOptions
    {
        ApplicationName = "AzureCosmosDBMCP",
        // Enable detailed logging for diagnostics
        EnableContentResponseOnWrite = false,
        RequestTimeout = TimeSpan.FromSeconds(60)
    });
});

// Register services for dependency injection
builder.Services.AddScoped<AzureCosmosDB.MCP.Toolkit.Services.CosmosDbToolsService>();
builder.Services.AddScoped<AzureCosmosDB.MCP.Toolkit.Services.AuthenticationService>();

// Configure forwarded headers for proxy scenarios
builder.Services.Configure<ForwardedHeadersOptions>(options =>
{
    options.ForwardedHeaders = ForwardedHeaders.XForwardedFor | ForwardedHeaders.XForwardedProto;
    options.KnownNetworks.Clear();
    options.KnownProxies.Clear();
});

var app = builder.Build();

// Add security headers middleware to allow MSAL authentication
app.Use(async (context, next) =>
{
    // Fix COOP policy to allow MSAL popup authentication
    context.Response.Headers["Cross-Origin-Opener-Policy"] = "unsafe-none";
    context.Response.Headers["Cross-Origin-Embedder-Policy"] = "unsafe-none";
    
    await next();
});

// Add request logging middleware with User-Agent tracking
app.Use(async (context, next) =>
{
    var logger = context.RequestServices.GetRequiredService<ILogger<Program>>();
    var path = context.Request.Path.Value ?? "";
    var method = context.Request.Method;
    var userAgent = context.Request.Headers["User-Agent"].ToString();
    var clientIp = context.Connection.RemoteIpAddress?.ToString() ?? "unknown";
    
    // Log all requests with User-Agent for analytics
    logger.LogInformation(
        "Request: {Method} {Path} | User-Agent: {UserAgent} | Client-IP: {ClientIp}", 
        method, path, string.IsNullOrEmpty(userAgent) ? "Not-Specified" : userAgent, clientIp);
    
    // Detailed logging for MCP endpoints
    if (path.StartsWith("/mcp", StringComparison.OrdinalIgnoreCase))
    {
        logger.LogInformation("=== MCP REQUEST DETAILS ===");
        logger.LogInformation("Method: {Method}, Path: {Path}", method, path);
        logger.LogInformation("User-Agent: {UserAgent}", string.IsNullOrEmpty(userAgent) ? "Not-Specified" : userAgent);
        logger.LogInformation("Client-IP: {ClientIp}", clientIp);
        
        // Log other relevant headers (excluding sensitive data)
        if (context.Request.Headers.ContainsKey("Content-Type"))
            logger.LogInformation("Content-Type: {ContentType}", context.Request.Headers["Content-Type"].ToString());
        if (context.Request.Headers.ContainsKey("Accept"))
            logger.LogInformation("Accept: {Accept}", context.Request.Headers["Accept"].ToString());
        if (context.Request.Headers.ContainsKey("Referer"))
            logger.LogInformation("Referer: {Referer}", context.Request.Headers["Referer"].ToString());
        
        logger.LogInformation("=== END MCP REQUEST ===");
    }
    
    await next();
});

// Configure forwarded headers
app.UseForwardedHeaders();

// Add health check endpoint for container orchestrators
app.MapHealthChecks("/health");

// Enable CORS
app.UseCors("MCPPolicy");

// Configure static files with more explicit options
app.UseDefaultFiles(); // This will serve index.html as default
app.UseStaticFiles();

// Add routing first
app.UseRouting();

// Then authentication and authorization middleware (MUST be after UseRouting and before MapControllers)
app.UseAuthentication();
app.UseAuthorization();

// Development mode logging
if (isDevelopment || devBypassAuth)
{
    app.Logger.LogInformation("Running in development mode with authentication bypass");
}

// Map controllers last
app.MapControllers();

// Note: Commenting out built-in MCP endpoint to use custom controller
// Map MCP endpoints with specific path
// app.MapMcp("/mcp");

// Add a simple root endpoint as fallback
app.MapGet("/", () => Results.Redirect("/index.html"));

app.Run();

[McpServerToolType]
public static class CosmosDbTools
{
    // Environment variables used:
    // COSMOS_ENDPOINT - Cosmos DB account endpoint
    // OPENAI_ENDPOINT - Microsoft Foundry project endpoint (or legacy Azure OpenAI endpoint)
    // OPENAI_EMBEDDING_DEPLOYMENT - Embedding model deployment name in Microsoft Foundry/OpenAI
    // Auth uses Entra ID via DefaultAzureCredential (supports Managed Identity and service principals).

    [McpServerTool, Description("Lists databases available in the Cosmos DB account.")]
    public static async Task<string> ListDatabases()
    {
        try
        {
            var endpoint = Environment.GetEnvironmentVariable("COSMOS_ENDPOINT");
            if (string.IsNullOrWhiteSpace(endpoint))
            {
                return JsonSerializer.Serialize(new { error = "Missing required environment variable COSMOS_ENDPOINT." });
            }

            var credential = new DefaultAzureCredential();
            using var client = new CosmosClient(endpoint, credential, new CosmosClientOptions
            {
                ApplicationName = "AzureCosmosDBMCP"
            });

            var results = new List<string>();
            var iterator = client.GetDatabaseQueryIterator<DatabaseProperties>();
            while (iterator.HasMoreResults)
            {
                var page = await iterator.ReadNextAsync();
                foreach (var db in page)
                {
                    results.Add(db.Id);
                }
            }

            return JsonSerializer.Serialize(results);
        }
        catch (CosmosException cex)
        {
            return JsonSerializer.Serialize(new { error = cex.Message, statusCode = (int)cex.StatusCode });
        }
        catch (Exception ex)
        {
            return JsonSerializer.Serialize(new { error = ex.Message });
        }
    }

    [McpServerTool, Description("Lists containers (collections) for the specified database.")]
    public static async Task<string> ListCollections(
        [Description("Database id to list containers from")] string databaseId)
    {
        try
        {
            var endpoint = Environment.GetEnvironmentVariable("COSMOS_ENDPOINT");
            if (string.IsNullOrWhiteSpace(endpoint))
            {
                return JsonSerializer.Serialize(new { error = "Missing required environment variable COSMOS_ENDPOINT." });
            }

            if (string.IsNullOrWhiteSpace(databaseId))
            {
                return JsonSerializer.Serialize(new { error = "Parameter 'databaseId' is required." });
            }

            var credential = new DefaultAzureCredential();
            using var client = new CosmosClient(endpoint, credential, new CosmosClientOptions
            {
                ApplicationName = "AzureCosmosDBMCP"
            });

            var db = client.GetDatabase(databaseId);
            var results = new List<string>();
            var iterator = db.GetContainerQueryIterator<ContainerProperties>();
            while (iterator.HasMoreResults)
            {
                var page = await iterator.ReadNextAsync();
                foreach (var c in page)
                {
                    results.Add(c.Id);
                }
            }

            return JsonSerializer.Serialize(results);
        }
        catch (CosmosException cex)
        {
            return JsonSerializer.Serialize(new { error = cex.Message, statusCode = (int)cex.StatusCode });
        }
        catch (Exception ex)
        {
            return JsonSerializer.Serialize(new { error = ex.Message });
        }
    }

    [McpServerTool, Description("Gets the most recent N documents ordered by timestamp (_ts DESC) from the specified database/container. N must be between 1 and 20.")]
    public static async Task<string> GetRecentDocuments(
        [Description("Database id containing the container")] string databaseId,
        [Description("Container id to query")] string containerId,
        [Description("Number of documents to return (1-20)")] int n)
    {
        try
        {
            var endpoint = Environment.GetEnvironmentVariable("COSMOS_ENDPOINT");
            if (string.IsNullOrWhiteSpace(endpoint))
            {
                return JsonSerializer.Serialize(new { error = "Missing required environment variable COSMOS_ENDPOINT." });
            }
            if (string.IsNullOrWhiteSpace(databaseId) || string.IsNullOrWhiteSpace(containerId))
            {
                return JsonSerializer.Serialize(new { error = "Parameters 'databaseId' and 'containerId' are required." });
            }
            if (n < 1 || n > 20)
            {
                return JsonSerializer.Serialize(new { error = "Parameter 'n' must be a whole number between 1 and 20." });
            }

            var credential = new DefaultAzureCredential();
            using var client = new CosmosClient(endpoint, credential, new CosmosClientOptions
            {
                ApplicationName = "AzureCosmosDBMCP"
            });

            var container = client.GetContainer(databaseId, containerId);
            var queryText = $"SELECT TOP {n} * FROM c ORDER BY c._ts DESC";
            var iterator = container.GetItemQueryIterator<dynamic>(
                new QueryDefinition(queryText),
                requestOptions: new QueryRequestOptions { MaxItemCount = n }
            );

            var jsonDocs = new List<string>();
            while (iterator.HasMoreResults && jsonDocs.Count < n)
            {
                var page = await iterator.ReadNextAsync();
                foreach (var doc in page)
                {
                    jsonDocs.Add(doc?.ToString() ?? "{}");
                    if (jsonDocs.Count >= n) break;
                }
            }

            var jsonArray = "[" + string.Join(",", jsonDocs) + "]";
            return jsonArray;
        }
        catch (CosmosException cex)
        {
            return JsonSerializer.Serialize(new { error = cex.Message, statusCode = (int)cex.StatusCode });
        }
        catch (Exception ex)
        {
            return JsonSerializer.Serialize(new { error = ex.Message });
        }
    }

    [McpServerTool, Description("Select TOP N documents where a given property contains the provided search string. N must be between 1 and 20.")]
    public static async Task<string> TextSearch(
        [Description("Database id containing the container")] string databaseId,
        [Description("Container id to query")] string containerId,
        [Description("Document property to search, e.g. name or profile.name")] string property,
        [Description("Search term to look for within the property")] string searchPhrase,
        [Description("Number of documents to return (1-20)")] int n)
    {
        try
        {
            var endpoint = Environment.GetEnvironmentVariable("COSMOS_ENDPOINT");
            if (string.IsNullOrWhiteSpace(endpoint))
            {
                return JsonSerializer.Serialize(new { error = "Missing required environment variable COSMOS_ENDPOINT." });
            }
            if (string.IsNullOrWhiteSpace(databaseId) || string.IsNullOrWhiteSpace(containerId))
            {
                return JsonSerializer.Serialize(new { error = "Parameters 'databaseId' and 'containerId' are required." });
            }
            if (string.IsNullOrWhiteSpace(property))
            {
                return JsonSerializer.Serialize(new { error = "Parameter 'property' is required." });
            }
            if (n < 1 || n > 20)
            {
                return JsonSerializer.Serialize(new { error = "Parameter 'n' must be a whole number between 1 and 20." });
            }

            // Basic validation to avoid injection in the property path: allow letters, digits, underscore and dot segments.
            var propPattern = new Regex(@"^[A-Za-z_][A-Za-z0-9_]*(\.[A-Za-z_][A-Za-z0-9_]*)*$");
            if (!propPattern.IsMatch(property))
            {
                return JsonSerializer.Serialize(new { error = "Invalid property name. Use dot notation with letters, digits, and underscores only (e.g., name or profile.name)." });
            }

            var credential = new DefaultAzureCredential();
            using var client = new CosmosClient(endpoint, credential, new CosmosClientOptions
            {
                ApplicationName = "AzureCosmosDBMCP"
            });

            var container = client.GetContainer(databaseId, containerId);
            var queryText = $"SELECT TOP {n} * FROM c WHERE FullTextContains(c.{property}, @searchPhrase) ";
            var query = new QueryDefinition(queryText).WithParameter("@searchPhrase", searchPhrase);

            var iterator = container.GetItemQueryIterator<dynamic>(query, requestOptions: new QueryRequestOptions { MaxItemCount = n });

            var jsonDocs = new List<string>();
            while (iterator.HasMoreResults && jsonDocs.Count < n)
            {
                var page = await iterator.ReadNextAsync();
                foreach (var doc in page)
                {
                    jsonDocs.Add(doc?.ToString() ?? "{}");
                    if (jsonDocs.Count >= n) break;
                }
            }

            var jsonArray = "[" + string.Join(",", jsonDocs) + "]";
            return jsonArray;
        }
        catch (CosmosException cex)
        {
            return JsonSerializer.Serialize(new { error = cex.Message, statusCode = (int)cex.StatusCode });
        }
        catch (Exception ex)
        {
            return JsonSerializer.Serialize(new { error = ex.Message });
        }
    }

    [McpServerTool, Description("Find a document by its id in the specified database/container.")]
    public static async Task<string> FindDocumentByID(
        [Description("Database id containing the container")] string databaseId,
        [Description("Container id to query")] string containerId,
        [Description("The id of the document to find")] string id)
    {
        try
        {
            var endpoint = Environment.GetEnvironmentVariable("COSMOS_ENDPOINT");
            if (string.IsNullOrWhiteSpace(endpoint))
            {
                return JsonSerializer.Serialize(new { error = "Missing required environment variable COSMOS_ENDPOINT." });
            }
            if (string.IsNullOrWhiteSpace(databaseId) || string.IsNullOrWhiteSpace(containerId))
            {
                return JsonSerializer.Serialize(new { error = "Parameters 'databaseId' and 'containerId' are required." });
            }
            if (string.IsNullOrWhiteSpace(id))
            {
                return JsonSerializer.Serialize(new { error = "Parameter 'id' is required." });
            }

            var credential = new DefaultAzureCredential();
            using var client = new CosmosClient(endpoint, credential, new CosmosClientOptions
            {
                ApplicationName = "AzureCosmosDBMCP"
            });

            var container = client.GetContainer(databaseId, containerId);
            var queryText = "SELECT * FROM c WHERE c.id = @id";
            var query = new QueryDefinition(queryText).WithParameter("@id", id);

            var iterator = container.GetItemQueryIterator<dynamic>(query, requestOptions: new QueryRequestOptions { MaxItemCount = 1 });

            while (iterator.HasMoreResults)
            {
                var page = await iterator.ReadNextAsync();
                foreach (var doc in page)
                {
                    return doc?.ToString() ?? "{}";
                }
            }

            return JsonSerializer.Serialize(new { message = "No document found with the specified id." });
        }
        catch (CosmosException cex)
        {
            return JsonSerializer.Serialize(new { error = cex.Message, statusCode = (int)cex.StatusCode });
        }
        catch (Exception ex)
        {
            return JsonSerializer.Serialize(new { error = ex.Message });
        }
    }

    [McpServerTool, Description("Approximates a container schema by sampling up to 10 documents and returning a union of top-level properties with inferred types and brief descriptions.")]
    public static async Task<string> GetApproximateSchema(
        [Description("Database id containing the container")] string databaseId,
        [Description("Container id to inspect")] string containerId)
    {
        try
        {
            var endpoint = Environment.GetEnvironmentVariable("COSMOS_ENDPOINT");
            if (string.IsNullOrWhiteSpace(endpoint))
            {
                return JsonSerializer.Serialize(new { error = "Missing required environment variable COSMOS_ENDPOINT." });
            }
            if (string.IsNullOrWhiteSpace(databaseId) || string.IsNullOrWhiteSpace(containerId))
            {
                return JsonSerializer.Serialize(new { error = "Parameters 'databaseId' and 'containerId' are required." });
            }

            var credential = new DefaultAzureCredential();
            using var client = new CosmosClient(endpoint, credential, new CosmosClientOptions
            {
                ApplicationName = "AzureCosmosDBMCP"
            });

            var container = client.GetContainer(databaseId, containerId);
            var queryText = "SELECT TOP 10 * FROM c";
            var iterator = container.GetItemQueryIterator<dynamic>(
                new QueryDefinition(queryText),
                requestOptions: new QueryRequestOptions { MaxItemCount = 10 }
            );

            var typeMap = new Dictionary<string, HashSet<string>>(StringComparer.OrdinalIgnoreCase);
            var countMap = new Dictionary<string, int>(StringComparer.OrdinalIgnoreCase);
            int sampleCount = 0;

            while (iterator.HasMoreResults && sampleCount < 10)
            {
                var page = await iterator.ReadNextAsync();
                foreach (var doc in page)
                {
                    var json = doc?.ToString();
                    if (string.IsNullOrWhiteSpace(json)) continue;

                    try
                    {
                        using var parsed = JsonDocument.Parse(json);
                        if (parsed.RootElement.ValueKind != JsonValueKind.Object) continue;
                        sampleCount++;
                        
                        foreach (var prop in parsed.RootElement.EnumerateObject())
                        {
                            var name = prop.Name;
                            var kind = prop.Value.ValueKind;
                            string type = kind switch
                            {
                                JsonValueKind.String => "string",
                                JsonValueKind.Number => "number",
                                JsonValueKind.True => "boolean",
                                JsonValueKind.False => "boolean",
                                JsonValueKind.Object => "object",
                                JsonValueKind.Array => "array",
                                JsonValueKind.Null => "null",
                                _ => "unknown"
                            };

                            if (!typeMap.TryGetValue(name, out HashSet<string>? set))
                            {
                                set = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
                                typeMap[name] = set;
                            }
                            set!.Add(type);

                            countMap.TryGetValue(name, out int current);
                            countMap[name] = current + 1;
                        }
                    }
                    catch
                    {
                        // Ignore malformed JSON rows
                    }

                    if (sampleCount >= 10) break;
                }
            }

            if (sampleCount == 0)
            {
                return JsonSerializer.Serialize(new { message = "No documents found to infer schema." });
            }

            var properties = new List<object>();
            foreach (var kvp in typeMap.OrderBy(k => k.Key, StringComparer.OrdinalIgnoreCase))
            {
                var name = kvp.Key;
                var types = kvp.Value.OrderBy(t => t).ToArray();
                var typeStr = string.Join(" | ", types);
                countMap.TryGetValue(name, out int appearCount);
                var description = $"Appears in {appearCount}/{sampleCount} sampled documents.";
                properties.Add(new { name, type = typeStr, description });
            }

            var result = new { sampleSize = sampleCount, properties };
            return JsonSerializer.Serialize(result);
        }
        catch (CosmosException cex)
        {
            return JsonSerializer.Serialize(new { error = cex.Message, statusCode = (int)cex.StatusCode });
        }
        catch (Exception ex)
        {
            return JsonSerializer.Serialize(new { error = ex.Message });
        }
    }

    [McpServerTool, Description("Performs vector search on Cosmos DB using Azure OpenAI embeddings. Searches for semantically similar documents based on text input.")]
    public static async Task<string> VectorSearch(
        [Description("Database id containing the container")] string databaseId,
        [Description("Container id to query")] string containerId,
        [Description("Text to search for semantically similar content")] string searchText,
        [Description("Property name where vector embeddings are stored, e.g. 'vector' or 'embeddings'")] string vectorProperty,
        [Description("Comma-separated list of specific properties to project in results, e.g. 'id,title,content'. Cannot use '*' wildcard.")] string selectProperties,
        [Description("Number of documents to return (1-50)")] int topN)
    {
        try
        {
            // Validate environment variables
            var cosmosEndpoint = Environment.GetEnvironmentVariable("COSMOS_ENDPOINT");
            // OPENAI_ENDPOINT can be either a Microsoft Foundry project endpoint or legacy Azure OpenAI endpoint
            // Microsoft Foundry projects expose OpenAI-compatible endpoints (recommended)
            var openaiEndpoint = Environment.GetEnvironmentVariable("OPENAI_ENDPOINT");
            var embeddingDeployment = Environment.GetEnvironmentVariable("OPENAI_EMBEDDING_DEPLOYMENT");

            if (string.IsNullOrWhiteSpace(cosmosEndpoint))
            {
                return JsonSerializer.Serialize(new { error = "Missing required environment variable COSMOS_ENDPOINT." });
            }
            if (string.IsNullOrWhiteSpace(openaiEndpoint))
            {
                return JsonSerializer.Serialize(new { error = "Missing required environment variable OPENAI_ENDPOINT." });
            }
            if (string.IsNullOrWhiteSpace(embeddingDeployment))
            {
                return JsonSerializer.Serialize(new { error = "Missing required environment variable OPENAI_EMBEDDING_DEPLOYMENT." });
            }

            // Validate parameters
            if (string.IsNullOrWhiteSpace(databaseId) || string.IsNullOrWhiteSpace(containerId))
            {
                return JsonSerializer.Serialize(new { error = "Parameters 'databaseId' and 'containerId' are required." });
            }
            if (string.IsNullOrWhiteSpace(searchText))
            {
                return JsonSerializer.Serialize(new { error = "Parameter 'searchText' is required." });
            }
            if (string.IsNullOrWhiteSpace(vectorProperty))
            {
                return JsonSerializer.Serialize(new { error = "Parameter 'vectorProperty' is required." });
            }
            if (string.IsNullOrWhiteSpace(selectProperties))
            {
                return JsonSerializer.Serialize(new { error = "Parameter 'selectProperties' is required." });
            }
            if (topN < 1 || topN > 50)
            {
                return JsonSerializer.Serialize(new { error = "Parameter 'topN' must be a whole number between 1 and 50." });
            }

            // Validate that selectProperties doesn't contain wildcard
            if (selectProperties.Trim() == "*" || selectProperties.Contains("*"))
            {
                return JsonSerializer.Serialize(new { error = "Parameter 'selectProperties' cannot contain '*' wildcard. Please specify explicit property names separated by commas." });
            }

            // Validate property names (without c. prefix - we'll add it later)
            var propPattern = new Regex(@"^[A-Za-z_][A-Za-z0-9_]*(\.[A-Za-z_][A-Za-z0-9_]*)*$");
            
            // Validate vectorProperty
            if (!propPattern.IsMatch(vectorProperty))
            {
                return JsonSerializer.Serialize(new { error = "Invalid vectorProperty name. Use dot notation with letters, digits, and underscores only (e.g., 'vector' or 'embeddings')." });
            }

            // Validate selectProperties format - each property should be valid
            var properties = selectProperties.Split(',', StringSplitOptions.RemoveEmptyEntries)
                .Select(p => p.Trim())
                .ToArray();
            
            foreach (var prop in properties)
            {
                if (!propPattern.IsMatch(prop))
                {
                    return JsonSerializer.Serialize(new { error = $"Invalid property name '{prop}' in selectProperties. Use dot notation with letters, digits, and underscores only (e.g., 'id', 'title', 'metadata.author')." });
                }
            }

            var credential = new DefaultAzureCredential();

            // Generate embedding using Azure OpenAI
            float[] embedding;
            try
            {
                var openaiClient = new AzureOpenAIClient(new Uri(openaiEndpoint), credential);
                var embeddingClient = openaiClient.GetEmbeddingClient(embeddingDeployment);
                var embeddingResponse = await embeddingClient.GenerateEmbeddingAsync(searchText);
                embedding = embeddingResponse.Value.ToFloats().ToArray();
            }
            catch (Exception ex)
            {
                return JsonSerializer.Serialize(new { error = $"Failed to generate embedding: {ex.Message}" });
            }

            // Perform vector search in Cosmos DB
            using var cosmosClient = new CosmosClient(cosmosEndpoint, credential, new CosmosClientOptions
            {
                ApplicationName = "AzureCosmosDBMCP"
            });

            var container = cosmosClient.GetContainer(databaseId, containerId);

            // Build SELECT clause by prepending "c." to each property
            var selectClause = string.Join(", ", properties.Select(p => $"c.{p}"));

            // Build vector search query - prepend "c." to vectorProperty as well
            var queryText = $@"
                SELECT TOP @topN {selectClause}, VectorDistance(c.{vectorProperty}, @embedding) as _score
                FROM c
                ORDER BY VectorDistance(c.{vectorProperty}, @embedding)";

            var queryDefinition = new QueryDefinition(queryText)
                .WithParameter("@topN", topN)
                .WithParameter("@embedding", embedding);

            var iterator = container.GetItemQueryIterator<dynamic>(
                queryDefinition,
                requestOptions: new QueryRequestOptions { MaxItemCount = topN }
            );

            var results = new List<string>();
            while (iterator.HasMoreResults && results.Count < topN)
            {
                var page = await iterator.ReadNextAsync();
                foreach (var doc in page)
                {
                    results.Add(doc?.ToString() ?? "{}");
                    if (results.Count >= topN) break;
                }
            }

            var jsonArray = "[" + string.Join(",", results) + "]";
            return jsonArray;
        }
        catch (CosmosException cex)
        {
            return JsonSerializer.Serialize(new { error = cex.Message, statusCode = (int)cex.StatusCode });
        }
        catch (Exception ex)
        {
            return JsonSerializer.Serialize(new { error = ex.Message });
        }
    }
}
