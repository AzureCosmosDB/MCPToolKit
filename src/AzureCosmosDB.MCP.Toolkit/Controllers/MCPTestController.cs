using Microsoft.AspNetCore.Mvc;
using System.Text.Json;
using AzureCosmosDB.MCP.Toolkit.Services;

namespace AzureCosmosDB.MCP.Toolkit.Controllers;

[ApiController]
[Route("api/mcp")]
public class MCPTestController : ControllerBase
{
    private readonly CosmosDbToolsService _cosmosDbTools;
    private readonly ILogger<MCPTestController> _logger;

    public MCPTestController(CosmosDbToolsService cosmosDbTools, ILogger<MCPTestController> logger)
    {
        _cosmosDbTools = cosmosDbTools;
        _logger = logger;
    }

    [HttpPost("tools/{toolName}")]
    public async Task<IActionResult> CallTool(string toolName, [FromBody] MCPToolRequest request)
    {
        try
        {
            _logger.LogInformation("Received MCP tool call: {ToolName} with parameters: {Parameters}", 
                toolName, JsonSerializer.Serialize(request.Parameters));

            object? result = toolName.ToLowerInvariant() switch
            {
                "list_databases" => await _cosmosDbTools.ListDatabases(),
                "list_collections" => await CallListCollections(request.Parameters),
                "get_recent_documents" => await CallGetRecentDocuments(request.Parameters),
                "find_document_by_id" => await CallFindDocumentById(request.Parameters),
                "text_search" => await CallTextSearch(request.Parameters),
                "vector_search" => await CallVectorSearch(request.Parameters),
                "get_approximate_schema" => await CallGetApproximateSchema(request.Parameters),
                _ => throw new ArgumentException($"Unknown tool: {toolName}")
            };

            return Ok(new MCPToolResponse
            {
                Success = true,
                Result = result,
                ToolName = toolName,
                Parameters = request.Parameters,
                Timestamp = DateTime.UtcNow
            });
        }
        catch (Exception ex)
        {
            _logger.LogError(ex, "Error executing MCP tool: {ToolName}", toolName);
            return BadRequest(new MCPToolResponse
            {
                Success = false,
                Error = ex.Message,
                ToolName = toolName,
                Parameters = request.Parameters,
                Timestamp = DateTime.UtcNow
            });
        }
    }

    [HttpGet("tools")]
    public IActionResult ListTools()
    {
        var tools = new[]
        {
            new { name = "list_databases", description = "Lists all databases available in the Cosmos DB account" },
            new { name = "list_collections", description = "Lists containers (collections) for a specified database" },
            new { name = "get_recent_documents", description = "Gets the most recent N documents ordered by timestamp (_ts DESC). N must be between 1-20" },
            new { name = "find_document_by_id", description = "Finds a document by its ID in the specified database/container" },
            new { name = "text_search", description = "Select TOP N documents where a given property contains the provided search string. N must be between 1-20" },
            new { name = "vector_search", description = "Performs vector search on Cosmos DB using Azure OpenAI embeddings" },
            new { name = "get_approximate_schema", description = "Approximates a container schema by sampling up to 10 documents" }
        };

        return Ok(new { tools, count = tools.Length, timestamp = DateTime.UtcNow });
    }

    private async Task<object> CallListCollections(Dictionary<string, object> parameters)
    {
        var databaseId = GetRequiredParameter<string>(parameters, "databaseId");
        return await _cosmosDbTools.ListCollections(databaseId);
    }

    private async Task<object> CallGetRecentDocuments(Dictionary<string, object> parameters)
    {
        var databaseId = GetRequiredParameter<string>(parameters, "databaseId");
        var containerId = GetRequiredParameter<string>(parameters, "containerId");
        var n = GetRequiredParameter<int>(parameters, "n");
        return await _cosmosDbTools.GetRecentDocuments(databaseId, containerId, n);
    }

    private async Task<object> CallFindDocumentById(Dictionary<string, object> parameters)
    {
        var databaseId = GetRequiredParameter<string>(parameters, "databaseId");
        var containerId = GetRequiredParameter<string>(parameters, "containerId");
        var id = GetRequiredParameter<string>(parameters, "id");
        return await _cosmosDbTools.FindDocumentByID(databaseId, containerId, id);
    }

    private async Task<object> CallTextSearch(Dictionary<string, object> parameters)
    {
        var databaseId = GetRequiredParameter<string>(parameters, "databaseId");
        var containerId = GetRequiredParameter<string>(parameters, "containerId");
        var property = GetRequiredParameter<string>(parameters, "property");
        var searchPhrase = GetRequiredParameter<string>(parameters, "searchPhrase");
        var n = GetRequiredParameter<int>(parameters, "n");
        return await _cosmosDbTools.TextSearch(databaseId, containerId, property, searchPhrase, n);
    }

    private async Task<object> CallVectorSearch(Dictionary<string, object> parameters)
    {
        var databaseId = GetRequiredParameter<string>(parameters, "databaseId");
        var containerId = GetRequiredParameter<string>(parameters, "containerId");
        var searchText = GetRequiredParameter<string>(parameters, "searchText");
        var vectorProperty = GetRequiredParameter<string>(parameters, "vectorProperty");
        var selectProperties = GetRequiredParameter<string>(parameters, "selectProperties");
        var topN = GetRequiredParameter<int>(parameters, "topN");
        return await _cosmosDbTools.VectorSearch(databaseId, containerId, searchText, vectorProperty, selectProperties, topN);
    }

    private async Task<object> CallGetApproximateSchema(Dictionary<string, object> parameters)
    {
        var databaseId = GetRequiredParameter<string>(parameters, "databaseId");
        var containerId = GetRequiredParameter<string>(parameters, "containerId");
        return await _cosmosDbTools.GetApproximateSchema(databaseId, containerId);
    }

    private T GetRequiredParameter<T>(Dictionary<string, object> parameters, string paramName)
    {
        if (!parameters.TryGetValue(paramName, out var value))
            throw new ArgumentException($"Missing required parameter: {paramName}");

        if (value is JsonElement jsonElement)
        {
            return typeof(T) switch
            {
                Type t when t == typeof(string) => (T)(object)jsonElement.GetString()!,
                Type t when t == typeof(int) => (T)(object)jsonElement.GetInt32(),
                Type t when t == typeof(double) => (T)(object)jsonElement.GetDouble(),
                Type t when t == typeof(bool) => (T)(object)jsonElement.GetBoolean(),
                _ => throw new ArgumentException($"Unsupported parameter type: {typeof(T)}")
            };
        }

        try
        {
            return (T)Convert.ChangeType(value, typeof(T));
        }
        catch (Exception ex)
        {
            throw new ArgumentException($"Invalid parameter type for {paramName}. Expected {typeof(T).Name}, got {value?.GetType().Name}", ex);
        }
    }
}

public class MCPToolRequest
{
    public string Tool { get; set; } = string.Empty;
    public Dictionary<string, object> Parameters { get; set; } = new();
    public DateTime Timestamp { get; set; }
}

public class MCPToolResponse
{
    public bool Success { get; set; }
    public object? Result { get; set; }
    public string? Error { get; set; }
    public string ToolName { get; set; } = string.Empty;
    public Dictionary<string, object> Parameters { get; set; } = new();
    public DateTime Timestamp { get; set; }
}