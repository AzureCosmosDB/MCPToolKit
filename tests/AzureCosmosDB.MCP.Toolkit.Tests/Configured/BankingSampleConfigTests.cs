using AzureCosmosDB.MCP.Toolkit.Configuration;
using AzureCosmosDB.MCP.Toolkit.Runtime;
using FluentAssertions;
using Xunit;

namespace AzureCosmosDB.MCP.Toolkit.Tests.Configured;

/// <summary>
/// Validates the shipped banking sample configuration exactly as an operator would load it,
/// proving the documented example is correct and stays correct.
/// </summary>
public class BankingSampleConfigTests
{
    private static string SamplePath => Path.Combine(AppContext.BaseDirectory, "samples", "banking-cosmos-tools.yaml");

    [Fact]
    public void Sample_file_exists()
    {
        File.Exists(SamplePath).Should().BeTrue($"the banking sample should be copied to '{SamplePath}'.");
    }

    [Fact]
    public void Sample_loads_and_validates()
    {
        var env = new Dictionary<string, string?>(StringComparer.Ordinal)
        {
            ["COSMOS_ENDPOINT"] = "https://banking.documents.azure.com/",
            ["COSMOS_DATABASE"] = "banking",
        };

        var result = new ConfigurationLoader(env).LoadFromFile(SamplePath);

        result.IsValid.Should().BeTrue(string.Join("; ", result.Errors));
        result.Configuration!.Sources["banking"].Database.Should().Be("banking");
    }

    [Fact]
    public void Sample_registers_expected_banking_tools()
    {
        var env = new Dictionary<string, string?>(StringComparer.Ordinal)
        {
            ["COSMOS_ENDPOINT"] = "https://banking.documents.azure.com/",
            ["COSMOS_DATABASE"] = "banking",
        };

        var result = new ConfigurationLoader(env).LoadFromFile(SamplePath);
        var tools = ConfiguredToolSet.Build(result.Configuration!);

        tools.Select(t => t.Name).Should().Contain(new[]
        {
            "bank_balance", "get_transaction_history", "get_offer_information",
            "create_account", "service_request", "bank_transfer", "post_account_transaction",
        });

        // Read-only tools stay read-only; write tools are explicitly enabled.
        tools.Single(t => t.Name == "bank_balance").IsWrite.Should().BeFalse();
        tools.Single(t => t.Name == "create_account").IsWrite.Should().BeTrue();
        tools.Single(t => t.Name == "post_account_transaction").Governance.ReadOnly.Should().BeFalse();
    }
}
