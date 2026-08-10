using System.Security.Claims;
using System.Text.Json.Nodes;
using AzureCosmosDB.MCP.Toolkit.Configuration;

namespace AzureCosmosDB.MCP.Toolkit.Runtime;

/// <summary>Identity facts about the caller, sourced from validated claims (never from the model).</summary>
public sealed class CallerContext
{
    public bool IsAuthenticated { get; init; }
    public bool AuthenticationBypassed { get; init; }
    public IReadOnlyCollection<string> Scopes { get; init; } = Array.Empty<string>();
    public IReadOnlyCollection<string> Roles { get; init; } = Array.Empty<string>();
    public IReadOnlyDictionary<string, string> Claims { get; init; } = new Dictionary<string, string>(StringComparer.Ordinal);

    public string? GetClaim(string type) => Claims.TryGetValue(type, out var value) ? value : null;

    public static CallerContext FromPrincipal(ClaimsPrincipal? principal, bool authenticationBypassed)
    {
        if (principal is null)
        {
            return new CallerContext { AuthenticationBypassed = authenticationBypassed };
        }

        var scopes = new HashSet<string>(StringComparer.Ordinal);
        foreach (var claim in principal.FindAll("scp").Concat(principal.FindAll("http://schemas.microsoft.com/identity/claims/scope")))
        {
            foreach (var scope in claim.Value.Split(' ', StringSplitOptions.RemoveEmptyEntries | StringSplitOptions.TrimEntries))
            {
                scopes.Add(scope);
            }
        }

        var roles = new HashSet<string>(StringComparer.Ordinal);
        foreach (var claim in principal.FindAll("roles").Concat(principal.FindAll(ClaimTypes.Role)))
        {
            roles.Add(claim.Value);
        }

        var claims = new Dictionary<string, string>(StringComparer.Ordinal);
        foreach (var claim in principal.Claims)
        {
            claims[claim.Type] = claim.Value;
        }

        return new CallerContext
        {
            IsAuthenticated = principal.Identity?.IsAuthenticated ?? false,
            AuthenticationBypassed = authenticationBypassed,
            Scopes = scopes,
            Roles = roles,
            Claims = claims,
        };
    }
}

/// <summary>Result of an authorization decision.</summary>
public sealed record AuthorizationResult(bool Allowed, string? Error)
{
    public static readonly AuthorizationResult Success = new(true, null);

    public static AuthorizationResult Deny(string error) => new(false, error);
}

/// <summary>
/// Evaluates per-tool authorization: scopes, roles, claim rules, and tenant/partition isolation.
/// Tenant identity is always taken from validated claims and enforced against caller-supplied
/// input, so a model cannot spoof another tenant.
/// </summary>
public static class AuthorizationEvaluator
{
    public static AuthorizationResult Authorize(
        AuthorizationConfiguration? authorization,
        CallerContext caller,
        IReadOnlyDictionary<string, JsonNode?> input)
    {
        if (authorization is null)
        {
            return AuthorizationResult.Success;
        }

        if (caller.AuthenticationBypassed)
        {
            // Local development bypass mirrors the server's existing DEV_BYPASS_AUTH behavior.
            return AuthorizationResult.Success;
        }

        var requiresIdentity = authorization.RequiredScopes is { Count: > 0 }
            || authorization.RequiredRoles is { Count: > 0 }
            || authorization.Claims is { Count: > 0 }
            || !string.IsNullOrWhiteSpace(authorization.TenantClaim)
            || authorization.PartitionKeyFromClaim is { Count: > 0 };

        if (requiresIdentity && !caller.IsAuthenticated)
        {
            return AuthorizationResult.Deny("Authentication is required to invoke this tool.");
        }

        if (authorization.RequiredScopes is { Count: > 0 } scopes)
        {
            var missing = scopes.Where(s => !caller.Scopes.Contains(s)).ToList();
            if (missing.Count > 0)
            {
                return AuthorizationResult.Deny($"Missing required scope(s): {string.Join(", ", missing)}.");
            }
        }

        if (authorization.RequiredRoles is { Count: > 0 } roles)
        {
            var missing = roles.Where(r => !caller.Roles.Contains(r)).ToList();
            if (missing.Count > 0)
            {
                return AuthorizationResult.Deny($"Missing required role(s): {string.Join(", ", missing)}.");
            }
        }

        if (authorization.Claims is { Count: > 0 } claimRules)
        {
            foreach (var (type, expected) in claimRules)
            {
                if (!string.Equals(caller.GetClaim(type), expected, StringComparison.Ordinal))
                {
                    return AuthorizationResult.Deny($"Claim '{type}' does not satisfy the required policy.");
                }
            }
        }

        if (!string.IsNullOrWhiteSpace(authorization.TenantClaim) && !string.IsNullOrWhiteSpace(authorization.TenantField))
        {
            var tenant = caller.GetClaim(authorization.TenantClaim!);
            if (string.IsNullOrEmpty(tenant))
            {
                return AuthorizationResult.Deny($"Tenant claim '{authorization.TenantClaim}' is missing.");
            }

            var supplied = ReadString(input, authorization.TenantField!);
            if (supplied is not null && !string.Equals(supplied, tenant, StringComparison.Ordinal))
            {
                return AuthorizationResult.Deny("Tenant isolation violation: supplied tenant does not match the caller identity.");
            }
        }

        if (authorization.PartitionKeyFromClaim is { Count: > 0 } pkRules)
        {
            foreach (var (inputName, claimType) in pkRules)
            {
                var claimValue = caller.GetClaim(claimType);
                if (string.IsNullOrEmpty(claimValue))
                {
                    return AuthorizationResult.Deny($"Required identity claim '{claimType}' is missing.");
                }

                var supplied = ReadString(input, inputName);
                if (supplied is not null && !string.Equals(supplied, claimValue, StringComparison.Ordinal))
                {
                    return AuthorizationResult.Deny($"Partition restriction violation for '{inputName}'.");
                }
            }
        }

        return AuthorizationResult.Success;
    }

    /// <summary>
    /// Overlays identity-derived values onto the input so downstream binding always uses the trusted
    /// tenant/partition value regardless of what the model supplied.
    /// </summary>
    public static Dictionary<string, JsonNode?> ApplyIdentityDerivedInputs(
        AuthorizationConfiguration? authorization,
        CallerContext caller,
        IReadOnlyDictionary<string, JsonNode?> input)
    {
        var result = new Dictionary<string, JsonNode?>(input, StringComparer.Ordinal);
        if (authorization is null || caller.AuthenticationBypassed || !caller.IsAuthenticated)
        {
            return result;
        }

        if (!string.IsNullOrWhiteSpace(authorization.TenantClaim) && !string.IsNullOrWhiteSpace(authorization.TenantField))
        {
            var tenant = caller.GetClaim(authorization.TenantClaim!);
            if (!string.IsNullOrEmpty(tenant))
            {
                result[authorization.TenantField!] = JsonValue.Create(tenant);
            }
        }

        if (authorization.PartitionKeyFromClaim is { Count: > 0 } pkRules)
        {
            foreach (var (inputName, claimType) in pkRules)
            {
                var claimValue = caller.GetClaim(claimType);
                if (!string.IsNullOrEmpty(claimValue))
                {
                    result[inputName] = JsonValue.Create(claimValue);
                }
            }
        }

        return result;
    }

    private static string? ReadString(IReadOnlyDictionary<string, JsonNode?> input, string name)
    {
        if (input.TryGetValue(name, out var node) && node is JsonValue value && value.TryGetValue<string>(out var s))
        {
            return s;
        }

        return null;
    }
}
