using System.Net;
using System.Net.Http.Json;
using System.Text.Json;
using FluentAssertions;
using Microsoft.AspNetCore.Hosting;
using Microsoft.AspNetCore.Mvc.Testing;
using Xunit;

namespace AzureCosmosDB.MCP.Toolkit.Tests;

// The toolkit reads its sign-in settings from process-wide environment variables, so these tests must not run alongside others.
[CollectionDefinition(nameof(McpSignInMetadataTests), DisableParallelization = true)]
public class McpSignInMetadataCollection { }

/// <summary>
/// Checks the /mcp 401 response and the sign-in metadata page with Entra sign-in on, with and without
/// AzureAd:McpResourceUrl. With it set, MCP clients such as VS Code can discover how to sign in.
/// </summary>
[Collection(nameof(McpSignInMetadataTests))]
public class McpSignInMetadataTests
{
    private const string TenantId = "11111111-1111-1111-1111-111111111111";
    private const string ClientId = "22222222-2222-2222-2222-222222222222";
    private const string ResourceUrl = "https://toolkit.example.com/mcp";

    [Fact]
    public async Task Unauthorized_Mcp_Request_Points_To_Sign_In_Metadata_When_Resource_Url_Is_Set()
    {
        using var factory = new SignInApplicationFactory(ResourceUrl);
        var client = factory.CreateClient();

        var response = await PostToolsListAsync(client);

        response.StatusCode.Should().Be(HttpStatusCode.Unauthorized);
        response.Headers.WwwAuthenticate.ToString().Should()
            .Contain("resource_metadata=\"http://localhost/.well-known/oauth-protected-resource/mcp\"");

        var metadata = await client.GetAsync("/.well-known/oauth-protected-resource/mcp");
        metadata.StatusCode.Should().Be(HttpStatusCode.OK);
        using var document = JsonDocument.Parse(await metadata.Content.ReadAsStringAsync());
        document.RootElement.GetProperty("resource").GetString().Should().Be(ResourceUrl);
        document.RootElement.GetProperty("authorization_servers")[0].GetString().Should()
            .Be($"https://login.microsoftonline.com/{TenantId}/v2.0");
        document.RootElement.GetProperty("scopes_supported")[0].GetString().Should()
            .Be($"api://{ClientId}/access_as_user");
    }

    [Fact]
    public async Task Unauthorized_Mcp_Request_Is_Unchanged_When_Resource_Url_Is_Not_Set()
    {
        using var factory = new SignInApplicationFactory(resourceUrl: null);
        var client = factory.CreateClient();

        var response = await PostToolsListAsync(client);

        response.StatusCode.Should().Be(HttpStatusCode.Unauthorized);
        response.Headers.WwwAuthenticate.ToString().Should().Be("Bearer");
        (await client.GetAsync("/.well-known/oauth-protected-resource/mcp")).StatusCode.Should().Be(HttpStatusCode.NotFound);
    }

    private static Task<HttpResponseMessage> PostToolsListAsync(HttpClient client)
    {
        client.DefaultRequestHeaders.Accept.ParseAdd("application/json");
        client.DefaultRequestHeaders.Accept.ParseAdd("text/event-stream");
        return client.PostAsJsonAsync("/mcp", new { jsonrpc = "2.0", id = 1, method = "tools/list" });
    }

    private sealed class SignInApplicationFactory : WebApplicationFactory<Program>
    {
        private static readonly string[] VariableNames =
        [
            "DEV_BYPASS_AUTH", "COSMOS_ENDPOINT", "AzureAd__TenantId", "AzureAd__ClientId", "AzureAd__McpResourceUrl",
        ];

        private readonly Dictionary<string, string?> _previousValues =
            VariableNames.ToDictionary(name => name, Environment.GetEnvironmentVariable);

        private readonly string? _resourceUrl;

        public SignInApplicationFactory(string? resourceUrl) => _resourceUrl = resourceUrl;

        protected override void ConfigureWebHost(IWebHostBuilder builder)
        {
            Environment.SetEnvironmentVariable("DEV_BYPASS_AUTH", "false");
            Environment.SetEnvironmentVariable("COSMOS_ENDPOINT", "https://localhost:8081");
            Environment.SetEnvironmentVariable("AzureAd__TenantId", TenantId);
            Environment.SetEnvironmentVariable("AzureAd__ClientId", ClientId);
            Environment.SetEnvironmentVariable("AzureAd__McpResourceUrl", _resourceUrl);

            builder.UseEnvironment("Production");
        }

        protected override void Dispose(bool disposing)
        {
            base.Dispose(disposing);
            foreach (var (name, value) in _previousValues)
            {
                Environment.SetEnvironmentVariable(name, value);
            }
        }
    }
}
