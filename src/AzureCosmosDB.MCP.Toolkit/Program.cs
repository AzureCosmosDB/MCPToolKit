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
                ValidateIssuer = true,
                ValidIssuer = $"https://login.microsoftonline.com/{tenantId}/v2.0",

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
                    var environment = context.HttpContext.RequestServices.GetRequiredService<IWebHostEnvironment>();
                    
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
                    
                    // Only log headers in development mode
                    if (environment.IsDevelopment())
                    {
                        var hasAuth = context.Request.Headers.ContainsKey("Authorization");
                        var hasCustom = context.Request.Headers.ContainsKey("X-MS-TOKEN-AAD-ACCESS-TOKEN");
                        logger.LogDebug("Message received. Has Authorization header: {HasAuth}, Has X-MS-TOKEN-AAD-ACCESS-TOKEN: {HasCustom}", hasAuth, hasCustom);
                    }
                    
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

// Register singleton CosmosClient for better performance and connection pooling
builder.Services.AddSingleton<CosmosClient>(sp =>
{
    var configuration = sp.GetRequiredService<IConfiguration>();
    var logger = sp.GetRequiredService<ILogger<Program>>();
    
    var endpoint = configuration["COSMOS_ENDPOINT"] ?? Environment.GetEnvironmentVariable("COSMOS_ENDPOINT");
    
    if (string.IsNullOrWhiteSpace(endpoint))
    {
        logger.LogError("COSMOS_ENDPOINT is not configured. CosmosClient cannot be initialized.");
        throw new InvalidOperationException("COSMOS_ENDPOINT environment variable is required.");
    }
    
    logger.LogInformation("Initializing singleton CosmosClient with endpoint: {Endpoint}", endpoint);
    
    var credential = new DefaultAzureCredential();
    return new CosmosClient(endpoint, credential, new CosmosClientOptions
    {
        ApplicationName = "azurecosmosdb-mcp-kit",
        ConnectionMode = ConnectionMode.Direct, // Better performance than Gateway mode
        MaxRetryAttemptsOnRateLimitedRequests = 3,
        MaxRetryWaitTimeOnRateLimitedRequests = TimeSpan.FromSeconds(10),
        RequestTimeout = TimeSpan.FromSeconds(30),
        SerializerOptions = new CosmosSerializationOptions
        {
            PropertyNamingPolicy = CosmosPropertyNamingPolicy.CamelCase
        }
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

// Add early middleware to log incoming headers in DEVELOPMENT mode only (security issue in production)
app.Use(async (context, next) =>
{
    if (isDevelopment && context.Request.Path.StartsWithSegments("/mcp"))
    {
        var logger = context.RequestServices.GetRequiredService<ILogger<Program>>();
        logger.LogDebug("=== INCOMING REQUEST TO /mcp ===");
        logger.LogDebug("Method: {Method}, Path: {Path}", context.Request.Method, context.Request.Path);
        logger.LogDebug("Request headers (sensitive values redacted):");
        
        var sensitiveHeaders = new HashSet<string>(StringComparer.OrdinalIgnoreCase)
        {
            "Authorization", "X-MS-TOKEN-AAD-ACCESS-TOKEN", "X-Access-Token", "X-Auth-Token"
        };
        
        foreach (var header in context.Request.Headers)
        {
            var value = sensitiveHeaders.Contains(header.Key)
                ? "***REDACTED***"
                : header.Value.ToString();
            logger.LogDebug("  {Key}: {Value}", header.Key, value);
        }
        logger.LogDebug("=== END HEADERS ===");
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

// Add debug endpoint to check environment variables (no auth required for debugging)
app.MapGet("/debug/env", () =>
{
    var cosmosEndpoint = Environment.GetEnvironmentVariable("COSMOS_ENDPOINT");
    var openaiEndpoint = Environment.GetEnvironmentVariable("OPENAI_ENDPOINT");
    var environment = Environment.GetEnvironmentVariable("ASPNETCORE_ENVIRONMENT");
    
    return Results.Json(new
    {
        cosmosEndpoint = string.IsNullOrEmpty(cosmosEndpoint) ? "NOT SET" : "SET: " + cosmosEndpoint,
        openaiEndpoint = string.IsNullOrEmpty(openaiEndpoint) ? "NOT SET" : (openaiEndpoint.Length > 40 ? openaiEndpoint.Substring(0, 40) + "..." : openaiEndpoint),
        environment = environment ?? "NOT SET",
        allEnvVarsCount = Environment.GetEnvironmentVariables().Count,
        timestamp = DateTime.UtcNow
    });
}).AllowAnonymous();

app.Run();
