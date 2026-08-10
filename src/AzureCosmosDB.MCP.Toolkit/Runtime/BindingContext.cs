using System.Globalization;
using System.Text;
using System.Text.Json;
using System.Text.Json.Nodes;
using System.Text.RegularExpressions;

namespace AzureCosmosDB.MCP.Toolkit.Runtime;

/// <summary>
/// Resolves runtime <c>${...}</c> binding tokens against validated input, generated identifiers,
/// system values, and prior step outputs.
/// </summary>
/// <remarks>
/// Bound values are always produced as typed <see cref="JsonNode"/> values that are passed to
/// Cosmos DB as query <em>parameters</em>, ids, or partition keys — never concatenated into SQL text.
/// This is the core of the toolkit's injection resistance.
/// </remarks>
public sealed partial class BindingContext
{
    [GeneratedRegex(@"\$\{([A-Za-z_][A-Za-z0-9_.\[\]]*)\}")]
    private static partial Regex TokenRegex();

    private readonly IReadOnlyDictionary<string, JsonNode?> _input;
    private readonly Dictionary<string, string> _generated = new(StringComparer.Ordinal);
    private readonly Dictionary<string, JsonNode?> _steps = new(StringComparer.Ordinal);
    private readonly string _utcNow;

    public BindingContext(IReadOnlyDictionary<string, JsonNode?> input, DateTimeOffset? now = null)
    {
        _input = input;
        _utcNow = (now ?? DateTimeOffset.UtcNow).UtcDateTime.ToString("yyyy-MM-ddTHH:mm:ss.fffffffZ", CultureInfo.InvariantCulture);
    }

    /// <summary>Records the output of a named step for later <c>${steps.id.path}</c> references.</summary>
    public void SetStepOutput(string stepId, JsonNode? output) => _steps[stepId] = output;

    /// <summary>Gets (or lazily creates) a stable generated identifier for the current invocation.</summary>
    public string GetGenerated(string key)
    {
        if (!_generated.TryGetValue(key, out var value))
        {
            value = Guid.NewGuid().ToString();
            _generated[key] = value;
        }

        return value;
    }

    /// <summary>Binds an arbitrary configuration value (string/number/object/array) into a resolved node.</summary>
    public JsonNode? Bind(object? configValue)
    {
        var node = configValue switch
        {
            null => null,
            JsonNode n => n.DeepClone(),
            JsonElement e => JsonSerializer.SerializeToNode(e),
            _ => JsonSerializer.SerializeToNode(configValue),
        };

        return BindNode(node);
    }

    /// <summary>Binds a single template string, preserving type when it is exactly one token.</summary>
    public JsonNode? BindTemplate(string? template)
    {
        if (template is null)
        {
            return null;
        }

        var wholeMatch = TokenRegex().Match(template);
        if (wholeMatch.Success && wholeMatch.Value.Length == template.Length)
        {
            return Resolve(wholeMatch.Groups[1].Value, out var found)
                ?? (found ? null : JsonValue.Create(template));
        }

        var sb = new StringBuilder();
        var last = 0;
        foreach (Match m in TokenRegex().Matches(template))
        {
            sb.Append(template, last, m.Index - last);
            var resolved = Resolve(m.Groups[1].Value, out _);
            sb.Append(Stringify(resolved));
            last = m.Index + m.Length;
        }

        sb.Append(template, last, template.Length - last);
        return JsonValue.Create(sb.ToString());
    }

    /// <summary>Convenience helper for tokens that must resolve to a string (ids, partition keys).</summary>
    public string? BindToString(string? template)
    {
        var node = BindTemplate(template);
        return node is null ? null : Stringify(node);
    }

    private JsonNode? BindNode(JsonNode? node)
    {
        switch (node)
        {
            case null:
                return null;
            case JsonValue value when value.TryGetValue<string>(out var s) && s is not null:
                return BindTemplate(s);
            case JsonObject obj:
                var newObj = new JsonObject();
                foreach (var (key, child) in obj)
                {
                    newObj[key] = BindNode(child);
                }

                return newObj;
            case JsonArray arr:
                var newArr = new JsonArray();
                foreach (var child in arr)
                {
                    newArr.Add(BindNode(child));
                }

                return newArr;
            default:
                return node.DeepClone();
        }
    }

    private JsonNode? Resolve(string path, out bool found)
    {
        found = true;
        var segments = path.Split('.');
        var head = segments[0];

        switch (head)
        {
            case "system":
                if (segments.Length == 2 && segments[1] is "utcNow" or "utcnow")
                {
                    return JsonValue.Create(_utcNow);
                }

                found = false;
                return null;

            case "generated":
                if (segments.Length == 2)
                {
                    return JsonValue.Create(GetGenerated(segments[1]));
                }

                found = false;
                return null;

            case "input":
                return Navigate(ToObject(_input), segments.Skip(1), out found);

            case "steps":
                if (segments.Length >= 2 && _steps.TryGetValue(segments[1], out var stepNode))
                {
                    return Navigate(stepNode, segments.Skip(2), out found);
                }

                found = false;
                return null;

            default:
                // Bare token: look up directly in input.
                return Navigate(ToObject(_input), segments, out found);
        }
    }

    private static JsonObject ToObject(IReadOnlyDictionary<string, JsonNode?> input)
    {
        var obj = new JsonObject();
        foreach (var (key, value) in input)
        {
            obj[key] = value?.DeepClone();
        }

        return obj;
    }

    private static JsonNode? Navigate(JsonNode? node, IEnumerable<string> segments, out bool found)
    {
        found = true;
        var current = node;
        foreach (var segment in segments)
        {
            if (current is JsonObject obj && obj.TryGetPropertyValue(segment, out var next))
            {
                current = next;
            }
            else
            {
                found = false;
                return null;
            }
        }

        return current?.DeepClone();
    }

    private static string Stringify(JsonNode? node)
    {
        if (node is null)
        {
            return string.Empty;
        }

        if (node is JsonValue value)
        {
            if (value.TryGetValue<string>(out var s) && s is not null)
            {
                return s;
            }

            return value.ToJsonString();
        }

        return node.ToJsonString();
    }
}
