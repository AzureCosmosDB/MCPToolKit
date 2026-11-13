using System.Net;
using System.Net.Http.Json;
using FluentAssertions;
using Xunit;

namespace AzureCosmosDB.MCP.Toolkit.Tests;

public class McpStatelessTransportTests
{
    /// <summary>
    /// Checks that a client can initialize on one app instance and call tools on another, as when
    /// replicas sit behind a load balancer. Two in-memory test servers stand in for the two replicas.
    /// </summary>
    [Fact]
    public async Task ToolsList_Should_Succeed_On_A_Different_Instance_Than_Initialize()
    {
        using var first = new McpTestApplicationFactory();
        using var second = new McpTestApplicationFactory();
        var firstClient = CreateMcpClient(first);
        var secondClient = CreateMcpClient(second);

        var initialize = await firstClient.PostAsJsonAsync("/mcp", new
        {
            jsonrpc = "2.0",
            id = 1,
            method = "initialize",
            @params = new
            {
                protocolVersion = "2025-06-18",
                capabilities = new { },
                clientInfo = new { name = "test", version = "1.0" }
            }
        });

        initialize.StatusCode.Should().Be(HttpStatusCode.OK);
        if (initialize.Headers.TryGetValues("Mcp-Session-Id", out var sessionIds))
        {
            secondClient.DefaultRequestHeaders.Add("Mcp-Session-Id", sessionIds.Single());
        }

        var toolsList = await secondClient.PostAsJsonAsync("/mcp", new
        {
            jsonrpc = "2.0",
            id = 2,
            method = "tools/list"
        });

        toolsList.StatusCode.Should().Be(HttpStatusCode.OK);
        (await toolsList.Content.ReadAsStringAsync()).Should().Contain("list_collections");
    }

    private static HttpClient CreateMcpClient(McpTestApplicationFactory factory)
    {
        var client = factory.CreateClient();
        // The MCP SDK rejects requests that don't accept both JSON and event-stream responses.
        client.DefaultRequestHeaders.Accept.ParseAdd("application/json");
        client.DefaultRequestHeaders.Accept.ParseAdd("text/event-stream");
        return client;
    }
}
