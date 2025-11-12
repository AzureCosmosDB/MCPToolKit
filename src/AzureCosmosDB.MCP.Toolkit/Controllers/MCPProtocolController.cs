using Microsoft.AspNetCore.Mvc;
using Microsoft.AspNetCore.Authorization;
using System.Text.Json;
using System.Text.Json.Serialization;
using AzureCosmosDB.MCP.Toolkit.Services;

namespace AzureCosmosDB.MCP.Toolkit.Controllers;

[ApiController]
[Route("mcp")]
public class MCPProtocolController : ControllerBase
{
    private readonly CosmosDbToolsService _cosmosDbTools;
    private readonly AuthenticationService _authService;
    private readonly ILogger<MCPProtocolController> _logger;

    public MCPProtocolController(
        CosmosDbToolsService cosmosDbTools, 
        AuthenticationService authService,
        ILogger<MCPProtocolController> logger)
    {
        _cosmosDbTools = cosmosDbTools;
        _authService = authService;
        _logger = logger;
    }

    [HttpOptions]
    [AllowAnonymous] // Allow OPTIONS requests without authentication for CORS preflight
    public IActionResult HandleMCPOptions()
    {
        Response.Headers["Access-Control-Allow-Origin"] = "*";
        Response.Headers["Access-Control-Allow-Methods"] = "POST, OPTIONS";
        Response.Headers["Access-Control-Allow-Headers"] = "Content-Type, Authorization";
        return Ok();
    }

    [HttpPost]
    [AllowAnonymous] // Allow request through, we'll validate manually
    public async Task<IActionResult> HandleMCPRequest([FromBody] JsonElement requestJson)
    {
        // Parse request info for logging
        var method = requestJson.TryGetProperty("method", out var methodProp) ? methodProp.GetString() : null;
        var id = requestJson.TryGetProperty("id", out var idProp2) ? idProp2 : (JsonElement?)null;
        var paramsObj = requestJson.TryGetProperty("params", out var paramsProp) ? paramsProp : (JsonElement?)null;
        
        // Log authentication details for debugging
        _logger.LogInformation("Request from user: {User}, Authenticated: {IsAuth}, Identity: {Identity}", 
            User?.Identity?.Name ?? "Anonymous", 
            User?.Identity?.IsAuthenticated ?? false,
            User?.Identity?.AuthenticationType ?? "None");

        // Manual authentication check - for tools/call only (allow initialize and tools/list without auth for discovery)
        var requiresAuth = method?.ToLowerInvariant() == "tools/call";
        if (requiresAuth && _authService.IsAuthenticationEnabled())
        {
            // Try to manually validate token from header (in case it wasn't stripped)
            var authHeader = Request.Headers["Authorization"].FirstOrDefault() 
                ?? Request.Headers["X-MS-TOKEN-AAD-ACCESS-TOKEN"].FirstOrDefault();
            
            if (string.IsNullOrEmpty(authHeader))
            {
                _logger.LogWarning("Authentication required but no token provided");
                return Unauthorized(new MCPResponse
                {
                    JsonRpc = "2.0",
                    Id = id,
                    Error = new
                    {
                        code = -32001,
                        message = "Authentication required. Please provide a valid bearer token."
                    }
                });
            }

            // If we have a token but user is not authenticated, the token validation failed
            if (User?.Identity?.IsAuthenticated != true)
            {
                _logger.LogWarning("Token provided but authentication failed");
                
                // Log all user claims for debugging
                if (User != null)
                {
                    _logger.LogWarning("User claims: {Claims}", string.Join(", ", User.Claims.Select(c => $"{c.Type}={c.Value}")));
                }
                
                return Unauthorized(new MCPResponse
                {
                    JsonRpc = "2.0",
                    Id = id,
                    Error = new
                    {
                        code = -32002,
                        message = "Invalid or expired token"
                    }
                });
            }
        }

        try
        {
            // Log authentication information
            _logger.LogInformation("Received MCP request: {Method} with ID: {Id} from {UserInfo}", 
                method, id, _authService.GetUserIdentityInfo());
            _logger.LogInformation("Full request body: {RequestBody}", requestJson.GetRawText());

            // Set proper headers for streaming response and CORS
            Response.Headers["Cache-Control"] = "no-cache";
            Response.Headers["Connection"] = "keep-alive";
            Response.Headers["Access-Control-Allow-Origin"] = "*";
            Response.Headers["Access-Control-Allow-Methods"] = "POST, OPTIONS";
            Response.Headers["Access-Control-Allow-Headers"] = "Content-Type, Authorization";

            switch (method?.ToLowerInvariant())
            {
                case "initialize":
                    var initResponse = new
                    {
                        jsonrpc = "2.0",
                        id = id,
                        result = new
                        {
                            protocolVersion = "2024-11-05",
                            capabilities = new
                            {
                                tools = new { }
                            },
                            serverInfo = new
                            {
                                name = "azure-cosmosdb-mcp-toolkit",
                                version = "1.0.0"
                            }
                        }
                    };
                    _logger.LogInformation("Returning initialize response: {Response}", JsonSerializer.Serialize(initResponse));
                    Response.ContentType = "application/json";
                    return new JsonResult(initResponse);

                case "tools/list":
                    var toolsResponse = new
                    {
                        jsonrpc = "2.0",
                        id = id,
                        result = new
                        {
                            tools = new object[]
                            {
                                new { 
                                    name = "list_databases", 
                                    description = "Lists databases available in the Cosmos DB account.",
                                    inputSchema = new {
                                        type = "object",
                                        properties = new { },
                                        required = new string[] { }
                                    }
                                },
                                new { 
                                    name = "list_collections", 
                                    description = "Lists containers (collections) for the specified database.",
                                    inputSchema = new {
                                        type = "object",
                                        properties = new {
                                            databaseId = new { type = "string", description = "Database id to list containers from" }
                                        },
                                        required = new string[] { "databaseId" }
                                    }
                                },
                                new { 
                                    name = "get_recent_documents", 
                                    description = "Gets the most recent N documents ordered by timestamp (_ts DESC) from the specified database/container.",
                                    inputSchema = new {
                                        type = "object",
                                        properties = new {
                                            databaseId = new { type = "string", description = "Database id containing the container" },
                                            containerId = new { type = "string", description = "Container id to query" },
                                            n = new { type = "integer", description = "Number of documents to return (1-20)" }
                                        },
                                        required = new string[] { "databaseId", "containerId", "n" }
                                    }
                                },
                                new { 
                                    name = "text_search", 
                                    description = "Select TOP N documents where a given property contains the provided search string.",
                                    inputSchema = new {
                                        type = "object",
                                        properties = new {
                                            databaseId = new { type = "string", description = "Database id containing the container" },
                                            containerId = new { type = "string", description = "Container id to query" },
                                            property = new { type = "string", description = "Document property to search" },
                                            searchPhrase = new { type = "string", description = "Search term to look for" },
                                            n = new { type = "integer", description = "Number of documents to return (1-20)" }
                                        },
                                        required = new string[] { "databaseId", "containerId", "property", "searchPhrase", "n" }
                                    }
                                },
                                new { 
                                    name = "find_document_by_id", 
                                    description = "Find a document by its id in the specified database/container.",
                                    inputSchema = new {
                                        type = "object",
                                        properties = new {
                                            databaseId = new { type = "string", description = "Database id containing the container" },
                                            containerId = new { type = "string", description = "Container id to query" },
                                            id = new { type = "string", description = "The id of the document to find" }
                                        },
                                        required = new string[] { "databaseId", "containerId", "id" }
                                    }
                                },
                                new { 
                                    name = "get_approximate_schema", 
                                    description = "Approximates a container schema by sampling up to 10 documents.",
                                    inputSchema = new {
                                        type = "object",
                                        properties = new {
                                            databaseId = new { type = "string", description = "Database id containing the container" },
                                            containerId = new { type = "string", description = "Container id to inspect" }
                                        },
                                        required = new string[] { "databaseId", "containerId" }
                                    }
                                },
                                new { 
                                    name = "vector_search", 
                                    description = "Performs vector search on Cosmos DB using Azure OpenAI embeddings.",
                                    inputSchema = new {
                                        type = "object",
                                        properties = new {
                                            databaseId = new { type = "string", description = "Database id containing the container" },
                                            containerId = new { type = "string", description = "Container id to query" },
                                            searchText = new { type = "string", description = "Text to search for semantically similar content" },
                                            vectorProperty = new { type = "string", description = "Property name where vector embeddings are stored" },
                                            selectProperties = new { type = "string", description = "Comma-separated list of specific properties to project in results" },
                                            topN = new { type = "integer", description = "Number of documents to return (1-50)" }
                                        },
                                        required = new string[] { "databaseId", "containerId", "searchText", "vectorProperty", "selectProperties", "topN" }
                                    }
                                }
                            }
                        }
                    };
                    _logger.LogInformation("Returning tools/list response with {ToolCount} tools", ((object[])toolsResponse.result.tools).Length);
                    Response.ContentType = "application/json";
                    return new JsonResult(toolsResponse);

                case "tools/call":
                    // Check for MCP Tool Executor role before executing tools
                    _logger.LogInformation("tools/call request - Auth enabled: {AuthEnabled}, User authenticated: {IsAuth}", 
                        _authService.IsAuthenticationEnabled(), 
                        User?.Identity?.IsAuthenticated ?? false);
                    
                    if (User != null)
                    {
                        _logger.LogInformation("User claims: {Claims}", 
                            string.Join(", ", User.Claims.Select(c => $"{c.Type}={c.Value}")));
                        _logger.LogInformation("Checking role 'Mcp.Tool.Executor': {HasRole}", 
                            User.IsInRole("Mcp.Tool.Executor"));
                    }
                    
                    if (_authService.IsAuthenticationEnabled() && User?.Identity?.IsAuthenticated == true && !User.IsInRole("Mcp.Tool.Executor"))
                    {
                        _logger.LogWarning("User does not have Mcp.Tool.Executor role. User roles: {Roles}", 
                            string.Join(", ", User.Claims.Where(c => c.Type == "roles" || c.Type.EndsWith("/role")).Select(c => c.Value)));
                        return Forbid("Insufficient permissions. The 'Mcp.Tool.Executor' role is required to execute tools.");
                    }

                    if (paramsObj.HasValue && paramsObj.Value.TryGetProperty("name", out var toolNameProp))
                    {
                        var toolName = toolNameProp.GetString();
                        if (toolName != null)
                        {
                            var toolArgs = new Dictionary<string, object>();
                            
                            if (paramsObj.Value.TryGetProperty("arguments", out var argsProp))
                            {
                                foreach (var prop in argsProp.EnumerateObject())
                                {
                                    object value = prop.Value.ValueKind switch
                                    {
                                        JsonValueKind.String => prop.Value.GetString() ?? "",
                                        JsonValueKind.Number => prop.Value.GetInt32(),
                                        _ => prop.Value.ToString()
                                    };
                                    toolArgs[prop.Name] = value;
                                }
                            }

                            var result = await ExecuteTool(toolName, toolArgs, HttpContext.RequestAborted);
                        
                            var toolResponse = new
                            {
                                jsonrpc = "2.0",
                                id = id,
                                result = new
                                {
                                    content = new[]
                                    {
                                        new
                                        {
                                            type = "text",
                                            text = JsonSerializer.Serialize(result)
                                        }
                                    }
                                }
                            };
                            _logger.LogInformation("Returning tools/call response for tool: {ToolName}", toolName);
                            Response.ContentType = "application/json";
                            return new JsonResult(toolResponse);
                        }
                    }
                    break;
                    
                case "notifications/initialized":
                    // Client notification that it has successfully initialized
                    // No response required for notifications
                    _logger.LogInformation("Client initialized notification received");
                    return Ok();
                    
                case var n when n?.StartsWith("notifications/") == true:
                    // Other notifications - just acknowledge and continue
                    _logger.LogInformation("Notification received: {Method}", method);
                    return Ok();
            }

            return BadRequest(new MCPResponse
            {
                JsonRpc = "2.0",
                Id = id,
                Error = new
                {
                    code = -32601,
                    message = "Method not found",
                    data = method
                }
            });
        }
        catch (Exception ex)
        {
            _logger.LogError(ex, "Error handling MCP request");
            return StatusCode(500, new MCPResponse
            {
                JsonRpc = "2.0",
                Id = id,
                Error = new
                {
                    code = -32603,
                    message = "Internal error",
                    data = ex.Message
                }
            });
        }
    }

    private async Task<object> ExecuteTool(string toolName, Dictionary<string, object> args, CancellationToken cancellationToken = default)
    {
        return toolName.ToLowerInvariant() switch
        {
            "list_databases" => await _cosmosDbTools.ListDatabases(cancellationToken),
            "list_collections" => await _cosmosDbTools.ListCollections(GetStringArg(args, "databaseId"), cancellationToken),
            "get_recent_documents" => await _cosmosDbTools.GetRecentDocuments(
                GetStringArg(args, "databaseId"),
                GetStringArg(args, "containerId"),
                GetRequiredIntArg(args, "n"),
                cancellationToken),
            "text_search" => await _cosmosDbTools.TextSearch(
                GetStringArg(args, "databaseId"),
                GetStringArg(args, "containerId"),
                GetStringArg(args, "property"),
                GetStringArg(args, "searchPhrase"),
                GetRequiredIntArg(args, "n"),
                cancellationToken),
            "find_document_by_id" => await _cosmosDbTools.FindDocumentByID(
                GetStringArg(args, "databaseId"),
                GetStringArg(args, "containerId"),
                GetStringArg(args, "id"),
                cancellationToken),
            "get_approximate_schema" => await _cosmosDbTools.GetApproximateSchema(
                GetStringArg(args, "databaseId"),
                GetStringArg(args, "containerId"),
                cancellationToken),
            "vector_search" => await _cosmosDbTools.VectorSearch(
                GetStringArg(args, "databaseId"),
                GetStringArg(args, "containerId"),
                GetStringArg(args, "searchText"),
                GetStringArg(args, "vectorProperty"),
                GetStringArg(args, "selectProperties"),
                GetRequiredIntArg(args, "topN"),
                cancellationToken),
            _ => throw new ArgumentException($"Unknown tool: {toolName}")
        };
    }

    private static string GetStringArg(Dictionary<string, object> args, string key)
    {
        return args.TryGetValue(key, out var value) ? value?.ToString() ?? "" : "";
    }

    private static int GetIntArg(Dictionary<string, object> args, string key, int defaultValue = 0)
    {
        if (args.TryGetValue(key, out var value))
        {
            if (value is JsonElement element && element.TryGetInt32(out var intValue))
                return intValue;
            if (int.TryParse(value?.ToString(), out var parsedValue))
                return parsedValue;
        }
        return defaultValue;
    }

    private static int GetRequiredIntArg(Dictionary<string, object> args, string key)
    {
        if (!args.TryGetValue(key, out var value))
        {
            throw new ArgumentException($"Required parameter '{key}' is missing");
        }

        if (value is JsonElement element && element.TryGetInt32(out var intValue))
            return intValue;
        if (int.TryParse(value?.ToString(), out var parsedValue))
            return parsedValue;

        throw new ArgumentException($"Parameter '{key}' must be a valid integer");
    }
    
    [HttpGet("debug")]
    [AllowAnonymous]
    public IActionResult DebugHeaders()
    {
        var headers = new Dictionary<string, string>();
        foreach (var header in Request.Headers)
        {
            headers[header.Key] = header.Value.ToString();
        }
        
        var query = new Dictionary<string, string>();
        foreach (var q in Request.Query)
        {
            query[q.Key] = q.Value.ToString();
        }
        
        return Ok(new {
            headers = headers,
            query = query,
            user = User?.Identity?.Name,
            authenticated = User?.Identity?.IsAuthenticated,
            roles = User?.Claims.Where(c => c.Type == "roles" || c.Type == "http://schemas.microsoft.com/ws/2008/06/identity/claims/role").Select(c => c.Value).ToList()
        });
    }
}

public class MCPRequest
{
    public string? JsonRpc { get; set; }
    public object? Id { get; set; }
    public string? Method { get; set; }
    public MCPParams? Params { get; set; }
}

public class MCPParams
{
    public MCPArguments? Arguments { get; set; }
}

public class MCPArguments
{
    public string? Name { get; set; }
    public Dictionary<string, object>? Arguments { get; set; }
}

public class MCPResponse
{
    [JsonPropertyName("jsonrpc")]
    public string JsonRpc { get; set; } = "2.0";
    
    [JsonPropertyName("id")]
    public object? Id { get; set; }
    
    [JsonPropertyName("result")]
    public object? Result { get; set; }
    
    [JsonPropertyName("error")]
    public object? Error { get; set; }
}