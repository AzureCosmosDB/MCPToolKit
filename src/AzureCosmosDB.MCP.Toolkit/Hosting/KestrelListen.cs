namespace AzureCosmosDB.MCP.Toolkit.Hosting;

/// <summary>
/// Helpers for Kestrel listen configuration so ASPNETCORE_URLS is honored when set
/// (Container Apps / Docker set http://+:8080; local orchestrators may use 127.0.0.1 and a custom port).
/// </summary>
public static class KestrelListen
{
    /// <summary>
    /// When true, Program should not call <c>ListenAnyIP(8080)</c> so the host uses ASPNETCORE_URLS.
    /// </summary>
    public static bool ShouldUseAspNetCoreUrls(string? aspNetCoreUrls)
        => !string.IsNullOrWhiteSpace(aspNetCoreUrls);
}
