using System.Text.RegularExpressions;

namespace AzureCosmosDB.MCP.Toolkit.Configuration;

/// <summary>
/// Resolves <c>${VAR}</c> and <c>${env:VAR}</c> tokens against environment variables.
/// </summary>
/// <remarks>
/// Two forms are supported:
/// <list type="bullet">
/// <item><c>${env:NAME}</c> — always an environment reference; missing values are reported as errors.</item>
/// <item><c>${NAME}</c> — substituted only when an environment variable <c>NAME</c> exists.
/// Otherwise the token is left intact so it can be used as a runtime parameter binding
/// (for example <c>${accountId}</c>).</item>
/// </list>
/// This keeps environment substitution (load time) and parameter binding (invocation time)
/// unambiguous while matching the documented specification examples.
/// </remarks>
public static partial class EnvironmentSubstitution
{
    [GeneratedRegex(@"\$\{(env:)?([A-Za-z_][A-Za-z0-9_]*)\}")]
    private static partial Regex TokenRegex();

    public static string Apply(string input, IReadOnlyDictionary<string, string?> environment, IList<string> errors)
    {
        ArgumentNullException.ThrowIfNull(input);

        return TokenRegex().Replace(input, match =>
        {
            var explicitEnv = match.Groups[1].Success;
            var name = match.Groups[2].Value;
            var hasValue = environment.TryGetValue(name, out var value) && value is not null;

            if (hasValue)
            {
                return value!;
            }

            if (explicitEnv)
            {
                errors.Add($"Environment variable '{name}' referenced by '${{env:{name}}}' is not set.");
                return match.Value;
            }

            // Bare token with no matching environment variable: preserve as a runtime binding.
            return match.Value;
        });
    }

    public static IReadOnlyDictionary<string, string?> CurrentEnvironment()
    {
        var result = new Dictionary<string, string?>(StringComparer.Ordinal);
        foreach (System.Collections.DictionaryEntry entry in Environment.GetEnvironmentVariables())
        {
            result[entry.Key.ToString()!] = entry.Value?.ToString();
        }

        return result;
    }
}
