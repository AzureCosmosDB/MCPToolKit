using System.Text.Json;
using System.Text.Json.Serialization;

namespace AzureCosmosDB.MCP.Toolkit.Configuration;

/// <summary>
/// Reads booleans that may arrive as real JSON booleans or as quoted strings.
/// Required because the YAML→JSON bridge emits all scalars as strings.
/// </summary>
public sealed class FlexibleBooleanConverter : JsonConverter<bool>
{
    public override bool Read(ref Utf8JsonReader reader, Type typeToConvert, JsonSerializerOptions options)
        => reader.TokenType switch
        {
            JsonTokenType.True => true,
            JsonTokenType.False => false,
            JsonTokenType.String => bool.Parse(reader.GetString()!),
            JsonTokenType.Number => reader.GetInt32() != 0,
            _ => throw new JsonException($"Cannot convert {reader.TokenType} to boolean."),
        };

    public override void Write(Utf8JsonWriter writer, bool value, JsonSerializerOptions options)
        => writer.WriteBooleanValue(value);
}
