using AzureCosmosDB.MCP.Toolkit.Services;
using FluentAssertions;
using Microsoft.Extensions.Configuration;
using Microsoft.Extensions.Logging;
using Moq;
using Xunit;

namespace AzureCosmosDB.MCP.Toolkit.Tests;

public class EmbeddingClientFactoryTests
{
    [Theory]
    [InlineData("https://test.openai.azure.com/")]
    [InlineData("https://test.cognitiveservices.azure.com/")]
    [InlineData("https://test.services.ai.azure.com/api/projects/demo")]
    public void AzureEndpoints_IgnoreStaleKeysAndUseEntra(string endpoint)
    {
        var configuration = CreateConfiguration(endpoint, "stale-azure-key");
        var logger = new Mock<ILogger>();

        EmbeddingClientFactory.CreateEmbeddingClient(configuration, logger.Object)
            .Should().NotBeNull();

        logger.Verify(
            x => x.Log(
                LogLevel.Warning,
                It.IsAny<EventId>(),
                It.Is<It.IsAnyType>((state, _) => state.ToString()!.Contains("OPENAI_API_KEY is ignored")),
                It.IsAny<Exception?>(),
                It.IsAny<Func<It.IsAnyType, Exception?, string>>()),
            Times.Once);
        logger.Verify(
            x => x.Log(
                LogLevel.Information,
                It.IsAny<EventId>(),
                It.Is<It.IsAnyType>((state, _) => state.ToString()!.Contains("Using Microsoft Entra ID")),
                It.IsAny<Exception?>(),
                It.IsAny<Func<It.IsAnyType, Exception?, string>>()),
            Times.Once);
        logger.Verify(
            x => x.Log(
                It.IsAny<LogLevel>(),
                It.IsAny<EventId>(),
                It.Is<It.IsAnyType>((state, _) => state.ToString()!.Contains("Using API key authentication")),
                It.IsAny<Exception?>(),
                It.IsAny<Func<It.IsAnyType, Exception?, string>>()),
            Times.Never);
    }

    [Fact]
    public void NativeOpenAI_StillRequiresAndAcceptsKey()
    {
        var withoutKey = () => EmbeddingClientFactory.CreateEmbeddingClient(
            CreateConfiguration("https://api.openai.com/v1", ""));
        withoutKey.Should().Throw<InvalidOperationException>().WithMessage("*requires OPENAI_API_KEY*");

        EmbeddingClientFactory.CreateEmbeddingClient(
            CreateConfiguration("https://api.openai.com/v1", "native-test-key"))
            .EndpointType.Should().Be("OpenAI Native API");
    }

    [Theory]
    [InlineData("https://test.openai.azure.com/?redirect=api.openai.com")]
    [InlineData("https://test.services.ai.azure.com/api/projects/api.openai.com")]
    public void NativeHostnameInAzurePathOrQuery_DoesNotEnableKeyAuth(string endpoint)
    {
        EmbeddingClientFactory.CreateEmbeddingClient(CreateConfiguration(endpoint, "stale-key"))
            .EndpointType.Should().NotBe("OpenAI Native API");
    }

    [Theory]
    [InlineData("http://api.openai.com/v1")]
    [InlineData("http://test.openai.azure.com/")]
    public void InsecureEndpoints_AreRejected(string endpoint)
    {
        var createClient = () => EmbeddingClientFactory.CreateEmbeddingClient(
            CreateConfiguration(endpoint, "test-key"));
        createClient.Should().Throw<ArgumentException>().WithMessage("*HTTPS*");
    }

    [Fact]
    public void LookalikeNativeHostname_IsRejected()
    {
        var createClient = () => EmbeddingClientFactory.CreateEmbeddingClient(
            CreateConfiguration("https://api.openai.com.example.org/v1", "test-key"));
        createClient.Should().Throw<InvalidOperationException>().WithMessage("*Unable to determine endpoint type*");
    }

    private static IConfiguration CreateConfiguration(string endpoint, string apiKey) =>
        new ConfigurationBuilder().AddInMemoryCollection(new Dictionary<string, string?>
        {
            ["OPENAI_ENDPOINT"] = endpoint,
            ["OPENAI_API_KEY"] = apiKey
        }).Build();
}
