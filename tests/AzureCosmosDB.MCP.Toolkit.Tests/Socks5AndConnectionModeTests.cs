using AzureCosmosDB.MCP.Toolkit.Services;
using Microsoft.Azure.Cosmos;
using Microsoft.Extensions.Configuration;
using Xunit;

namespace AzureCosmosDB.MCP.Toolkit.Tests;

public class Socks5AndConnectionModeTests
{
    [Theory]
    [InlineData("socks5://127.0.0.1:51080", "127.0.0.1", 51080)]
    [InlineData("socks5h://localhost:1080", "localhost", 1080)]
    [InlineData("127.0.0.1:51080", "127.0.0.1", 51080)]
    public void TryParseProxyUrl_AcceptsSocks5Forms(string raw, string host, int port)
    {
        Assert.True(Socks5Connect.TryParseProxyUrl(raw, out var h, out var p, out var err), err);
        Assert.Equal(host, h);
        Assert.Equal(port, p);
    }

    [Theory]
    [InlineData("http://127.0.0.1:8080")]
    [InlineData("socks5://host")]
    [InlineData("")]
    public void TryParseProxyUrl_RejectsBadForms(string raw)
    {
        Assert.False(Socks5Connect.TryParseProxyUrl(raw, out _, out _, out _));
    }

    [Theory]
    [InlineData("socks5://127.0.0.1:51080", CosmosProxyTransport.Socks5)]
    [InlineData("socks5h://localhost:1080", CosmosProxyTransport.Socks5)]
    [InlineData("http://proxy.example:3128", CosmosProxyTransport.HttpConnect)]
    [InlineData("https://proxy.example:8443", CosmosProxyTransport.HttpConnect)]
    public void TryClassifyProxyUrl_AcceptsKnownSchemes(string raw, CosmosProxyTransport want)
    {
        Assert.True(CosmosClientFactory.TryClassifyProxyUrl(raw, allowBareHostPort: false, out var got, out var err), err);
        Assert.Equal(want, got);
    }

    [Fact]
    public void TryClassifyProxyUrl_BareHostRequiresAllowFlag()
    {
        Assert.False(CosmosClientFactory.TryClassifyProxyUrl("127.0.0.1:51080", allowBareHostPort: false, out _, out _));
        Assert.True(CosmosClientFactory.TryClassifyProxyUrl("127.0.0.1:51080", allowBareHostPort: true, out var t, out var err), err);
        Assert.Equal(CosmosProxyTransport.Socks5, t);
    }

    [Fact]
    public void ResolveProxy_PrefersExplicitSocksOverAllProxy()
    {
        var config = new ConfigurationBuilder()
            .AddInMemoryCollection(new Dictionary<string, string?>
            {
                ["COSMOS_SOCKS5_PROXY"] = "socks5://127.0.0.1:51080",
                ["ALL_PROXY"] = "http://127.0.0.1:9999",
                ["HTTPS_PROXY"] = "http://127.0.0.1:8888"
            })
            .Build();
        var proxy = CosmosClientFactory.ResolveProxy(config);
        Assert.NotNull(proxy);
        Assert.Equal(CosmosProxyTransport.Socks5, proxy!.Transport);
        Assert.Equal("COSMOS_SOCKS5_PROXY", proxy.Source);
        Assert.Equal("socks5://127.0.0.1:51080", proxy.Url);
    }

    [Fact]
    public void ResolveProxy_UsesHttpsProxyWhenNoSocks()
    {
        var config = new ConfigurationBuilder()
            .AddInMemoryCollection(new Dictionary<string, string?>
            {
                ["HTTPS_PROXY"] = "http://corp-proxy:3128",
                ["HTTP_PROXY"] = "http://corp-proxy:3127"
            })
            .Build();
        var proxy = CosmosClientFactory.ResolveProxy(config);
        Assert.NotNull(proxy);
        Assert.Equal(CosmosProxyTransport.HttpConnect, proxy!.Transport);
        Assert.Equal("HTTPS_PROXY", proxy.Source);
        Assert.Equal("http://corp-proxy:3128", proxy.Url);
    }

    [Fact]
    public void ResolveProxy_AllProxyHttpConnect()
    {
        var config = new ConfigurationBuilder()
            .AddInMemoryCollection(new Dictionary<string, string?>
            {
                ["ALL_PROXY"] = "http://127.0.0.1:8080"
            })
            .Build();
        var proxy = CosmosClientFactory.ResolveProxy(config);
        Assert.NotNull(proxy);
        Assert.Equal(CosmosProxyTransport.HttpConnect, proxy!.Transport);
        Assert.Equal("ALL_PROXY", proxy.Source);
    }

    [Fact]
    public void ResolveSocks5Proxy_PrefersExplicitEnv()
    {
        var config = new ConfigurationBuilder()
            .AddInMemoryCollection(new Dictionary<string, string?>
            {
                ["COSMOS_SOCKS5_PROXY"] = "socks5://127.0.0.1:51080",
                ["ALL_PROXY"] = "socks5://127.0.0.1:9999"
            })
            .Build();
        Assert.Equal("socks5://127.0.0.1:51080", CosmosClientFactory.ResolveSocks5Proxy(config));
    }

    [Fact]
    public void ResolveConnectionMode_SocksForcesGateway()
    {
        var config = new ConfigurationBuilder().Build();
        Assert.Equal(
            ConnectionMode.Gateway,
            CosmosClientFactory.ResolveConnectionMode(config, "socks5://127.0.0.1:51080"));
    }

    [Fact]
    public void ResolveConnectionMode_HttpProxyForcesGateway()
    {
        var config = new ConfigurationBuilder().Build();
        var proxy = new CosmosProxyConfig(CosmosProxyTransport.HttpConnect, "http://proxy:3128", "HTTPS_PROXY");
        Assert.Equal(ConnectionMode.Gateway, CosmosClientFactory.ResolveConnectionMode(config, proxy));
    }

    [Fact]
    public void ResolveConnectionMode_DirectWithSocksThrows()
    {
        var config = new ConfigurationBuilder()
            .AddInMemoryCollection(new Dictionary<string, string?>
            {
                ["COSMOS_CONNECTION_MODE"] = "Direct"
            })
            .Build();
        Assert.Throws<InvalidOperationException>(() =>
            CosmosClientFactory.ResolveConnectionMode(config, "socks5://127.0.0.1:51080"));
    }

    [Fact]
    public void ResolveConnectionMode_DirectWithHttpProxyThrows()
    {
        var config = new ConfigurationBuilder()
            .AddInMemoryCollection(new Dictionary<string, string?>
            {
                ["COSMOS_CONNECTION_MODE"] = "Direct"
            })
            .Build();
        var proxy = new CosmosProxyConfig(CosmosProxyTransport.HttpConnect, "http://proxy:3128", "HTTPS_PROXY");
        Assert.Throws<InvalidOperationException>(() =>
            CosmosClientFactory.ResolveConnectionMode(config, proxy));
    }
}
