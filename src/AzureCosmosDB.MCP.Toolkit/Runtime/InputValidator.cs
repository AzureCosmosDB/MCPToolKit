using System.Text.Json;
using System.Text.Json.Nodes;
using System.Text.RegularExpressions;
using AzureCosmosDB.MCP.Toolkit.Configuration;

namespace AzureCosmosDB.MCP.Toolkit.Runtime;

/// <summary>Result of validating and coercing tool input against its declared schema.</summary>
public sealed class InputValidationResult
{
    public bool IsValid => Errors.Count == 0;
    public List<string> Errors { get; } = new();

    /// <summary>Validated, coerced, default-populated input values keyed by property name.</summary>
    public Dictionary<string, JsonNode?> Values { get; } = new(StringComparer.Ordinal);
}

/// <summary>
/// Validates caller-supplied arguments against a declarative input schema.
/// Produces structured, client-safe error messages and never throws on invalid input.
/// </summary>
public static class InputValidator
{
    public static InputValidationResult Validate(InputSchemaConfiguration? schema, IReadOnlyDictionary<string, JsonNode?> input)
    {
        var result = new InputValidationResult();

        if (schema is null)
        {
            foreach (var (key, value) in input)
            {
                result.Values[key] = value?.DeepClone();
            }

            return result;
        }

        var properties = schema.Properties ?? new Dictionary<string, PropertySchema>();
        var required = schema.Required ?? new List<string>();

        foreach (var name in required)
        {
            if (!input.TryGetValue(name, out var v) || v is null)
            {
                result.Errors.Add($"Missing required property '{name}'.");
            }
        }

        foreach (var (name, propSchema) in properties)
        {
            if (input.TryGetValue(name, out var value) && value is not null)
            {
                ValidateProperty(name, propSchema, value, result);
            }
            else if (propSchema.Default is not null)
            {
                result.Values[name] = JsonSerializer.SerializeToNode(propSchema.Default);
            }
        }

        // Reject unknown properties (closed schema) to mirror the built-in tools' behavior.
        foreach (var (name, _) in input)
        {
            if (!properties.ContainsKey(name))
            {
                result.Errors.Add($"Unknown property '{name}'.");
            }
        }

        return result;
    }

    private static void ValidateProperty(string name, PropertySchema schema, JsonNode value, InputValidationResult result)
    {
        var beforeErrors = result.Errors.Count;

        switch (schema.Type.ToLowerInvariant())
        {
            case "string":
                if (TryGetString(value, out var s))
                {
                    ValidateString(name, schema, s, result);
                    if (result.Errors.Count == beforeErrors)
                    {
                        result.Values[name] = s;
                    }
                }
                else
                {
                    result.Errors.Add($"Property '{name}' must be a string.");
                }
                break;

            case "integer":
                if (TryGetInteger(value, out var l))
                {
                    ValidateNumber(name, schema, l, result);
                    if (result.Errors.Count == beforeErrors)
                    {
                        result.Values[name] = l;
                    }
                }
                else
                {
                    result.Errors.Add($"Property '{name}' must be an integer.");
                }
                break;

            case "number":
                if (TryGetNumber(value, out var d))
                {
                    ValidateNumber(name, schema, d, result);
                    if (result.Errors.Count == beforeErrors)
                    {
                        result.Values[name] = d;
                    }
                }
                else
                {
                    result.Errors.Add($"Property '{name}' must be a number.");
                }
                break;

            case "boolean":
                if (value is JsonValue bv && bv.TryGetValue<bool>(out var b))
                {
                    result.Values[name] = b;
                }
                else
                {
                    result.Errors.Add($"Property '{name}' must be a boolean.");
                }
                break;

            case "array":
                if (value is JsonArray arr)
                {
                    ValidateArray(name, schema, arr, result);
                    if (result.Errors.Count == beforeErrors)
                    {
                        result.Values[name] = arr.DeepClone();
                    }
                }
                else
                {
                    result.Errors.Add($"Property '{name}' must be an array.");
                }
                break;

            case "object":
                if (value is JsonObject obj)
                {
                    if (schema.Properties is not null)
                    {
                        var nested = new InputSchemaConfiguration
                        {
                            Type = "object",
                            Required = schema.Required,
                            Properties = schema.Properties,
                        };
                        var nestedInput = obj.ToDictionary(kvp => kvp.Key, kvp => kvp.Value);
                        var nestedResult = Validate(nested, nestedInput);
                        foreach (var err in nestedResult.Errors)
                        {
                            result.Errors.Add($"{name}.{err}");
                        }
                    }

                    if (result.Errors.Count == beforeErrors)
                    {
                        result.Values[name] = obj.DeepClone();
                    }
                }
                else
                {
                    result.Errors.Add($"Property '{name}' must be an object.");
                }
                break;

            default:
                result.Values[name] = value.DeepClone();
                break;
        }

        if (schema.Enum is { Count: > 0 } enumValues && result.Errors.Count == beforeErrors)
        {
            var allowed = enumValues.Select(e => JsonSerializer.Serialize(e)).ToHashSet(StringComparer.Ordinal);
            var actual = value.ToJsonString();
            if (!allowed.Contains(actual))
            {
                result.Errors.Add($"Property '{name}' must be one of: {string.Join(", ", enumValues)}.");
            }
        }
    }

    private static void ValidateString(string name, PropertySchema schema, string value, InputValidationResult result)
    {
        if (schema.MinLength is int min && value.Length < min)
        {
            result.Errors.Add($"Property '{name}' must be at least {min} characters.");
        }

        if (schema.MaxLength is int max && value.Length > max)
        {
            result.Errors.Add($"Property '{name}' must be at most {max} characters.");
        }

        if (!string.IsNullOrEmpty(schema.Pattern) && !Regex.IsMatch(value, schema.Pattern))
        {
            result.Errors.Add($"Property '{name}' does not match the required pattern.");
        }
    }

    private static void ValidateNumber(string name, PropertySchema schema, double value, InputValidationResult result)
    {
        if (schema.Minimum is double min && value < min)
        {
            result.Errors.Add($"Property '{name}' must be >= {min}.");
        }

        if (schema.Maximum is double max && value > max)
        {
            result.Errors.Add($"Property '{name}' must be <= {max}.");
        }
    }

    private static void ValidateArray(string name, PropertySchema schema, JsonArray array, InputValidationResult result)
    {
        if (schema.MinItems is int min && array.Count < min)
        {
            result.Errors.Add($"Property '{name}' must contain at least {min} items.");
        }

        if (schema.MaxItems is int max && array.Count > max)
        {
            result.Errors.Add($"Property '{name}' must contain at most {max} items.");
        }

        if (schema.Items is not null)
        {
            for (var i = 0; i < array.Count; i++)
            {
                var item = array[i];
                if (item is not null)
                {
                    ValidateProperty($"{name}[{i}]", schema.Items, item, result);
                }
            }
        }
    }

    private static bool TryGetString(JsonNode node, out string value)
    {
        if (node is JsonValue jv && jv.TryGetValue<string>(out var s) && s is not null)
        {
            value = s;
            return true;
        }

        value = string.Empty;
        return false;
    }

    private static bool TryGetInteger(JsonNode node, out long value)
    {
        value = 0;
        if (node is not JsonValue jv)
        {
            return false;
        }

        if (jv.TryGetValue<long>(out var l))
        {
            value = l;
            return true;
        }

        // Reject fractional numbers and numeric strings so that types stay strict.
        return false;
    }

    private static bool TryGetNumber(JsonNode node, out double value)
    {
        value = 0;
        if (node is JsonValue jv && jv.TryGetValue<double>(out var d))
        {
            value = d;
            return true;
        }

        return false;
    }
}
