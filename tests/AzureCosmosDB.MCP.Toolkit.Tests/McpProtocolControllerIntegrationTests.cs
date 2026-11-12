using System.Net;
using System.Net.Http.Json;
using System.Text.Json;
using FluentAssertions;
using Microsoft.AspNetCore.Mvc.Testing;
using Microsoft.AspNetCore.Hosting;
using ModelContextProtocol.Server;
using Xunit;

namespace AzureCosmosDB.MCP.Toolkit.Tests;

public class McpProtocolControllerIntegrationTests : IClassFixture<McpTestApplicationFactory>
{
    private readonly HttpClient _client;

    public McpProtocolControllerIntegrationTests(McpTestApplicationFactory factory)
    {
        _client = factory.CreateClient();
    }

    [Fact]
    public async Task ToolsCall_Should_Reject_Missing_Params()
    {
        var response = await _client.PostAsJsonAsync("/mcp", new
        {
            jsonrpc = "2.0",
            id = 1,
            method = "tools/call"
        });

        response.StatusCode.Should().Be(HttpStatusCode.BadRequest);

        using var document = JsonDocument.Parse(await response.Content.ReadAsStringAsync());
        document.RootElement.GetProperty("error").GetProperty("code").GetInt32().Should().Be(-32602);
        document.RootElement.GetProperty("error").GetProperty("message").GetString().Should().Be("Invalid params");
        document.RootElement.GetProperty("error").GetProperty("data").GetString().Should().Contain("'params' must be provided");
    }

    [Fact]
    public async Task ToolsCall_Should_Reject_Unexpected_Argument_Properties()
    {
        var response = await _client.PostAsJsonAsync("/mcp", new
        {
            jsonrpc = "2.0",
            id = 1,
            method = "tools/call",
            @params = new
            {
                name = "list_collections",
                arguments = new
                {
                    databaseId = "db1",
                    unexpected = "value"
                }
            }
        });

        response.StatusCode.Should().Be(HttpStatusCode.BadRequest);

        using var document = JsonDocument.Parse(await response.Content.ReadAsStringAsync());
        document.RootElement.GetProperty("error").GetProperty("code").GetInt32().Should().Be(-32602);
        document.RootElement.GetProperty("error").GetProperty("data").GetString().Should().Contain("Unknown property 'unexpected'");
    }

    [Fact]
    public async Task ToolsCall_Should_Reject_Wrong_Argument_Types()
    {
        var response = await _client.PostAsJsonAsync("/mcp", new
        {
            jsonrpc = "2.0",
            id = 1,
            method = "tools/call",
            @params = new
            {
                name = "get_recent_documents",
                arguments = new
                {
                    databaseId = "db1",
                    containerId = "c1",
                    n = "5"
                }
            }
        });

        response.StatusCode.Should().Be(HttpStatusCode.BadRequest);

        using var document = JsonDocument.Parse(await response.Content.ReadAsStringAsync());
        document.RootElement.GetProperty("error").GetProperty("code").GetInt32().Should().Be(-32602);
        document.RootElement.GetProperty("error").GetProperty("data").GetString().Should().Contain("'n' must be an integer");
    }

    [Fact]
    public async Task ToolsList_Should_Advertise_Closed_Schemas()
    {
        var response = await _client.PostAsJsonAsync("/mcp", new
        {
            jsonrpc = "2.0",
            id = 1,
            method = "tools/list"
        });

        response.StatusCode.Should().Be(HttpStatusCode.OK);

        using var document = JsonDocument.Parse(await response.Content.ReadAsStringAsync());
        var tools = document.RootElement.GetProperty("result").GetProperty("tools").EnumerateArray().ToList();
        tools.Should().NotBeEmpty();
        tools.Should().OnlyContain(tool => tool.GetProperty("inputSchema").GetProperty("additionalProperties").GetBoolean() == false);
    }

    [Fact]
    public async Task QueryDocuments_Should_Reject_Multiple_Statements()
    {
        var result = await CosmosDbTools.QueryDocuments("db1", "container1", "SELECT * FROM c; DELETE FROM c");

        using var document = JsonDocument.Parse(result);
        document.RootElement.GetProperty("error").GetString().Should().Be("Only a single SELECT query is allowed.");
    }

    [Fact]
    public void QueryDocuments_Should_Be_Registered_As_ReadOnlyMcpTool()
    {
        var toolAttribute = typeof(CosmosDbTools)
            .GetMethod(nameof(CosmosDbTools.QueryDocuments))!
            .GetCustomAttributes(typeof(McpServerToolAttribute), inherit: false)
            .Cast<McpServerToolAttribute>()
            .Single();

        toolAttribute.Name.Should().Be("query_documents");
        toolAttribute.ReadOnly.Should().BeTrue();
    }
}

public sealed class McpTestApplicationFactory : WebApplicationFactory<Program>
{
    protected override void ConfigureWebHost(IWebHostBuilder builder)
    {
        Environment.SetEnvironmentVariable("DEV_BYPASS_AUTH", "true");
        Environment.SetEnvironmentVariable("COSMOS_ENDPOINT", "https://localhost:8081");

        builder.UseEnvironment("Development");
    }
}