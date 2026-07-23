using System.Text;
using System.Text.Json;

namespace AzureCosmosDB.MCP.Toolkit.Services;

public sealed class McpToolRequestValidator
{
    private const int MaxToolNameLength = 64;

    private static readonly IReadOnlyDictionary<string, ToolSchema> Schemas =
        new Dictionary<string, ToolSchema>(StringComparer.OrdinalIgnoreCase)
        {
            ["list_databases"] = new(new Dictionary<string, ToolArgumentSchema>(StringComparer.Ordinal)),
            ["list_collections"] = new(new Dictionary<string, ToolArgumentSchema>(StringComparer.Ordinal)
            {
                ["databaseId"] = ToolArgumentSchema.String(required: true, maxLength: 256)
            }),
            ["get_recent_documents"] = new(new Dictionary<string, ToolArgumentSchema>(StringComparer.Ordinal)
            {
                ["databaseId"] = ToolArgumentSchema.String(required: true, maxLength: 256),
                ["containerId"] = ToolArgumentSchema.String(required: true, maxLength: 256),
                ["n"] = ToolArgumentSchema.Integer(required: true, minValue: 1, maxValue: 20)
            }),
            ["text_search"] = new(new Dictionary<string, ToolArgumentSchema>(StringComparer.Ordinal)
            {
                ["databaseId"] = ToolArgumentSchema.String(required: true, maxLength: 256),
                ["containerId"] = ToolArgumentSchema.String(required: true, maxLength: 256),
                ["property"] = ToolArgumentSchema.String(required: true, maxLength: 256),
                ["searchPhrase"] = ToolArgumentSchema.String(required: true, maxLength: 2048),
                ["n"] = ToolArgumentSchema.Integer(required: false, minValue: 1, maxValue: 20)
            }),
            ["find_document_by_id"] = new(new Dictionary<string, ToolArgumentSchema>(StringComparer.Ordinal)
            {
                ["databaseId"] = ToolArgumentSchema.String(required: true, maxLength: 256),
                ["containerId"] = ToolArgumentSchema.String(required: true, maxLength: 256),
                ["id"] = ToolArgumentSchema.String(required: true, maxLength: 256)
            }),
            ["get_approximate_schema"] = new(new Dictionary<string, ToolArgumentSchema>(StringComparer.Ordinal)
            {
                ["databaseId"] = ToolArgumentSchema.String(required: true, maxLength: 256),
                ["containerId"] = ToolArgumentSchema.String(required: true, maxLength: 256)
            }),
            ["vector_search"] = new(new Dictionary<string, ToolArgumentSchema>(StringComparer.Ordinal)
            {
                ["databaseId"] = ToolArgumentSchema.String(required: true, maxLength: 256),
                ["containerId"] = ToolArgumentSchema.String(required: true, maxLength: 256),
                ["searchText"] = ToolArgumentSchema.String(required: true, maxLength: 2048),
                ["vectorProperty"] = ToolArgumentSchema.String(required: true, maxLength: 256),
                ["selectProperties"] = ToolArgumentSchema.String(required: true, maxLength: 512),
                ["topN"] = ToolArgumentSchema.Integer(required: false, minValue: 1, maxValue: 50)
            }),
            ["hybrid_search"] = new(new Dictionary<string, ToolArgumentSchema>(StringComparer.Ordinal)
            {
                ["databaseId"] = ToolArgumentSchema.String(required: true, maxLength: 256),
                ["containerId"] = ToolArgumentSchema.String(required: true, maxLength: 256),
                ["searchText"] = ToolArgumentSchema.String(required: true, maxLength: 2048),
                ["textProperty"] = ToolArgumentSchema.String(required: true, maxLength: 256),
                ["vectorProperty"] = ToolArgumentSchema.String(required: true, maxLength: 256),
                ["selectProperties"] = ToolArgumentSchema.String(required: true, maxLength: 512),
                ["topN"] = ToolArgumentSchema.Integer(required: false, minValue: 1, maxValue: 50)
            }),
            ["agentic_search"] = new(new Dictionary<string, ToolArgumentSchema>(StringComparer.Ordinal)
            {
                ["query"] = ToolArgumentSchema.String(required: true, maxLength: 4096),
                ["maxDocuments"] = ToolArgumentSchema.Integer(required: false, minValue: 1, maxValue: 50),
                ["database"] = ToolArgumentSchema.String(required: false, maxLength: 256),
                ["container"] = ToolArgumentSchema.String(required: false, maxLength: 256),
                ["temperature"] = ToolArgumentSchema.Number(required: false, minValue: 0.0, maxValue: 2.0),
                ["maxTurns"] = ToolArgumentSchema.Integer(required: false, minValue: 1, maxValue: 200),
                ["reasoningEffort"] = ToolArgumentSchema.String(required: false, maxLength: 16),
                ["schemaOverride"] = ToolArgumentSchema.Object(required: false, maxLength: 2048),
                ["searchDisplayLimit"] = ToolArgumentSchema.Integer(required: false, minValue: 1, maxValue: 50),
                ["accountUri"] = ToolArgumentSchema.String(required: false, maxLength: 512),
                ["embeddingModel"] = ToolArgumentSchema.String(required: false, maxLength: 256),
                ["embeddingEndpoint"] = ToolArgumentSchema.String(required: false, maxLength: 512)
            })
        };

    public ToolValidationResult ValidateToolCall(JsonElement paramsElement)
    {
        if (paramsElement.ValueKind != JsonValueKind.Object)
        {
            throw new ToolInputValidationException("'params' must be a JSON object.");
        }

        // `_meta` is a standard MCP field clients may attach to params (e.g. progress
        // tokens); accept and ignore it rather than rejecting the request.
        RejectUnknownProperties(paramsElement, ["name", "arguments", "_meta"], "params");

        if (!paramsElement.TryGetProperty("name", out var toolNameElement) || toolNameElement.ValueKind != JsonValueKind.String)
        {
            throw new ToolInputValidationException("'params.name' must be a string.");
        }

        var toolName = ValidateString(toolNameElement.GetString(), "params.name", MaxToolNameLength);
        if (!Schemas.TryGetValue(toolName, out var schema))
        {
            throw new ToolInputValidationException($"Unknown tool '{toolName}'.");
        }

        var argsElement = paramsElement.TryGetProperty("arguments", out var rawArgs)
            ? rawArgs
            : default;

        if (argsElement.ValueKind != JsonValueKind.Undefined && argsElement.ValueKind != JsonValueKind.Object)
        {
            throw new ToolInputValidationException("'params.arguments' must be a JSON object when provided.");
        }

        return new ToolValidationResult(toolName, ValidateArguments(toolName, schema, argsElement));
    }

    private static Dictionary<string, object> ValidateArguments(string toolName, ToolSchema schema, JsonElement argsElement)
    {
        var validated = new Dictionary<string, object>(StringComparer.Ordinal);

        if (argsElement.ValueKind == JsonValueKind.Object)
        {
            RejectUnknownProperties(argsElement, schema.Arguments.Keys, $"arguments for '{toolName}'");
        }

        foreach (var argument in schema.Arguments)
        {
            if (!TryGetProperty(argsElement, argument.Key, out var valueElement))
            {
                if (argument.Value.Required)
                {
                    throw new ToolInputValidationException($"Missing required argument '{argument.Key}' for tool '{toolName}'.");
                }

                continue;
            }

            validated[argument.Key] = argument.Value.Kind switch
            {
                ArgKind.String => ValidateString(valueElement.GetString(), argument.Key, argument.Value.MaxLength),
                ArgKind.Integer => ValidateInteger(valueElement, argument.Key, (int)argument.Value.MinValue, (int)argument.Value.MaxValue),
                ArgKind.Number => ValidateNumber(valueElement, argument.Key, argument.Value.MinValue, argument.Value.MaxValue),
                ArgKind.Boolean => ValidateBoolean(valueElement, argument.Key),
                ArgKind.Object => ValidateObject(valueElement, argument.Key, argument.Value.MaxLength),
                _ => throw new ToolInputValidationException($"Unsupported schema for argument '{argument.Key}'.")
            };
        }

        return validated;
    }

    private static string ValidateString(string? value, string fieldName, int maxLength)
    {
        if (value is null)
        {
            throw new ToolInputValidationException($"'{fieldName}' must be a string.");
        }

        var normalized = value.Normalize(NormalizationForm.FormKC);
        if (string.IsNullOrWhiteSpace(normalized))
        {
            throw new ToolInputValidationException($"'{fieldName}' must not be empty.");
        }

        if (normalized.Length > maxLength)
        {
            throw new ToolInputValidationException($"'{fieldName}' exceeds the maximum length of {maxLength} characters.");
        }

        if (normalized.Any(char.IsControl))
        {
            throw new ToolInputValidationException($"'{fieldName}' contains control characters, which are not allowed.");
        }

        return normalized;
    }

    private static int ValidateInteger(JsonElement valueElement, string fieldName, int minValue, int maxValue)
    {
        if (valueElement.ValueKind != JsonValueKind.Number || !valueElement.TryGetInt32(out var value))
        {
            throw new ToolInputValidationException($"'{fieldName}' must be an integer.");
        }

        if (value < minValue || value > maxValue)
        {
            throw new ToolInputValidationException($"'{fieldName}' must be between {minValue} and {maxValue}.");
        }

        return value;
    }

    private static double ValidateNumber(JsonElement valueElement, string fieldName, double minValue, double maxValue)
    {
        if (valueElement.ValueKind != JsonValueKind.Number || !valueElement.TryGetDouble(out var value))
        {
            throw new ToolInputValidationException($"'{fieldName}' must be a number.");
        }

        if (value < minValue || value > maxValue)
        {
            throw new ToolInputValidationException($"'{fieldName}' must be between {minValue} and {maxValue}.");
        }

        return value;
    }

    private static bool ValidateBoolean(JsonElement valueElement, string fieldName)
    {
        if (valueElement.ValueKind != JsonValueKind.True && valueElement.ValueKind != JsonValueKind.False)
        {
            throw new ToolInputValidationException($"'{fieldName}' must be a boolean.");
        }

        return valueElement.GetBoolean();
    }

    // Accepts a JSON object and returns its raw JSON text (length-capped). Used
    // for structured arguments like schemaOverride that are forwarded verbatim.
    private static string ValidateObject(JsonElement valueElement, string fieldName, int maxLength)
    {
        if (valueElement.ValueKind != JsonValueKind.Object)
        {
            throw new ToolInputValidationException($"'{fieldName}' must be a JSON object.");
        }

        var raw = valueElement.GetRawText();
        if (raw.Length > maxLength)
        {
            throw new ToolInputValidationException($"'{fieldName}' exceeds the maximum length of {maxLength} characters.");
        }

        return raw;
    }

    private static bool TryGetProperty(JsonElement element, string propertyName, out JsonElement value)
    {
        if (element.ValueKind == JsonValueKind.Object && element.TryGetProperty(propertyName, out value))
        {
            return true;
        }

        value = default;
        return false;
    }

    private static void RejectUnknownProperties(JsonElement element, IEnumerable<string> allowedProperties, string scope)
    {
        if (element.ValueKind != JsonValueKind.Object)
        {
            return;
        }

        var allowed = new HashSet<string>(allowedProperties, StringComparer.Ordinal);
        foreach (var property in element.EnumerateObject())
        {
            if (!allowed.Contains(property.Name))
            {
                throw new ToolInputValidationException($"Unknown property '{property.Name}' in {scope}.");
            }
        }
    }

    private sealed record ToolSchema(IReadOnlyDictionary<string, ToolArgumentSchema> Arguments);

    private enum ArgKind { String, Integer, Number, Boolean, Object }

    private sealed record ToolArgumentSchema(ArgKind Kind, bool Required, int MaxLength = 0, double MinValue = 0, double MaxValue = 0)
    {
        public static ToolArgumentSchema String(bool required, int maxLength)
            => new(ArgKind.String, required, MaxLength: maxLength);

        public static ToolArgumentSchema Integer(bool required, int minValue, int maxValue)
            => new(ArgKind.Integer, required, MinValue: minValue, MaxValue: maxValue);

        public static ToolArgumentSchema Number(bool required, double minValue, double maxValue)
            => new(ArgKind.Number, required, MinValue: minValue, MaxValue: maxValue);

        public static ToolArgumentSchema Boolean(bool required)
            => new(ArgKind.Boolean, required);

        public static ToolArgumentSchema Object(bool required, int maxLength)
            => new(ArgKind.Object, required, MaxLength: maxLength);
    }
}

public sealed record ToolValidationResult(string ToolName, Dictionary<string, object> Arguments);

public sealed class ToolInputValidationException : Exception
{
    public ToolInputValidationException(string message)
        : base(message)
    {
    }
}