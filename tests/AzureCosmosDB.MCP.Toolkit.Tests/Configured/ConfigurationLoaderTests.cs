using AzureCosmosDB.MCP.Toolkit.Configuration;
using FluentAssertions;
using Xunit;

namespace AzureCosmosDB.MCP.Toolkit.Tests.Configured;

public class ConfigurationLoaderTests
{
    private static ConfigurationLoader Loader(Dictionary<string, string?>? env = null)
        => new(env ?? new Dictionary<string, string?>(StringComparer.Ordinal));

    private const string BankingYaml = """
version: "1.0"
sources:
  banking:
    type: cosmos
    endpoint: "${COSMOS_ENDPOINT}"
    database: banking
    authentication:
      type: managed-identity
defaults:
  governance:
    timeoutMs: 5000
    maxItems: 100
    readOnly: true
tools:
  get_account_balance:
    description: Returns the current balance for an account.
    source: banking
    operation:
      type: point-read
      container: accounts
      id: "${accountId}"
      partitionKey: "${customerId}"
    input:
      type: object
      required: [customerId, accountId]
      properties:
        customerId:
          type: string
        accountId:
          type: string
    output:
      select:
        accountId: accountId
        balance: balance
""";

    [Fact]
    public void Loads_valid_yaml_and_substitutes_environment()
    {
        var loader = Loader(new Dictionary<string, string?>(StringComparer.Ordinal) { ["COSMOS_ENDPOINT"] = "https://acct.documents.azure.com/" });

        var result = loader.LoadFromText(BankingYaml);

        result.IsValid.Should().BeTrue(string.Join("; ", result.Errors));
        result.Configuration!.Version.Should().Be("1.0");
        result.Configuration.Sources["banking"].Endpoint.Should().Be("https://acct.documents.azure.com/");
        result.Configuration.Tools.Should().ContainKey("get_account_balance");
    }

    [Fact]
    public void Preserves_runtime_binding_tokens_that_are_not_environment_variables()
    {
        var loader = Loader(new Dictionary<string, string?>(StringComparer.Ordinal) { ["COSMOS_ENDPOINT"] = "https://acct/" });

        var result = loader.LoadFromText(BankingYaml);

        result.Configuration!.Tools["get_account_balance"].Operation!.Id.Should().Be("${accountId}");
    }

    [Fact]
    public void Explicit_env_token_missing_is_an_error()
    {
        var loader = Loader();
        var yaml = BankingYaml.Replace("${COSMOS_ENDPOINT}", "${env:COSMOS_ENDPOINT}");

        var result = loader.LoadFromText(yaml);

        result.IsValid.Should().BeFalse();
        result.Errors.Should().ContainMatch("*COSMOS_ENDPOINT*not set*");
    }

    [Fact]
    public void Loads_equivalent_json()
    {
        var loader = Loader(new Dictionary<string, string?>(StringComparer.Ordinal) { ["COSMOS_ENDPOINT"] = "https://acct/" });
        const string json = """
        {
          "version": "1.0",
          "sources": { "banking": { "type": "cosmos", "endpoint": "https://acct/", "database": "banking" } },
          "tools": {
            "get_account_balance": {
              "description": "d",
              "source": "banking",
              "operation": { "type": "point-read", "container": "accounts", "id": "${accountId}", "partitionKey": "${customerId}" }
            }
          }
        }
        """;

        var result = loader.LoadFromText(json, isJson: true);

        result.IsValid.Should().BeTrue(string.Join("; ", result.Errors));
        result.Configuration!.Tools["get_account_balance"].Operation!.Container.Should().Be("accounts");
    }

    [Fact]
    public void Empty_document_fails_closed()
    {
        Loader().LoadFromText("   ").IsValid.Should().BeFalse();
    }
}
