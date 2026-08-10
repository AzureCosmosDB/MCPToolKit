using System.Globalization;
using System.Text.Json.Nodes;
using YamlDotNet.RepresentationModel;

namespace AzureCosmosDB.MCP.Toolkit.Configuration;

/// <summary>
/// Converts a YAML document into a <see cref="JsonNode"/> tree with correct scalar typing.
/// </summary>
/// <remarks>
/// YamlDotNet's built-in JSON-compatible serializer emits every scalar as a quoted string, which
/// loses the integer/number/boolean/null distinction the configuration model relies on. This
/// converter applies the YAML core-schema type inference for <em>plain</em> (unquoted) scalars while
/// preserving explicitly quoted scalars as strings (so <c>version: "1.0"</c> stays a string).
/// </remarks>
public static class YamlToJsonConverter
{
    public static JsonNode? Parse(string yaml)
    {
        using var reader = new StringReader(yaml);
        var stream = new YamlStream();
        stream.Load(reader);

        if (stream.Documents.Count == 0)
        {
            return null;
        }

        return Convert(stream.Documents[0].RootNode);
    }

    private static JsonNode? Convert(YamlNode node)
    {
        return node switch
        {
            YamlMappingNode map => ConvertMapping(map),
            YamlSequenceNode seq => ConvertSequence(seq),
            YamlScalarNode scalar => ConvertScalar(scalar),
            _ => null,
        };
    }

    private static JsonObject ConvertMapping(YamlMappingNode map)
    {
        var obj = new JsonObject();
        foreach (var (key, value) in map.Children)
        {
            var name = ((YamlScalarNode)key).Value ?? string.Empty;
            obj[name] = Convert(value);
        }

        return obj;
    }

    private static JsonArray ConvertSequence(YamlSequenceNode seq)
    {
        var arr = new JsonArray();
        foreach (var item in seq.Children)
        {
            arr.Add(Convert(item));
        }

        return arr;
    }

    private static JsonNode? ConvertScalar(YamlScalarNode scalar)
    {
        var value = scalar.Value;
        if (value is null)
        {
            return null;
        }

        // Explicitly quoted scalars are always strings.
        if (scalar.Style is YamlDotNet.Core.ScalarStyle.SingleQuoted or YamlDotNet.Core.ScalarStyle.DoubleQuoted)
        {
            return JsonValue.Create(value);
        }

        if (value.Length == 0)
        {
            return JsonValue.Create(string.Empty);
        }

        if (value is "null" or "~" or "Null" or "NULL")
        {
            return null;
        }

        if (value is "true" or "True" or "TRUE")
        {
            return JsonValue.Create(true);
        }

        if (value is "false" or "False" or "FALSE")
        {
            return JsonValue.Create(false);
        }

        if (long.TryParse(value, NumberStyles.Integer, CultureInfo.InvariantCulture, out var l))
        {
            return JsonValue.Create(l);
        }

        if (double.TryParse(value, NumberStyles.Float, CultureInfo.InvariantCulture, out var d))
        {
            return JsonValue.Create(d);
        }

        return JsonValue.Create(value);
    }
}
