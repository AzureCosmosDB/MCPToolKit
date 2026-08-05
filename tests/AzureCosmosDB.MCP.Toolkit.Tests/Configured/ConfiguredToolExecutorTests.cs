using System.Security.Claims;
using System.Text.Json.Nodes;
using AzureCosmosDB.MCP.Toolkit.Configuration;
using AzureCosmosDB.MCP.Toolkit.Runtime;
using FluentAssertions;
using Microsoft.Extensions.Logging.Abstractions;
using Xunit;

namespace AzureCosmosDB.MCP.Toolkit.Tests.Configured;

public class ConfiguredToolExecutorTests
{
    private static ConfiguredTool BuildTool(string yaml, string toolKey)
    {
        var loader = new ConfigurationLoader(new Dictionary<string, string?>(StringComparer.Ordinal) { ["COSMOS_ENDPOINT"] = "https://acct/" });
        var result = loader.LoadFromText(yaml);
        result.IsValid.Should().BeTrue(string.Join("; ", result.Errors));
        return ConfiguredToolSet.Build(result.Configuration!).Single(t => t.Name == toolKey);
    }

    private static Dictionary<string, JsonNode?> Input(params (string, JsonNode?)[] items)
        => items.ToDictionary(i => i.Item1, i => i.Item2, StringComparer.Ordinal);

    private static CallerContext Bypass => new() { AuthenticationBypassed = true };

    private const string PointReadYaml = """
version: "1.0"
sources:
  banking: { type: cosmos, endpoint: "${COSMOS_ENDPOINT}", database: banking }
tools:
  get_account_balance:
    description: balance
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
        customerId: { type: string }
        accountId: { type: string }
    output:
      select:
        accountId: accountId
        availableBalance: balance
      redact: [internalRiskScore]
""";

    [Fact]
    public async Task Point_read_binds_id_and_partition_and_projects_output()
    {
        var tool = BuildTool(PointReadYaml, "get_account_balance");
        var gateway = new FakeCosmosGateway
        {
            PointReadResult = new JsonObject { ["accountId"] = "A1", ["balance"] = 250.0, ["internalRiskScore"] = 9 },
        };
        var executor = new ConfiguredToolExecutor(gateway, NullLogger.Instance);

        var result = await executor.ExecuteAsync(tool, Input(("customerId", JsonValue.Create("C1")), ("accountId", JsonValue.Create("A1"))), Bypass, default);

        result.IsError.Should().BeFalse();
        gateway.LastId.Should().Be("A1");
        gateway.LastPartitionKey.Should().Be("C1");
        var node = JsonNode.Parse(result.Json)!;
        node["availableBalance"]!.GetValue<double>().Should().Be(250.0);
        node.AsObject().ContainsKey("internalRiskScore").Should().BeFalse();
    }

    [Fact]
    public async Task Invalid_input_returns_structured_validation_error()
    {
        var tool = BuildTool(PointReadYaml, "get_account_balance");
        var executor = new ConfiguredToolExecutor(new FakeCosmosGateway(), NullLogger.Instance);

        var result = await executor.ExecuteAsync(tool, Input(("accountId", JsonValue.Create("A1"))), Bypass, default);

        result.IsError.Should().BeTrue();
        result.Category.Should().Be("validation");
        result.Json.Should().Contain("customerId");
    }

    private const string QueryYaml = """
version: "1.0"
sources:
  banking: { type: cosmos, endpoint: "${COSMOS_ENDPOINT}", database: banking }
tools:
  get_transaction_history:
    description: history
    source: banking
    operation:
      type: query
      container: transactions
      statement: "SELECT TOP @limit c.id, c.amount FROM c WHERE c.accountId = @accountId ORDER BY c.timestamp DESC"
      parameters:
        accountId: "${accountId}"
        limit: "${limit}"
      partitionKey: "${accountId}"
    input:
      type: object
      required: [accountId]
      properties:
        accountId: { type: string }
        limit: { type: integer, default: 10, minimum: 1, maximum: 50 }
""";

    [Fact]
    public async Task Query_binds_parameters_safely_including_injection_attempt()
    {
        var tool = BuildTool(QueryYaml, "get_transaction_history");
        var gateway = new FakeCosmosGateway { QueryResult = new JsonArray(new JsonObject { ["id"] = "t1" }) };
        var executor = new ConfiguredToolExecutor(gateway, NullLogger.Instance);
        var evil = "A1' OR '1'='1";

        var result = await executor.ExecuteAsync(tool, Input(("accountId", JsonValue.Create(evil))), Bypass, default);

        result.IsError.Should().BeFalse();
        // The statement text is untouched; the malicious value is bound as a parameter value only.
        gateway.LastQuery!.Statement.Should().NotContain(evil);
        gateway.LastQuery.Parameters["accountId"]!.GetValue<string>().Should().Be(evil);
        gateway.LastQuery.Parameters["limit"]!.GetValue<int>().Should().Be(10);
    }

    private const string TransferYaml = """
version: "1.0"
sources:
  banking: { type: cosmos, endpoint: "${COSMOS_ENDPOINT}", database: banking }
tools:
  bank_transfer:
    description: transfer within a customer's accounts
    source: banking
    governance:
      readOnly: false
    operation:
      type: transactional-batch
      container: accounts
      partitionKey: "${customerId}"
      steps:
        - id: debit
          type: patch
          itemId: "${sourceAccountId}"
          operations:
            - op: increment
              path: /balance
              value: "${negativeAmount}"
        - id: credit
          type: patch
          itemId: "${destinationAccountId}"
          operations:
            - op: increment
              path: /balance
              value: "${amount}"
        - id: record
          type: create
          document:
            id: "${generated.transactionId}"
            customerId: "${customerId}"
            amount: "${amount}"
            createdAt: "${system.utcNow}"
    input:
      type: object
      required: [customerId, sourceAccountId, destinationAccountId, amount, negativeAmount]
      properties:
        customerId: { type: string }
        sourceAccountId: { type: string }
        destinationAccountId: { type: string }
        amount: { type: number }
        negativeAmount: { type: number }
""";

    [Fact]
    public async Task Transactional_batch_binds_all_steps_within_one_partition()
    {
        var tool = BuildTool(TransferYaml, "bank_transfer");
        var gateway = new FakeCosmosGateway();
        var executor = new ConfiguredToolExecutor(gateway, NullLogger.Instance);

        var result = await executor.ExecuteAsync(tool, Input(
            ("customerId", JsonValue.Create("C1")),
            ("sourceAccountId", JsonValue.Create("A1")),
            ("destinationAccountId", JsonValue.Create("A2")),
            ("amount", JsonValue.Create(100.0)),
            ("negativeAmount", JsonValue.Create(-100.0))), Bypass, default);

        result.IsError.Should().BeFalse(result.Json);
        gateway.LastPartitionKey.Should().Be("C1");
        gateway.LastBatch!.Should().HaveCount(3);
        gateway.LastBatch![0].ItemId.Should().Be("A1");
        gateway.LastBatch![1].ItemId.Should().Be("A2");
        gateway.LastBatch![2].Type.Should().Be("create");
        gateway.LastBatch![2].Document!["customerId"]!.GetValue<string>().Should().Be("C1");
    }

    [Fact]
    public void Read_only_default_blocks_writes_at_validation_time()
    {
        // The same transfer without governance.readOnly:false must not load as a valid tool.
        const string yaml = """
version: "1.0"
sources:
  banking: { type: cosmos, endpoint: "${COSMOS_ENDPOINT}", database: banking }
tools:
  bank_transfer:
    description: transfer
    source: banking
    operation:
      type: transactional-batch
      container: accounts
      partitionKey: "${customerId}"
      steps:
        - id: record
          type: create
          document:
            id: "${generated.transactionId}"
""";
        var loader = new ConfigurationLoader(new Dictionary<string, string?>(StringComparer.Ordinal) { ["COSMOS_ENDPOINT"] = "https://acct/" });
        var result = loader.LoadFromText(yaml);

        result.IsValid.Should().BeFalse();
        result.Errors.Should().ContainMatch("*readOnly is not disabled*");
    }
}

public class AuthorizationEvaluatorTests
{
    private static Dictionary<string, JsonNode?> Input(params (string, JsonNode?)[] items)
        => items.ToDictionary(i => i.Item1, i => i.Item2, StringComparer.Ordinal);

    private static CallerContext Caller(bool authenticated, IEnumerable<string>? scopes = null, (string, string)[]? claims = null)
    {
        var identity = new ClaimsIdentity(authenticated ? "test" : null);
        if (scopes is not null)
        {
            identity.AddClaim(new Claim("scp", string.Join(' ', scopes)));
        }

        foreach (var (t, v) in claims ?? Array.Empty<(string, string)>())
        {
            identity.AddClaim(new Claim(t, v));
        }

        return CallerContext.FromPrincipal(new ClaimsPrincipal(identity), authenticationBypassed: false);
    }

    [Fact]
    public void Missing_scope_is_denied()
    {
        var auth = new AuthorizationConfiguration { RequiredScopes = new() { "banking.accounts.read" } };
        var result = AuthorizationEvaluator.Authorize(auth, Caller(true, scopes: new[] { "other.scope" }), Input());
        result.Allowed.Should().BeFalse();
        result.Error.Should().Contain("scope");
    }

    [Fact]
    public void Present_scope_is_allowed()
    {
        var auth = new AuthorizationConfiguration { RequiredScopes = new() { "banking.accounts.read" } };
        AuthorizationEvaluator.Authorize(auth, Caller(true, scopes: new[] { "banking.accounts.read" }), Input()).Allowed.Should().BeTrue();
    }

    [Fact]
    public void Unauthenticated_caller_is_denied_when_policy_present()
    {
        var auth = new AuthorizationConfiguration { RequiredScopes = new() { "banking.accounts.read" } };
        AuthorizationEvaluator.Authorize(auth, Caller(false), Input()).Allowed.Should().BeFalse();
    }

    [Fact]
    public void Model_supplied_tenant_cannot_spoof_a_different_tenant()
    {
        var auth = new AuthorizationConfiguration { TenantClaim = "tid", TenantField = "tenantId" };
        var caller = Caller(true, claims: new[] { ("tid", "tenant-A") });
        var input = Input(("tenantId", JsonValue.Create("tenant-B")));

        AuthorizationEvaluator.Authorize(auth, caller, input).Allowed.Should().BeFalse();
    }

    [Fact]
    public void Identity_derived_input_overwrites_model_supplied_tenant()
    {
        var auth = new AuthorizationConfiguration { TenantClaim = "tid", TenantField = "tenantId" };
        var caller = Caller(true, claims: new[] { ("tid", "tenant-A") });
        var input = Input(("tenantId", JsonValue.Create("tenant-A")));

        var overlaid = AuthorizationEvaluator.ApplyIdentityDerivedInputs(auth, caller, input);
        overlaid["tenantId"]!.GetValue<string>().Should().Be("tenant-A");
    }
}
