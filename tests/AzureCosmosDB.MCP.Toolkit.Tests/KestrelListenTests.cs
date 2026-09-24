using AzureCosmosDB.MCP.Toolkit.Hosting;
using Xunit;

namespace AzureCosmosDB.MCP.Toolkit.Tests;

public class KestrelListenTests
{
    [Theory]
    [InlineData(null, false)]
    [InlineData("", false)]
    [InlineData("   ", false)]
    [InlineData("http://+:8080", true)]
    [InlineData("http://127.0.0.1:18080", true)]
    public void ShouldUseAspNetCoreUrls_WhenSet(string? urls, bool expected)
    {
        Assert.Equal(expected, KestrelListen.ShouldUseAspNetCoreUrls(urls));
    }
}
