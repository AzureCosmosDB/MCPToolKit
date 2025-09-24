using Xunit;
using FluentAssertions;
using System.Text.Json;

namespace AzureCosmosDB.MCP.Toolkit.Tests;

public class CosmosDbToolsTests
{
    [Fact]
    public void CosmosDbTools_Should_Exist()
    {
        // Arrange & Act
        var type = typeof(CosmosDbTools);
        
        // Assert
        type.Should().NotBeNull();
        type.Name.Should().Be("CosmosDbTools");
    }

    [Theory]
    [InlineData("")]
    [InlineData("   ")]
    [InlineData(null)]
    public async Task ListDatabases_Should_Return_Error_When_Endpoint_Missing(string? endpoint)
    {
        // Arrange
        Environment.SetEnvironmentVariable("COSMOS_ENDPOINT", endpoint);
        
        // Act
        var result = await CosmosDbTools.ListDatabases();
        
        // Assert
        var jsonDoc = JsonDocument.Parse(result);
        jsonDoc.RootElement.TryGetProperty("error", out var errorElement).Should().BeTrue();
        errorElement.GetString().Should().Be("Missing required environment variable COSMOS_ENDPOINT.");
        
        // Cleanup
        Environment.SetEnvironmentVariable("COSMOS_ENDPOINT", null);
    }

    [Fact]
    public async Task TextSearch_Should_Validate_Property_Names()
    {
        // Arrange
        Environment.SetEnvironmentVariable("COSMOS_ENDPOINT", "https://test.documents.azure.com:443/");
        var invalidProperty = "invalid-property-name!";
        
        // Act
        var result = await CosmosDbTools.TextSearch("testDb", "testContainer", invalidProperty, "search", 1);
        
        // Assert
        var jsonDoc = JsonDocument.Parse(result);
        jsonDoc.RootElement.TryGetProperty("error", out var errorElement).Should().BeTrue();
        errorElement.GetString().Should().Contain("Invalid property name");
        
        // Cleanup
        Environment.SetEnvironmentVariable("COSMOS_ENDPOINT", null);
    }

    [Theory]
    [InlineData(0)]
    [InlineData(21)]
    [InlineData(-1)]
    public async Task GetRecentDocuments_Should_Validate_Count_Parameter(int n)
    {
        // Arrange
        Environment.SetEnvironmentVariable("COSMOS_ENDPOINT", "https://test.documents.azure.com:443/");
        
        // Act
        var result = await CosmosDbTools.GetRecentDocuments("testDb", "testContainer", n);
        
        // Assert
        var jsonDoc = JsonDocument.Parse(result);
        jsonDoc.RootElement.TryGetProperty("error", out var errorElement).Should().BeTrue();
        errorElement.GetString().Should().Be("Parameter 'n' must be a whole number between 1 and 20.");
        
        // Cleanup
        Environment.SetEnvironmentVariable("COSMOS_ENDPOINT", null);
    }
}