using System.Text.Json;
using System.Text.Json.Nodes;
using AzureCosmosDB.MCP.Toolkit.Configuration;
using AzureCosmosDB.MCP.Toolkit.Runtime;
using FluentAssertions;
using Xunit;

namespace AzureCosmosDB.MCP.Toolkit.Tests.Configured;

public class InputValidatorTests
{
    private static Dictionary<string, JsonNode?> Input(params (string, JsonNode?)[] items)
        => items.ToDictionary(i => i.Item1, i => i.Item2, StringComparer.Ordinal);

    private static InputSchemaConfiguration Schema() => new()
    {
        Type = "object",
        Required = new() { "customerId", "amount" },
        Properties = new()
        {
            ["customerId"] = new PropertySchema { Type = "string", MinLength = 1 },
            ["amount"] = new PropertySchema { Type = "number", Minimum = 0.01 },
            ["limit"] = new PropertySchema { Type = "integer", Minimum = 1, Maximum = 20, Default = 10 },
            ["category"] = new PropertySchema { Type = "string", Enum = new() { "a", "b" } },
        },
    };

    [Fact]
    public void Missing_required_property_is_reported()
    {
        var result = InputValidator.Validate(Schema(), Input(("amount", JsonValue.Create(5.0))));
        result.IsValid.Should().BeFalse();
        result.Errors.Should().ContainMatch("*Missing required property 'customerId'*");
    }

    [Fact]
    public void Applies_default_for_absent_optional_property()
    {
        var result = InputValidator.Validate(Schema(), Input(("customerId", JsonValue.Create("c1")), ("amount", JsonValue.Create(5.0))));
        result.IsValid.Should().BeTrue(string.Join(";", result.Errors));
        result.Values["limit"]!.GetValue<int>().Should().Be(10);
    }

    [Fact]
    public void Rejects_wrong_type()
    {
        var result = InputValidator.Validate(Schema(), Input(("customerId", JsonValue.Create("c1")), ("amount", JsonValue.Create("not-a-number"))));
        result.IsValid.Should().BeFalse();
        result.Errors.Should().ContainMatch("*'amount' must be a number*");
    }

    [Fact]
    public void Enforces_numeric_minimum()
    {
        var result = InputValidator.Validate(Schema(), Input(("customerId", JsonValue.Create("c1")), ("amount", JsonValue.Create(0.0))));
        result.Errors.Should().ContainMatch("*'amount' must be >= 0.01*");
    }

    [Fact]
    public void Enforces_enum()
    {
        var result = InputValidator.Validate(Schema(), Input(
            ("customerId", JsonValue.Create("c1")), ("amount", JsonValue.Create(5.0)), ("category", JsonValue.Create("z"))));
        result.Errors.Should().ContainMatch("*'category' must be one of*");
    }

    [Fact]
    public void Rejects_unknown_property_closed_schema()
    {
        var result = InputValidator.Validate(Schema(), Input(
            ("customerId", JsonValue.Create("c1")), ("amount", JsonValue.Create(5.0)), ("surprise", JsonValue.Create("x"))));
        result.Errors.Should().ContainMatch("*Unknown property 'surprise'*");
    }
}

public class BindingContextTests
{
    private static Dictionary<string, JsonNode?> Input(params (string, JsonNode?)[] items)
        => items.ToDictionary(i => i.Item1, i => i.Item2, StringComparer.Ordinal);

    [Fact]
    public void Binds_bare_and_prefixed_tokens_preserving_type()
    {
        var ctx = new BindingContext(Input(("accountId", JsonValue.Create("A1")), ("amount", JsonValue.Create(42.5))));
        ctx.BindToString("${accountId}").Should().Be("A1");
        ctx.BindTemplate("${input.amount}")!.GetValue<double>().Should().Be(42.5);
    }

    [Fact]
    public void Embedded_token_produces_string_interpolation()
    {
        var ctx = new BindingContext(Input(("accountId", JsonValue.Create("A1"))));
        ctx.BindToString("acct-${accountId}-suffix").Should().Be("acct-A1-suffix");
    }

    [Fact]
    public void System_and_generated_values_resolve()
    {
        var ctx = new BindingContext(Input(), new DateTimeOffset(2026, 1, 2, 3, 4, 5, TimeSpan.Zero));
        ctx.BindToString("${system.utcNow}").Should().StartWith("2026-01-02T03:04:05");
        var g1 = ctx.BindToString("${generated.id}");
        var g2 = ctx.BindToString("${generated.id}");
        g1.Should().Be(g2).And.NotBeNullOrEmpty();
    }

    [Fact]
    public void Malicious_input_is_not_interpreted_as_sql_it_stays_a_value()
    {
        // Injection resistance: a SQL-looking string binds as a literal value, never as SQL.
        var evil = "'; DROP TABLE accounts; --";
        var ctx = new BindingContext(Input(("accountId", JsonValue.Create(evil))));
        ctx.BindToString("${accountId}").Should().Be(evil);
    }

    [Fact]
    public void Binds_nested_document_recursively()
    {
        var ctx = new BindingContext(Input(("customerId", JsonValue.Create("C9")), ("amount", JsonValue.Create(100.0))));
        var doc = new Dictionary<string, object?>
        {
            ["customerId"] = "${customerId}",
            ["amount"] = "${amount}",
            ["status"] = "open",
        };

        var bound = (JsonObject)ctx.Bind(doc)!;
        bound["customerId"]!.GetValue<string>().Should().Be("C9");
        bound["amount"]!.GetValue<double>().Should().Be(100.0);
        bound["status"]!.GetValue<string>().Should().Be("open");
    }
}

public class SafeExpressionEvaluatorTests
{
    private static BindingContext Ctx() => new(new Dictionary<string, JsonNode?>(StringComparer.Ordinal)
    {
        ["amount"] = JsonValue.Create(50.0),
    });

    [Fact]
    public void Evaluates_numeric_comparison_with_step_output()
    {
        var ctx = Ctx();
        ctx.SetStepOutput("source", new JsonObject { ["balance"] = 100.0 });
        SafeExpressionEvaluator.Evaluate("${steps.source.balance >= input.amount}", ctx, out _).Should().BeTrue();
    }

    [Fact]
    public void Fails_when_condition_false()
    {
        var ctx = Ctx();
        ctx.SetStepOutput("source", new JsonObject { ["balance"] = 10.0 });
        SafeExpressionEvaluator.Evaluate("${steps.source.balance >= input.amount}", ctx, out _).Should().BeFalse();
    }

    [Fact]
    public void Supports_logical_and()
    {
        var ctx = Ctx();
        SafeExpressionEvaluator.Evaluate("input.amount > 0 && input.amount < 100", ctx, out _).Should().BeTrue();
    }
}

public class OutputProjectorTests
{
    [Fact]
    public void Projects_renames_and_redacts()
    {
        var input = new JsonObject
        {
            ["accountId"] = "A1",
            ["balance"] = 500.0,
            ["currency"] = "USD",
            ["internalRiskScore"] = 7,
        };
        var output = new OutputConfiguration
        {
            Select = new() { ["accountId"] = "accountId", ["availableBalance"] = "balance" },
            Redact = new() { "internalRiskScore" },
        };

        var shaped = (JsonObject)OutputProjector.Apply(input, output)!;

        shaped.ContainsKey("availableBalance").Should().BeTrue();
        shaped["availableBalance"]!.GetValue<double>().Should().Be(500.0);
        shaped.ContainsKey("currency").Should().BeFalse();
        shaped.ContainsKey("internalRiskScore").Should().BeFalse();
    }

    [Fact]
    public void Limits_array_results()
    {
        var arr = new JsonArray(
            new JsonObject { ["id"] = "1" },
            new JsonObject { ["id"] = "2" },
            new JsonObject { ["id"] = "3" });
        var output = new OutputConfiguration { MaxItems = 2 };

        ((JsonArray)OutputProjector.Apply(arr, output)!).Count.Should().Be(2);
    }
}

public class JsonSchemaGeneratorTests
{
    [Fact]
    public void Generates_closed_schema_with_required_and_constraints()
    {
        var schema = new InputSchemaConfiguration
        {
            Required = new() { "customerId" },
            Properties = new()
            {
                ["customerId"] = new PropertySchema { Type = "string", Description = "cust" },
                ["limit"] = new PropertySchema { Type = "integer", Minimum = 1, Maximum = 20 },
            },
        };

        var element = JsonSchemaGenerator.Generate(schema);

        element.GetProperty("additionalProperties").GetBoolean().Should().BeFalse();
        element.GetProperty("required")[0].GetString().Should().Be("customerId");
        element.GetProperty("properties").GetProperty("limit").GetProperty("maximum").GetDouble().Should().Be(20);
    }
}
