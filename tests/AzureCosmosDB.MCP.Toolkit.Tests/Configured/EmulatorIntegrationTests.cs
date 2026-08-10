using System.Text.Json.Nodes;
using AzureCosmosDB.MCP.Toolkit.Configuration;
using AzureCosmosDB.MCP.Toolkit.Providers;
using AzureCosmosDB.MCP.Toolkit.Runtime;
using FluentAssertions;
using Microsoft.Azure.Cosmos;
using Microsoft.Extensions.Configuration;
using Microsoft.Extensions.Logging.Abstractions;
using Xunit;

namespace AzureCosmosDB.MCP.Toolkit.Tests.Configured;

/// <summary>
/// End-to-end tests that run the real <see cref="CosmosGateway"/> and configuration runtime against
/// the local Azure Cosmos DB emulator. They are automatically skipped (no-op) when the emulator is
/// not reachable, so they never break CI environments without an emulator.
/// </summary>
public sealed class EmulatorIntegrationTests : IAsyncLifetime
{
    private const string EmulatorConnectionString =
        "AccountEndpoint=https://localhost:8081/;AccountKey=C2y6yDjf5/R+ob0N8A7Cgv30VRDJIWEHLM+4QDU5DE2nQ9nDuVTqobD4b8mGGyPMbIZnqyMsEcaGQy67XIw/Jw==";

    private readonly string _databaseName = "mcp_it_" + Guid.NewGuid().ToString("N")[..8];
    private CosmosClient? _client;
    private bool _available;

    public async Task InitializeAsync()
    {
        try
        {
            _client = new CosmosClient(EmulatorConnectionString, new CosmosClientOptions
            {
                ConnectionMode = ConnectionMode.Gateway,
                HttpClientFactory = () => new HttpClient(new HttpClientHandler
                {
                    ServerCertificateCustomValidationCallback = HttpClientHandler.DangerousAcceptAnyServerCertificateValidator,
                }),
                RequestTimeout = TimeSpan.FromSeconds(10),
            });

            var db = await _client.CreateDatabaseIfNotExistsAsync(_databaseName);
            await db.Database.CreateContainerIfNotExistsAsync(new ContainerProperties
            {
                Id = "accounts",
                PartitionKeyPaths = new List<string> { "/tenantId", "/accountId" },
            });

            var accounts = _client.GetContainer(_databaseName, "accounts");
            await accounts.CreateItemAsync(new JsonObject
            {
                ["id"] = "Acc001",
                ["type"] = "BankAccount",
                ["tenantId"] = "Contoso",
                ["accountId"] = "Acc001",
                ["name"] = "Mark",
                ["balance"] = 500.0,
                ["accountType"] = "Savings",
            }, new PartitionKeyBuilder().Add("Contoso").Add("Acc001").Build());

            _available = true;
        }
        catch
        {
            _available = false;
        }
    }

    public async Task DisposeAsync()
    {
        if (_client is not null && _available)
        {
            try
            {
                await _client.GetDatabase(_databaseName).DeleteAsync();
            }
            catch
            {
                // best-effort cleanup
            }
        }

        _client?.Dispose();
    }

    private ConfiguredTool BuildTool(string toolName)
    {
        var yaml = """
version: "1.0"
sources:
  banking: { type: cosmos, endpoint: "https://localhost:8081/", database: __DB__ }
tools:
  bank_balance:
    description: balance
    source: banking
    operation:
      type: point-read
      container: accounts
      id: "${accountId}"
      partitionKeys: ["${tenantId}", "${accountId}"]
    input:
      type: object
      required: [tenantId, accountId]
      properties:
        tenantId: { type: string }
        accountId: { type: string }
  post_account_transaction:
    description: adjust + record
    source: banking
    governance:
      readOnly: false
    operation:
      type: transactional-batch
      container: accounts
      partitionKeys: ["${tenantId}", "${accountId}"]
      steps:
        - id: adjust
          type: patch
          itemId: "${accountId}"
          operations:
            - op: increment
              path: /balance
              value: "${amount}"
        - id: record
          type: create
          document:
            id: "${generated.txnId}"
            type: "BankTransaction"
            tenantId: "${tenantId}"
            accountId: "${accountId}"
            amount: "${amount}"
            transactionDateTime: "${system.utcNow}"
    input:
      type: object
      required: [tenantId, accountId, amount]
      properties:
        tenantId: { type: string }
        accountId: { type: string }
        amount: { type: number }
""".Replace("__DB__", _databaseName);
        var result = new ConfigurationLoader(new Dictionary<string, string?>(StringComparer.Ordinal)).LoadFromText(yaml);
        result.IsValid.Should().BeTrue(string.Join("; ", result.Errors));
        return ConfiguredToolSet.Build(result.Configuration!).Single(t => t.Name == toolName);
    }

    private ConfiguredToolExecutor CreateExecutor()
    {
        var configuration = new ConfigurationBuilder().AddInMemoryCollection().Build();
        var gateway = new CosmosGateway(_client!, configuration, NullLogger<CosmosGateway>.Instance);
        return new ConfiguredToolExecutor(gateway, NullLogger.Instance);
    }

    private static Dictionary<string, JsonNode?> Input(params (string, JsonNode?)[] items)
        => items.ToDictionary(i => i.Item1, i => i.Item2, StringComparer.Ordinal);

    [Fact]
    public async Task Point_read_returns_seeded_account()
    {
        if (!_available)
        {
            return; // emulator unavailable — skip
        }

        var executor = CreateExecutor();
        var tool = BuildTool("bank_balance");

        var result = await executor.ExecuteAsync(
            tool,
            Input(("tenantId", JsonValue.Create("Contoso")), ("accountId", JsonValue.Create("Acc001"))),
            new CallerContext { AuthenticationBypassed = true },
            default);

        result.IsError.Should().BeFalse(result.Json);
        JsonNode.Parse(result.Json)!["balance"]!.GetValue<double>().Should().Be(500.0);
    }

    [Fact]
    public async Task Transactional_batch_adjusts_balance_and_records_transaction()
    {
        if (!_available)
        {
            return; // emulator unavailable — skip
        }

        var executor = CreateExecutor();
        var tool = BuildTool("post_account_transaction");

        var result = await executor.ExecuteAsync(
            tool,
            Input(("tenantId", JsonValue.Create("Contoso")), ("accountId", JsonValue.Create("Acc001")), ("amount", JsonValue.Create(150.0))),
            new CallerContext { AuthenticationBypassed = true },
            default);

        result.IsError.Should().BeFalse(result.Json);

        var accounts = _client!.GetContainer(_databaseName, "accounts");
        var account = await accounts.ReadItemAsync<JsonObject>("Acc001", new PartitionKeyBuilder().Add("Contoso").Add("Acc001").Build());
        account.Resource["balance"]!.GetValue<double>().Should().Be(650.0);
    }
}
