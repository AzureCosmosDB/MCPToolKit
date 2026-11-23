using System.Net;
using System.Net.Http.Json;
using System.Text.Json;
using FluentAssertions;
using Microsoft.AspNetCore.Mvc.Testing;
using Microsoft.AspNetCore.Hosting;
using Microsoft.AspNetCore.Authentication.JwtBearer;
using Microsoft.AspNetCore.TestHost;
using Microsoft.Extensions.DependencyInjection;
using Microsoft.Azure.Cosmos;
using Microsoft.IdentityModel.Protocols;
using Microsoft.IdentityModel.Protocols.OpenIdConnect;
using Microsoft.IdentityModel.Tokens;
using ModelContextProtocol.Server;
using Moq;
using System.IdentityModel.Tokens.Jwt;
using System.Security.Claims;
using System.Text;
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

    [Fact]
    public void FindDocumentByID_Should_Expose_Optional_PartitionKey_And_Cancellation()
    {
        var method = typeof(CosmosDbTools).GetMethod(nameof(CosmosDbTools.FindDocumentByID))!;
        var toolAttribute = method.GetCustomAttributes(typeof(McpServerToolAttribute), inherit: false)
            .Cast<McpServerToolAttribute>().Single();
        var partitionKey = method.GetParameters().Single(parameter => parameter.Name == "partitionKey");
        var cancellation = method.GetParameters().Single(parameter => parameter.ParameterType == typeof(CancellationToken));

        toolAttribute.ReadOnly.Should().BeTrue();
        partitionKey.ParameterType.Should().Be(typeof(string));
        partitionKey.HasDefaultValue.Should().BeTrue();
        partitionKey.DefaultValue.Should().BeNull();
        cancellation.HasDefaultValue.Should().BeTrue();
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

[CollectionDefinition("Diagnostic endpoint authentication", DisableParallelization = true)]
public sealed class DiagnosticEndpointAuthenticationCollection
{
}

[Collection("Diagnostic endpoint authentication")]
public class McpDiagnosticEndpointTests
{
    [Theory]
    [InlineData("Production", "anonymous")]
    [InlineData("Production", "invalid")]
    [InlineData("Production", "authenticated")]
    [InlineData("Development", "anonymous")]
    [InlineData("Development", "invalid")]
    [InlineData("Development", "authenticated")]
    public async Task DebugRoute_Should_NotExist_OrReflectRequestData(string environment, string authentication)
    {
        // Existing application factories change this process-wide setting.
        var previousBypass = Environment.GetEnvironmentVariable("DEV_BYPASS_AUTH");
        var bypass = environment == "Development";
        Environment.SetEnvironmentVariable("DEV_BYPASS_AUTH", bypass ? "true" : "false");
        try
        {
            const string issuer = "https://login.microsoftonline.com/11111111-1111-1111-1111-111111111111/v2.0";
            const string audience = "diagnostic-test-client";
            var key = new SymmetricSecurityKey(Encoding.UTF8.GetBytes("synthetic-test-signing-key-not-a-production-secret"));
            var tokenValidated = false;
            using var factory = new WebApplicationFactory<Program>().WithWebHostBuilder(builder =>
            {
                builder.UseEnvironment(environment);
                builder.UseSetting("DevelopmentMode:BypassAuthentication", bypass.ToString());
                builder.UseSetting("AzureAd:TenantId", "11111111-1111-1111-1111-111111111111");
                builder.UseSetting("AzureAd:ClientId", audience);
                builder.ConfigureTestServices(services =>
                {
                    services.AddSingleton(new Mock<CosmosClient>().Object);
                    services.PostConfigure<JwtBearerOptions>(JwtBearerDefaults.AuthenticationScheme, options =>
                    {
                        options.Configuration = new OpenIdConnectConfiguration { Issuer = issuer };
                        options.Configuration.SigningKeys.Add(key);
                        options.ConfigurationManager = new StaticConfigurationManager<OpenIdConnectConfiguration>(options.Configuration);
                        options.TokenValidationParameters.ValidAudiences = [audience];
                        options.Events.OnTokenValidated = _ =>
                        {
                            tokenValidated = true;
                            return Task.CompletedTask;
                        };
                    });
                });
            });
            using var client = factory.CreateClient();
            var token = new JwtSecurityTokenHandler().WriteToken(new JwtSecurityToken(
                issuer: issuer,
                audience: audience,
                claims: [new Claim(ClaimTypes.Name, "synthetic-user"), new Claim("roles", "Mcp.Tool.Executor")],
                expires: DateTime.UtcNow.AddMinutes(5),
                signingCredentials: new SigningCredentials(key, SecurityAlgorithms.HmacSha256)));
            var path = authentication == "invalid"
                ? "/mcp/http/debug?access_token=synthetic-query-token"
                : "/mcp/http/debug?probe=synthetic-query-value";
            using var request = new HttpRequestMessage(HttpMethod.Get, path);
            request.Headers.Add("Cookie", "session=synthetic-cookie-secret");
            request.Headers.Add("X-Forwarded-Host", "synthetic-internal-routing");
            request.Headers.Add("X-Container-App-Revision-Name", "synthetic-revision");
            if (authentication == "authenticated")
                request.Headers.Authorization = new System.Net.Http.Headers.AuthenticationHeaderValue("Bearer", token);
            else if (authentication == "invalid")
            {
                request.Headers.Authorization = new System.Net.Http.Headers.AuthenticationHeaderValue("Bearer", "synthetic-invalid-token");
                request.Headers.Add("X-MS-TOKEN-AAD-ACCESS-TOKEN", "synthetic-platform-token");
            }

            using var response = await client.SendAsync(request);

            response.StatusCode.Should().Be(HttpStatusCode.NotFound);
            var body = await response.Content.ReadAsStringAsync();
            foreach (var value in new[] { "synthetic-", token, "\"headers\"", "\"query\"", "\"authenticated\"", "\"roles\"" })
                body.Should().NotContain(value);
            if (!bypass && authentication == "authenticated")
                tokenValidated.Should().BeTrue();

            using var health = await client.GetAsync("/health");
            health.StatusCode.Should().Be(HttpStatusCode.OK);
            if (!bypass && authentication == "anonymous")
            {
                using var mcpResponse = await client.PostAsJsonAsync("/mcp", new { jsonrpc = "2.0", id = 1, method = "tools/list" });
                mcpResponse.StatusCode.Should().Be(HttpStatusCode.Unauthorized);
            }
        }
        finally
        {
            Environment.SetEnvironmentVariable("DEV_BYPASS_AUTH", previousBypass);
        }
    }
}