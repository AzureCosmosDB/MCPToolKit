using Xunit;
using FluentAssertions;
using System.Net;
using System.Text;
using System.Text.Json;
using Microsoft.Extensions.Logging;
using Microsoft.Extensions.Configuration;
using Moq;
using Moq.Protected;
using AzureCosmosDB.MCP.Toolkit.Services;

namespace AzureCosmosDB.MCP.Toolkit.Tests;

public class CopyJobServiceTests
{
    private readonly Mock<ILogger<CopyJobService>> _loggerMock;
    private readonly Mock<IConfiguration> _configurationMock;

    public CopyJobServiceTests()
    {
        _loggerMock = new Mock<ILogger<CopyJobService>>();
        _configurationMock = new Mock<IConfiguration>();
    }

    [Fact]
    public void CopyJobService_Should_Exist()
    {
        var type = typeof(CopyJobService);
        type.Should().NotBeNull();
        type.Name.Should().Be("CopyJobService");
    }

    [Fact]
    public async Task CreateCopyJob_Should_Require_SubscriptionId()
    {
        // Arrange
        var httpClientFactory = new Mock<IHttpClientFactory>();
        var service = new CopyJobService(httpClientFactory.Object, _loggerMock.Object, _configurationMock.Object);

        // Act & Assert
        await Assert.ThrowsAsync<ArgumentException>(() =>
            service.CreateCopyJob("", "testJob", "{}", cancellationToken: CancellationToken.None));
    }

    [Fact]
    public async Task CreateCopyJob_Should_Require_JobName()
    {
        var httpClientFactory = new Mock<IHttpClientFactory>();
        var service = new CopyJobService(httpClientFactory.Object, _loggerMock.Object, _configurationMock.Object);

        await Assert.ThrowsAsync<ArgumentException>(() =>
            service.CreateCopyJob("sub-123", "", "{}", cancellationToken: CancellationToken.None));
    }

    [Fact]
    public async Task CreateCopyJob_Should_Require_JobProperties()
    {
        var httpClientFactory = new Mock<IHttpClientFactory>();
        var service = new CopyJobService(httpClientFactory.Object, _loggerMock.Object, _configurationMock.Object);

        await Assert.ThrowsAsync<ArgumentException>(() =>
            service.CreateCopyJob("sub-123", "testJob", "", cancellationToken: CancellationToken.None));
    }

    [Fact]
    public async Task CreateCopyJob_Should_Validate_JobProperties_Json()
    {
        // Arrange
        Environment.SetEnvironmentVariable("COSMOS_ENDPOINT", "https://testaccount.documents.azure.com:443/");
        var httpClientFactory = new Mock<IHttpClientFactory>();
        var service = new CopyJobService(httpClientFactory.Object, _loggerMock.Object, _configurationMock.Object);

        // Act & Assert — invalid JSON should throw ArgumentException
        await Assert.ThrowsAsync<ArgumentException>(() =>
            service.CreateCopyJob("sub-123", "testJob", "not-valid-json", cancellationToken: CancellationToken.None));

        // Cleanup
        Environment.SetEnvironmentVariable("COSMOS_ENDPOINT", null);
    }

    [Fact]
    public async Task GetCopyJob_Should_Require_SubscriptionId()
    {
        var httpClientFactory = new Mock<IHttpClientFactory>();
        var service = new CopyJobService(httpClientFactory.Object, _loggerMock.Object, _configurationMock.Object);

        await Assert.ThrowsAsync<ArgumentException>(() =>
            service.GetCopyJob("", "testJob", CancellationToken.None));
    }

    [Fact]
    public async Task GetCopyJob_Should_Require_JobName()
    {
        var httpClientFactory = new Mock<IHttpClientFactory>();
        var service = new CopyJobService(httpClientFactory.Object, _loggerMock.Object, _configurationMock.Object);

        await Assert.ThrowsAsync<ArgumentException>(() =>
            service.GetCopyJob("sub-123", "", CancellationToken.None));
    }

    [Fact]
    public async Task ListCopyJobs_Should_Require_SubscriptionId()
    {
        var httpClientFactory = new Mock<IHttpClientFactory>();
        var service = new CopyJobService(httpClientFactory.Object, _loggerMock.Object, _configurationMock.Object);

        await Assert.ThrowsAsync<ArgumentException>(() =>
            service.ListCopyJobs("", CancellationToken.None));
    }

    [Fact]
    public async Task CopyJobAction_Should_Require_SubscriptionId()
    {
        var httpClientFactory = new Mock<IHttpClientFactory>();
        var service = new CopyJobService(httpClientFactory.Object, _loggerMock.Object, _configurationMock.Object);

        await Assert.ThrowsAsync<ArgumentException>(() =>
            service.CopyJobAction("", "testJob", "cancel", CancellationToken.None));
    }

    [Fact]
    public async Task CopyJobAction_Should_Require_JobName()
    {
        var httpClientFactory = new Mock<IHttpClientFactory>();
        var service = new CopyJobService(httpClientFactory.Object, _loggerMock.Object, _configurationMock.Object);

        await Assert.ThrowsAsync<ArgumentException>(() =>
            service.CopyJobAction("sub-123", "", "cancel", CancellationToken.None));
    }
}
