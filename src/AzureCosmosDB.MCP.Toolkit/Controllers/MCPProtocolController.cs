using Microsoft.AspNetCore.Mvc;
using Microsoft.AspNetCore.Authorization;
using System.Text.Json;
using System.Text.Json.Serialization;
using AzureCosmosDB.MCP.Toolkit.Services;

namespace AzureCosmosDB.MCP.Toolkit.Controllers;

[ApiController]
[Route("mcp")]
[AllowAnonymous] // Allow all requests, we'll handle auth manually in the controller
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
    [AllowAnonymous] // Allow all requests, we'll handle auth manually
    public async Task<IActionResult> HandleMCPRequest([FromBody] JsonElement requestJson)
    {
        // Check authentication if enabled
        if (_authService.IsAuthenticationEnabled() && User.Identity?.IsAuthenticated != true)
        {
            return Unauthorized(new MCPResponse
            {
                JsonRpc = "2.0",
                Id = requestJson.TryGetProperty("id", out var idProp) ? idProp : null,
                Error = new
                {
                    code = -32001,
                    message = "Authentication required"
                }
            });
        }

        // Parse the JSON-RPC request manually for better control
        var method = requestJson.TryGetProperty("method", out var methodProp) ? methodProp.GetString() : null;
        var id = requestJson.TryGetProperty("id", out var idProp2) ? idProp2 : (JsonElement?)null;
        var paramsObj = requestJson.TryGetProperty("params", out var paramsProp) ? paramsProp : (JsonElement?)null;

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
                    return Ok(new MCPResponse
                    {
                        JsonRpc = "2.0",
                        Id = id,
                        Result = new
                        {
                            protocolVersion = "2024-11-05",
                            capabilities = new
                            {
                                tools = new { }
                            },
                            serverInfo = new
                            {
                                name = "Azure Cosmos DB MCP Toolkit",
                                version = "1.0.0"
                            }
                        }
                    });

                case "tools/list":
                    return Ok(new MCPResponse
                    {
                        JsonRpc = "2.0",
                        Id = id,
                        Result = new
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
                    });

                case "tools/call":
                    // Check for MCP Tool Executor role before executing tools
                    if (_authService.IsAuthenticationEnabled() && !User.IsInRole("Mcp.Tool.Executor"))
                    {
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

                            var result = await ExecuteTool(toolName, toolArgs);
                        
                            return Ok(new MCPResponse
                            {
                                JsonRpc = "2.0",
                                Id = id,
                                Result = new
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
                            });
                        }
                    }
                    break;
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

    private async Task<object> ExecuteTool(string toolName, Dictionary<string, object> args)
    {
        return toolName.ToLowerInvariant() switch
        {
            "list_databases" => await _cosmosDbTools.ListDatabases(),
            "list_collections" => await _cosmosDbTools.ListCollections(GetStringArg(args, "databaseId")),
            "get_recent_documents" => await _cosmosDbTools.GetRecentDocuments(
                GetStringArg(args, "databaseId"),
                GetStringArg(args, "containerId"),
                GetIntArg(args, "n", 5)),
            "text_search" => await _cosmosDbTools.TextSearch(
                GetStringArg(args, "databaseId"),
                GetStringArg(args, "containerId"),
                GetStringArg(args, "property"),
                GetStringArg(args, "searchPhrase"),
                GetIntArg(args, "n", 10)),
            "find_document_by_id" => await _cosmosDbTools.FindDocumentByID(
                GetStringArg(args, "databaseId"),
                GetStringArg(args, "containerId"),
                GetStringArg(args, "id")),
            "get_approximate_schema" => await _cosmosDbTools.GetApproximateSchema(
                GetStringArg(args, "databaseId"),
                GetStringArg(args, "containerId")),
            "vector_search" => await _cosmosDbTools.VectorSearch(
                GetStringArg(args, "databaseId"),
                GetStringArg(args, "containerId"),
                GetStringArg(args, "searchText"),
                GetStringArg(args, "vectorProperty"),
                GetStringArg(args, "selectProperties"),
                GetIntArg(args, "topN", 10)),
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