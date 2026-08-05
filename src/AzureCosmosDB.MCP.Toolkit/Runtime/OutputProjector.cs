using System.Text.Json.Nodes;
using AzureCosmosDB.MCP.Toolkit.Configuration;

namespace AzureCosmosDB.MCP.Toolkit.Runtime;

/// <summary>
/// Applies declarative output shaping: projection, renaming, nested output, redaction, and limits.
/// Operates on a single object or an array of objects.
/// </summary>
public static class OutputProjector
{
    public static JsonNode? Apply(JsonNode? result, OutputConfiguration? output)
    {
        if (output is null || result is null)
        {
            return result;
        }

        if (result is JsonArray array)
        {
            var projected = new JsonArray();
            var count = 0;
            foreach (var item in array)
            {
                if (output.MaxItems is int max && count >= max)
                {
                    break;
                }

                projected.Add(ApplyToObject(item, output));
                count++;
            }

            return projected;
        }

        return ApplyToObject(result, output);
    }

    private static JsonNode? ApplyToObject(JsonNode? node, OutputConfiguration output)
    {
        if (node is not JsonObject obj)
        {
            return node?.DeepClone();
        }

        JsonObject shaped;
        if (output.Select is { Count: > 0 } select)
        {
            shaped = new JsonObject();
            foreach (var (outputName, sourcePath) in select)
            {
                var value = ReadPath(obj, sourcePath);
                shaped[outputName] = value?.DeepClone();
            }
        }
        else
        {
            shaped = (JsonObject)obj.DeepClone();
        }

        if (output.Redact is { Count: > 0 } redact)
        {
            foreach (var field in redact)
            {
                RemovePath(shaped, field);
            }
        }

        return shaped;
    }

    private static JsonNode? ReadPath(JsonObject root, string path)
    {
        JsonNode? current = root;
        foreach (var segment in path.Split('.'))
        {
            if (current is JsonObject obj && obj.TryGetPropertyValue(segment, out var next))
            {
                current = next;
            }
            else
            {
                return null;
            }
        }

        return current;
    }

    private static void RemovePath(JsonObject root, string path)
    {
        var segments = path.Split('.');
        JsonObject? current = root;
        for (var i = 0; i < segments.Length - 1 && current is not null; i++)
        {
            current = current.TryGetPropertyValue(segments[i], out var next) ? next as JsonObject : null;
        }

        current?.Remove(segments[^1]);
    }
}
