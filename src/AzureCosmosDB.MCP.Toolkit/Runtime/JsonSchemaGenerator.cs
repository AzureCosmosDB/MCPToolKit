using System.Text.Json;
using System.Text.Json.Nodes;
using AzureCosmosDB.MCP.Toolkit.Configuration;

namespace AzureCosmosDB.MCP.Toolkit.Runtime;

/// <summary>
/// Generates a closed JSON Schema (<c>additionalProperties: false</c>) from a declarative input
/// schema, matching the discovery contract used by the built-in tools.
/// </summary>
public static class JsonSchemaGenerator
{
    public static JsonElement Generate(InputSchemaConfiguration? schema)
    {
        var root = BuildObjectSchema(schema?.Properties, schema?.Required);
        return JsonSerializer.SerializeToElement(root);
    }

    private static JsonObject BuildObjectSchema(Dictionary<string, PropertySchema>? properties, List<string>? required)
    {
        var node = new JsonObject
        {
            ["type"] = "object",
            ["additionalProperties"] = false,
        };

        var props = new JsonObject();
        if (properties is not null)
        {
            foreach (var (name, prop) in properties)
            {
                props[name] = BuildPropertySchema(prop);
            }
        }

        node["properties"] = props;

        if (required is { Count: > 0 })
        {
            var req = new JsonArray();
            foreach (var name in required)
            {
                req.Add(name);
            }

            node["required"] = req;
        }

        return node;
    }

    private static JsonObject BuildPropertySchema(PropertySchema prop)
    {
        var node = new JsonObject { ["type"] = prop.Type };

        if (!string.IsNullOrWhiteSpace(prop.Description))
        {
            node["description"] = prop.Description;
        }

        if (prop.Enum is { Count: > 0 })
        {
            var arr = new JsonArray();
            foreach (var e in prop.Enum)
            {
                arr.Add(JsonSerializer.SerializeToNode(e));
            }

            node["enum"] = arr;
        }

        if (prop.Minimum is double min)
        {
            node["minimum"] = min;
        }

        if (prop.Maximum is double max)
        {
            node["maximum"] = max;
        }

        if (prop.MinLength is int minLen)
        {
            node["minLength"] = minLen;
        }

        if (prop.MaxLength is int maxLen)
        {
            node["maxLength"] = maxLen;
        }

        if (!string.IsNullOrWhiteSpace(prop.Pattern))
        {
            node["pattern"] = prop.Pattern;
        }

        if (prop.MinItems is int minItems)
        {
            node["minItems"] = minItems;
        }

        if (prop.MaxItems is int maxItems)
        {
            node["maxItems"] = maxItems;
        }

        if (string.Equals(prop.Type, "array", StringComparison.OrdinalIgnoreCase) && prop.Items is not null)
        {
            node["items"] = BuildPropertySchema(prop.Items);
        }

        if (string.Equals(prop.Type, "object", StringComparison.OrdinalIgnoreCase))
        {
            node["additionalProperties"] = false;
            if (prop.Properties is not null)
            {
                var nested = new JsonObject();
                foreach (var (name, child) in prop.Properties)
                {
                    nested[name] = BuildPropertySchema(child);
                }

                node["properties"] = nested;
            }
        }

        return node;
    }
}
