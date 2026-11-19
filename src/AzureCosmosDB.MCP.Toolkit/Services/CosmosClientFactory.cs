using System.Net;
using Azure.Identity;
using Microsoft.Azure.Cosmos;

namespace AzureCosmosDB.MCP.Toolkit.Services;

/// <summary>
/// How Gateway-mode Cosmos HTTPS is dialed through an outbound proxy.
/// </summary>
public enum CosmosProxyTransport
{
    /// <summary>SOCKS5 CONNECT (e.g. Bastion local tunnel).</summary>
    Socks5,
    /// <summary>HTTP CONNECT via <see cref="WebProxy"/> (HTTP_PROXY / HTTPS_PROXY).</summary>
    HttpConnect
}

/// <summary>
/// Resolved outbound proxy for Cosmos Gateway traffic.
/// </summary>
public sealed record CosmosProxyConfig(
    CosmosProxyTransport Transport,
    string Url,
    string Source);

/// <summary>
/// Factory for creating CosmosClient instances with support for both Azure credentials and connection strings.
/// Optional Gateway proxy: SOCKS5 (Bastion) or HTTP CONNECT (HTTP_PROXY / HTTPS_PROXY / ALL_PROXY).
/// </summary>
public static class CosmosClientFactory
{
    private static CosmosClientOptions BuildClientOptions(
        IConfiguration configuration,
        ILogger logger,
        bool useGatewayMode,
        CosmosProxyConfig? proxy)
    {
        var options = new CosmosClientOptions
        {
            ApplicationName = "AzureCosmosDBMCP",
            EnableContentResponseOnWrite = false,
            RequestTimeout = TimeSpan.FromSeconds(60)
        };

        if (useGatewayMode)
        {
            // Emulator/local and proxy paths use HTTPS gateway (port 443).
            options.ConnectionMode = ConnectionMode.Gateway;
        }
        else if (proxy is not null)
        {
            // Direct mode opens replica TCP ports and cannot use an HTTP/SOCKS proxy — fail closed.
            throw new InvalidOperationException(
                "An outbound proxy (COSMOS_SOCKS5_PROXY, ALL_PROXY, HTTPS_PROXY, or HTTP_PROXY) requires Gateway connection mode. " +
                "Set COSMOS_CONNECTION_MODE=Gateway or omit Direct. " +
                "See https://github.com/AzureCosmosDB/MCPToolKit/issues/152");
        }

        string? socksHost = null;
        var socksPort = 0;
        Uri? httpProxyUri = null;

        if (proxy is { Transport: CosmosProxyTransport.Socks5 })
        {
            if (!Socks5Connect.TryParseProxyUrl(proxy.Url, out socksHost!, out socksPort, out var parseError))
            {
                throw new InvalidOperationException(parseError ?? $"Invalid SOCKS5 proxy URL from {proxy.Source}.");
            }
            logger.LogInformation(
                "Cosmos Gateway traffic will dial via SOCKS5 proxy {ProxyHost}:{ProxyPort} (from {ProxySource})",
                socksHost, socksPort, proxy.Source);
        }
        else if (proxy is { Transport: CosmosProxyTransport.HttpConnect })
        {
            if (!Uri.TryCreate(proxy.Url, UriKind.Absolute, out httpProxyUri)
                || (httpProxyUri.Scheme != Uri.UriSchemeHttp && httpProxyUri.Scheme != Uri.UriSchemeHttps))
            {
                throw new InvalidOperationException(
                    $"Invalid HTTP proxy URL from {proxy.Source}: '{proxy.Url}'. Use http://host:port or https://host:port.");
            }
            logger.LogInformation(
                "Cosmos Gateway traffic will dial via HTTP CONNECT proxy {ProxyUri} (from {ProxySource})",
                httpProxyUri, proxy.Source);
        }

        var sslVerifySetting = configuration["COSMOS_EMULATOR_SSL_VERIFY"]
            ?? Environment.GetEnvironmentVariable("COSMOS_EMULATOR_SSL_VERIFY");
        var disableSslVerify = !string.IsNullOrWhiteSpace(sslVerifySetting)
            && bool.TryParse(sslVerifySetting, out var sslVerify)
            && !sslVerify;

        if (disableSslVerify)
        {
            logger.LogWarning("COSMOS_EMULATOR_SSL_VERIFY=false detected. TLS certificate validation is disabled for Cosmos DB emulator connections.");
        }

        if (socksHost is not null || httpProxyUri is not null || disableSslVerify)
        {
            var proxyHost = socksHost;
            var proxyPort = socksPort;
            var webProxy = httpProxyUri is null ? null : new WebProxy(httpProxyUri);
            options.HttpClientFactory = () =>
            {
                if (proxyHost is not null)
                {
                    var handler = new SocketsHttpHandler
                    {
                        ConnectCallback = async (context, cancellationToken) =>
                        {
                            var ep = context.DnsEndPoint;
                            return await Socks5Connect.ConnectAsync(
                                proxyHost, proxyPort, ep.Host, ep.Port, cancellationToken).ConfigureAwait(false);
                        }
                    };
                    if (disableSslVerify)
                    {
                        handler.SslOptions.RemoteCertificateValidationCallback = static (_, _, _, _) => true;
                    }
                    return new HttpClient(handler);
                }

                if (webProxy is not null)
                {
                    var handler = new SocketsHttpHandler
                    {
                        Proxy = webProxy,
                        UseProxy = true
                    };
                    if (disableSslVerify)
                    {
                        handler.SslOptions.RemoteCertificateValidationCallback = static (_, _, _, _) => true;
                    }
                    return new HttpClient(handler);
                }

                return new HttpClient(new HttpClientHandler
                {
                    ServerCertificateCustomValidationCallback = HttpClientHandler.DangerousAcceptAnyServerCertificateValidator
                });
            };
        }

        return options;
    }

    /// <summary>
    /// Create a CosmosClient with fallback support for connection strings and Azure credentials.
    ///
    /// Priority order:
    /// 1. COSMOS_CONNECTION_STRING - for emulator or local development
    /// 2. COSMOS_ENDPOINT with DefaultAzureCredential - for cloud production
    ///
    /// Optional Gateway proxy (any configured proxy forces Gateway):
    /// - COSMOS_SOCKS5_PROXY / socks5 ALL_PROXY → SOCKS5
    /// - HTTPS_PROXY / HTTP_PROXY / http(s) ALL_PROXY → HTTP CONNECT
    /// - Optional COSMOS_CONNECTION_MODE=Gateway|Direct
    /// </summary>
    public static CosmosClient CreateCosmosClient(IConfiguration configuration, ILogger logger)
    {
        var proxy = ResolveProxy(configuration);
        var connectionMode = ResolveConnectionMode(configuration, proxy);

        // Check for connection string first (emulator/local development)
        var connectionString = configuration["COSMOS_CONNECTION_STRING"]
            ?? Environment.GetEnvironmentVariable("COSMOS_CONNECTION_STRING");

        if (!string.IsNullOrWhiteSpace(connectionString))
        {
            logger.LogInformation("Creating CosmosClient using connection string (emulator/local mode)");
            return new CosmosClient(
                connectionString,
                BuildClientOptions(configuration, logger, useGatewayMode: true, proxy));
        }

        // Fall back to Azure credentials for cloud production
        var endpoint = configuration["COSMOS_ENDPOINT"]
            ?? Environment.GetEnvironmentVariable("COSMOS_ENDPOINT");

        if (string.IsNullOrWhiteSpace(endpoint))
        {
            throw new InvalidOperationException(
                "Either COSMOS_ENDPOINT or COSMOS_CONNECTION_STRING environment variable must be set. " +
                "For emulator/local development, use COSMOS_CONNECTION_STRING. " +
                "For cloud production, use COSMOS_ENDPOINT with Azure credentials.");
        }

        var useGateway = connectionMode != ConnectionMode.Direct;
        logger.LogInformation(
            "Creating CosmosClient using Azure credentials (cloud mode, ConnectionMode={Mode})",
            useGateway ? "Gateway" : "Direct");
        var credential = new DefaultAzureCredential();

        return new CosmosClient(
            endpoint,
            credential,
            BuildClientOptions(configuration, logger, useGatewayMode: useGateway, proxy));
    }

    /// <summary>
    /// Resolves an outbound proxy for Gateway Cosmos traffic.
    /// Precedence: COSMOS_SOCKS5_PROXY → ALL_PROXY → HTTPS_PROXY → HTTP_PROXY.
    /// </summary>
    public static CosmosProxyConfig? ResolveProxy(IConfiguration configuration)
    {
        foreach (var (source, value) in EnumerateProxyCandidates(configuration))
        {
            if (string.IsNullOrWhiteSpace(value))
            {
                continue;
            }

            var trimmed = value.Trim();
            if (!TryClassifyProxyUrl(trimmed, allowBareHostPort: source == "COSMOS_SOCKS5_PROXY",
                    out var transport, out var error))
            {
                if (source is "ALL_PROXY" or "all_proxy")
                {
                    // ALL_PROXY may be set for other tools with an unsupported scheme — skip, don't fail.
                    continue;
                }

                throw new InvalidOperationException(error ?? $"Invalid proxy URL from {source}: '{trimmed}'.");
            }

            return new CosmosProxyConfig(transport, trimmed, source);
        }

        return null;
    }

    /// <summary>
    /// Back-compat helper: returns a SOCKS5 URL when <see cref="ResolveProxy"/> selects SOCKS5; otherwise null.
    /// </summary>
    public static string? ResolveSocks5Proxy(IConfiguration configuration)
    {
        var proxy = ResolveProxy(configuration);
        return proxy is { Transport: CosmosProxyTransport.Socks5 } ? proxy.Url : null;
    }

    private static IEnumerable<(string Source, string? Value)> EnumerateProxyCandidates(IConfiguration configuration)
    {
        yield return ("COSMOS_SOCKS5_PROXY",
            configuration["COSMOS_SOCKS5_PROXY"] ?? Environment.GetEnvironmentVariable("COSMOS_SOCKS5_PROXY"));
        yield return ("ALL_PROXY",
            configuration["ALL_PROXY"]
            ?? Environment.GetEnvironmentVariable("ALL_PROXY")
            ?? Environment.GetEnvironmentVariable("all_proxy"));
        yield return ("HTTPS_PROXY",
            configuration["HTTPS_PROXY"]
            ?? Environment.GetEnvironmentVariable("HTTPS_PROXY")
            ?? Environment.GetEnvironmentVariable("https_proxy"));
        yield return ("HTTP_PROXY",
            configuration["HTTP_PROXY"]
            ?? Environment.GetEnvironmentVariable("HTTP_PROXY")
            ?? Environment.GetEnvironmentVariable("http_proxy"));
    }

    /// <summary>
    /// Classifies a proxy URL as SOCKS5 or HTTP CONNECT.
    /// Bare host:port is allowed only for COSMOS_SOCKS5_PROXY (treated as socks5).
    /// </summary>
    public static bool TryClassifyProxyUrl(
        string raw,
        bool allowBareHostPort,
        out CosmosProxyTransport transport,
        out string? error)
    {
        transport = default;
        error = null;
        if (string.IsNullOrWhiteSpace(raw))
        {
            return false;
        }

        var value = raw.Trim();
        if (value.StartsWith("socks5://", StringComparison.OrdinalIgnoreCase)
            || value.StartsWith("socks5h://", StringComparison.OrdinalIgnoreCase))
        {
            if (!Socks5Connect.TryParseProxyUrl(value, out _, out _, out error))
            {
                return false;
            }
            transport = CosmosProxyTransport.Socks5;
            return true;
        }

        if (value.StartsWith("http://", StringComparison.OrdinalIgnoreCase)
            || value.StartsWith("https://", StringComparison.OrdinalIgnoreCase))
        {
            if (!Uri.TryCreate(value, UriKind.Absolute, out var uri)
                || string.IsNullOrWhiteSpace(uri.Host)
                || uri.Port is < 1 or > 65535)
            {
                error = $"Invalid HTTP proxy URL '{raw}'.";
                return false;
            }
            transport = CosmosProxyTransport.HttpConnect;
            return true;
        }

        if (value.Contains("://", StringComparison.Ordinal))
        {
            error = $"Unsupported proxy scheme in '{raw}'. Use socks5://, http://, or https://.";
            return false;
        }

        if (allowBareHostPort && Socks5Connect.TryParseProxyUrl(value, out _, out _, out error))
        {
            transport = CosmosProxyTransport.Socks5;
            return true;
        }

        error = $"Proxy URL '{raw}' must include a scheme (socks5://, http://, or https://).";
        return false;
    }

    /// <summary>
    /// Default: Direct for cloud (historical). Any outbound proxy or explicit Gateway forces Gateway.
    /// </summary>
    public static ConnectionMode ResolveConnectionMode(IConfiguration configuration, CosmosProxyConfig? proxy)
    {
        var raw = configuration["COSMOS_CONNECTION_MODE"]
            ?? Environment.GetEnvironmentVariable("COSMOS_CONNECTION_MODE");

        if (proxy is not null)
        {
            if (!string.IsNullOrWhiteSpace(raw)
                && raw.Equals("Direct", StringComparison.OrdinalIgnoreCase))
            {
                throw new InvalidOperationException(
                    "COSMOS_CONNECTION_MODE=Direct is incompatible with an outbound proxy " +
                    "(COSMOS_SOCKS5_PROXY, ALL_PROXY, HTTPS_PROXY, or HTTP_PROXY).");
            }
            return ConnectionMode.Gateway;
        }

        if (!string.IsNullOrWhiteSpace(raw))
        {
            if (raw.Equals("Gateway", StringComparison.OrdinalIgnoreCase))
            {
                return ConnectionMode.Gateway;
            }
            if (raw.Equals("Direct", StringComparison.OrdinalIgnoreCase))
            {
                return ConnectionMode.Direct;
            }
            throw new InvalidOperationException(
                $"COSMOS_CONNECTION_MODE must be Gateway or Direct (got '{raw}').");
        }

        return ConnectionMode.Direct;
    }

    /// <summary>Back-compat overload taking a SOCKS URL string.</summary>
    public static ConnectionMode ResolveConnectionMode(IConfiguration configuration, string? socks5Proxy)
    {
        CosmosProxyConfig? proxy = null;
        if (!string.IsNullOrWhiteSpace(socks5Proxy))
        {
            proxy = new CosmosProxyConfig(CosmosProxyTransport.Socks5, socks5Proxy.Trim(), "argument");
        }
        return ResolveConnectionMode(configuration, proxy);
    }
}
