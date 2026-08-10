using System.Globalization;
using System.Text.Json;
using System.Text.Json.Serialization;

namespace AzureCosmosDB.MCP.Toolkit.Configuration;

/// <summary>
/// Reads string-typed configuration fields (which frequently hold binding templates such as
/// <c>${topK}</c>) even when the underlying YAML scalar was a number or boolean literal
/// (for example <c>topK: 5</c>). This keeps authoring natural while the model stays strongly typed.
/// </summary>
public sealed class FlexibleStringConverter : JsonConverter<string>
{
    public override string? Read(ref Utf8JsonReader reader, Type typeToConvert, JsonSerializerOptions options)
        => reader.TokenType switch
        {
            JsonTokenType.String => reader.GetString(),
            JsonTokenType.Number => reader.TryGetInt64(out var l)
                ? l.ToString(CultureInfo.InvariantCulture)
                : reader.GetDouble().ToString(CultureInfo.InvariantCulture),
            JsonTokenType.True => "true",
            JsonTokenType.False => "false",
            JsonTokenType.Null => null,
            _ => throw new JsonException($"Cannot convert {reader.TokenType} to string."),
        };

    public override void Write(Utf8JsonWriter writer, string value, JsonSerializerOptions options)
        => writer.WriteStringValue(value);
}
