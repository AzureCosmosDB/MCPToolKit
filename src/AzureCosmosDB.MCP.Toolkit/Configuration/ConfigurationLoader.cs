using System.Text.Json;

namespace AzureCosmosDB.MCP.Toolkit.Configuration;

/// <summary>Outcome of loading and validating a declarative configuration document.</summary>
public sealed class ConfigurationLoadResult
{
    public ToolkitConfiguration? Configuration { get; init; }
    public IReadOnlyList<string> Errors { get; init; } = Array.Empty<string>();
    public IReadOnlyList<string> Warnings { get; init; } = Array.Empty<string>();
    public bool IsValid => Errors.Count == 0 && Configuration is not null;
}

/// <summary>
/// Loads the additive declarative configuration from YAML or JSON text.
/// Fails closed: any parse or validation error yields an invalid result with diagnostics.
/// </summary>
public sealed class ConfigurationLoader
{
    private static readonly JsonSerializerOptions JsonOptions = new()
    {
        PropertyNameCaseInsensitive = true,
        ReadCommentHandling = JsonCommentHandling.Skip,
        AllowTrailingCommas = true,
        NumberHandling = System.Text.Json.Serialization.JsonNumberHandling.AllowReadingFromString,
        Converters = { new FlexibleBooleanConverter() },
    };

    private readonly IReadOnlyDictionary<string, string?> _environment;

    public ConfigurationLoader(IReadOnlyDictionary<string, string?>? environment = null)
    {
        _environment = environment ?? EnvironmentSubstitution.CurrentEnvironment();
    }

    /// <summary>Load configuration from a file path (format inferred from extension/content).</summary>
    public ConfigurationLoadResult LoadFromFile(string path)
    {
        if (!File.Exists(path))
        {
            return new ConfigurationLoadResult { Errors = new[] { $"Configuration file not found: {path}" } };
        }

        var isJson = path.EndsWith(".json", StringComparison.OrdinalIgnoreCase);
        string text;
        try
        {
            text = File.ReadAllText(path);
        }
        catch (Exception ex)
        {
            return new ConfigurationLoadResult { Errors = new[] { $"Failed to read configuration file '{path}': {ex.Message}" } };
        }

        return LoadFromText(text, isJson);
    }

    /// <summary>Load configuration from raw text. When <paramref name="isJson"/> is null the format is auto-detected.</summary>
    public ConfigurationLoadResult LoadFromText(string text, bool? isJson = null)
    {
        if (string.IsNullOrWhiteSpace(text))
        {
            return new ConfigurationLoadResult { Errors = new[] { "Configuration document is empty." } };
        }

        var substitutionErrors = new List<string>();
        var substituted = EnvironmentSubstitution.Apply(text, _environment, substitutionErrors);
        if (substitutionErrors.Count > 0)
        {
            return new ConfigurationLoadResult { Errors = substitutionErrors };
        }

        var treatAsJson = isJson ?? substituted.TrimStart().StartsWith('{');

        string json;
        if (treatAsJson)
        {
            json = substituted;
        }
        else
        {
            try
            {
                var node = YamlToJsonConverter.Parse(substituted);
                json = node?.ToJsonString() ?? "null";
            }
            catch (Exception ex)
            {
                return new ConfigurationLoadResult { Errors = new[] { $"YAML parse error: {ex.Message}" } };
            }
        }

        ToolkitConfiguration? config;
        try
        {
            config = JsonSerializer.Deserialize<ToolkitConfiguration>(json, JsonOptions);
        }
        catch (Exception ex)
        {
            return new ConfigurationLoadResult { Errors = new[] { $"Configuration deserialization error: {ex.Message}" } };
        }

        if (config is null)
        {
            return new ConfigurationLoadResult { Errors = new[] { "Configuration document produced no content." } };
        }

        var validation = ConfigurationValidator.Validate(config);
        return new ConfigurationLoadResult
        {
            Configuration = validation.Errors.Count == 0 ? config : null,
            Errors = validation.Errors,
            Warnings = validation.Warnings,
        };
    }
}
