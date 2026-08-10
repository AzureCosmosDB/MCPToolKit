using AzureCosmosDB.MCP.Toolkit.Configuration;
using FluentAssertions;
using Xunit;

namespace AzureCosmosDB.MCP.Toolkit.Tests.Configured;

public class ConfigurationValidatorTests
{
    private static ConfigurationLoadResult Load(string yaml)
        => new ConfigurationLoader(new Dictionary<string, string?>(StringComparer.Ordinal) { ["COSMOS_ENDPOINT"] = "https://acct/" })
            .LoadFromText(yaml);

    private const string Header = """
version: "1.0"
sources:
  banking:
    type: cosmos
    endpoint: "${COSMOS_ENDPOINT}"
    database: banking
tools:

""";

    [Fact]
    public void Write_operation_without_readOnly_false_fails_closed()
    {
        var yaml = Header + """
  create_account:
    description: create
    source: banking
    operation:
      type: create
      container: accounts
      partitionKey: "${customerId}"
      document:
        id: "${generated.id}"
""";

        var result = Load(yaml);

        result.IsValid.Should().BeFalse();
        result.Errors.Should().ContainMatch("*readOnly is not disabled*");
    }

    [Fact]
    public void Write_operation_with_readOnly_false_is_allowed()
    {
        var yaml = Header + """
  create_account:
    description: create
    source: banking
    governance:
      readOnly: false
    operation:
      type: create
      container: accounts
      partitionKey: "${customerId}"
      document:
        id: "${generated.id}"
""";

        Load(yaml).IsValid.Should().BeTrue();
    }

    [Fact]
    public void Delete_requires_allowDelete()
    {
        var yaml = Header + """
  remove_it:
    description: d
    source: banking
    governance:
      readOnly: false
    operation:
      type: delete
      container: accounts
      id: "${id}"
      partitionKey: "${customerId}"
""";

        var result = Load(yaml);
        result.IsValid.Should().BeFalse();
        result.Errors.Should().ContainMatch("*allowDelete*");
    }

    [Fact]
    public void Unknown_operation_type_fails()
    {
        var yaml = Header + """
  weird:
    description: d
    source: banking
    operation:
      type: teleport
      container: accounts
""";

        Load(yaml).Errors.Should().ContainMatch("*unknown operation type*");
    }

    [Fact]
    public void Vector_search_requires_explicit_select()
    {
        var yaml = Header + """
  search_offers:
    description: d
    source: banking
    operation:
      type: vector-search
      container: offers
      vectorPath: /embedding
      searchText: "${query}"
""";

        Load(yaml).Errors.Should().ContainMatch("*requires an explicit 'select'*");
    }

    [Fact]
    public void Patch_path_outside_allowlist_is_rejected()
    {
        var yaml = Header + """
  patch_it:
    description: d
    source: banking
    governance:
      readOnly: false
      allowedPatchPaths: ["/balance"]
    operation:
      type: patch
      container: accounts
      id: "${id}"
      partitionKey: "${customerId}"
      operations:
        - op: replace
          path: /creditLimit
          value: "${x}"
""";

        Load(yaml).Errors.Should().ContainMatch("*not in governance.allowedPatchPaths*");
    }

    [Fact]
    public void Unknown_source_is_rejected()
    {
        var yaml = Header + """
  t:
    description: d
    source: nope
    operation:
      type: point-read
      container: accounts
      id: "${id}"
      partitionKey: "${pk}"
""";

        Load(yaml).Errors.Should().ContainMatch("*unknown source*");
    }
}
