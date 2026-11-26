using Xunit;
using FluentAssertions;
using System.Text.Json;
using Microsoft.Extensions.Logging;
using Microsoft.Extensions.Configuration;
using Moq;
using AzureCosmosDB.MCP.Toolkit.Services;
using Microsoft.Azure.Cosmos;
using ModelContextProtocol.Server;

namespace AzureCosmosDB.MCP.Toolkit.Tests;

public class CosmosDbToolsTests
{
    private readonly Mock<ILogger<CosmosDbToolsService>> _loggerMock;
    private readonly Mock<IConfiguration> _configurationMock;
    
    public CosmosDbToolsTests()
    {
        _loggerMock = new Mock<ILogger<CosmosDbToolsService>>();
        _configurationMock = new Mock<IConfiguration>();
    }

    [Fact]
    public void Bm25QueryHelper_Should_Parameterize_Individual_Terms()
    {
        var terms = Bm25QueryHelper.PrepareTerms("Vitamin A X-1", "split");
        var ranking = Bm25QueryHelper.BuildHybridRanking("text", "vector", terms);
        var query = Bm25QueryHelper.BindParameters(new QueryDefinition(ranking), terms);

        ranking.Should().Be("RRF(VectorDistance(c.vector, @embedding), FullTextScore(c.text, @bm25Term0, @bm25Term1, @bm25Term2, @bm25Term3))");
        query.GetQueryParameters().Select(parameter => parameter.Value)
            .Should().Equal("Vitamin", "A", "X", "1");
    }

    [Fact]
    public void Bm25QueryHelper_Should_Accept_Thirty_Terms_By_Default()
    {
        var text = string.Join(" ", Enumerable.Range(0, 30).Select(index => $"term{index}"));
        var terms = Bm25QueryHelper.PrepareTerms(text);
        var query = Bm25QueryHelper.BindParameters(new QueryDefinition(Bm25QueryHelper.BuildHybridRanking("text", "vector", terms)), terms);

        query.GetQueryParameters().Should().HaveCount(30);
        query.QueryText.Should().Contain("@bm25Term29");
        query.QueryText.Should().NotContain("[30");
    }

    [Fact]
    public void Bm25QueryHelper_Should_Split_Long_Queries_By_Default_Without_Truncation()
    {
        var text = string.Join(" ", Enumerable.Range(0, 31).Select(index => $"term{index}"));
        var terms = Bm25QueryHelper.PrepareTerms(text);
        var query = Bm25QueryHelper.BindParameters(new QueryDefinition(Bm25QueryHelper.BuildHybridRanking("text", "vector", terms)), terms);

        Bm25QueryHelper.DefaultPolicy.Should().Be("split");
        query.GetQueryParameters().Should().HaveCount(31);
        query.QueryText.Should().EndWith(", [31, 30, 1])");
    }

    [Theory]
    [InlineData(31, "[31, 30, 1]")]
    [InlineData(61, "[61, 30, 30, 1]")]
    public void Bm25QueryHelper_Should_Keep_All_Grouped_Terms_And_Balance_Their_Weights(int count, string weights)
    {
        var text = string.Join(" ", Enumerable.Range(0, count).Select(index => $"term{index}"));
        var terms = Bm25QueryHelper.PrepareTerms(text, "split");
        var ranking = Bm25QueryHelper.BuildHybridRanking("text", "vector", terms);
        var query = Bm25QueryHelper.BindParameters(new QueryDefinition(ranking), terms);

        query.GetQueryParameters().Should().HaveCount(count);
        query.GetQueryParameters().Select(parameter => parameter.Value)
            .Should().Equal(Enumerable.Range(0, count).Select(index => $"term{index}"));
        ranking.Should().EndWith($", {weights})");
        ranking.Should().NotContain("RRF(RRF(");
        var scores = System.Text.RegularExpressions.Regex.Matches(ranking, @"FullTextScore\(c\.text, ([^)]+)\)");
        scores.Should().HaveCount((count + 29) / 30);
        scores.Cast<System.Text.RegularExpressions.Match>()
            .Should().OnlyContain(score => score.Groups[1].Value.Split(", ", StringSplitOptions.None).Length <= 30);
    }

    [Fact]
    public void Bm25QueryHelper_Should_Build_One_Keyword_Score_Per_Group_Of_At_Most_Thirty_Terms()
    {
        var text = string.Join(" ", Enumerable.Range(0, 31).Select(index => $"term{index}"));
        var terms = Bm25QueryHelper.PrepareTerms(text);

        var scores = Bm25QueryHelper.BuildKeywordScores("text", terms);

        scores.Select(score => score.TermCount).Should().Equal(30, 1);
        scores[0].Expression.Should().StartWith("FullTextScore(c.text, @bm25Term0, ")
            .And.EndWith(", @bm25Term29)");
        scores[1].Expression.Should().Be("FullTextScore(c.text, @bm25Term30)");
    }

    [Fact]
    public void Bm25QueryHelper_Should_Build_Keyword_Ranking_Without_Rrf_For_One_Group()
    {
        var terms = Bm25QueryHelper.PrepareTerms("capital city");

        Bm25QueryHelper.BuildKeywordRanking("text", terms)
            .Should().Be("FullTextScore(c.text, @bm25Term0, @bm25Term1)");
        Bm25QueryHelper.BuildKeywordFilter("text", terms)
            .Should().Be("FullTextContainsAny(c.text, @bm25Term0, @bm25Term1)");
    }

    [Fact]
    public void Bm25QueryHelper_Should_Weight_Keyword_Groups_By_Word_Count_Without_Vector()
    {
        var text = string.Join(" ", Enumerable.Range(0, 31).Select(index => $"term{index}"));
        var terms = Bm25QueryHelper.PrepareTerms(text);

        var ranking = Bm25QueryHelper.BuildKeywordRanking("text", terms);
        var filter = Bm25QueryHelper.BuildKeywordFilter("text", terms);

        ranking.Should().StartWith("RRF(FullTextScore(c.text, @bm25Term0, ")
            .And.EndWith("FullTextScore(c.text, @bm25Term30), [30, 1])")
            .And.NotContain("VectorDistance");
        filter.Should().StartWith("FullTextContainsAny(c.text, @bm25Term0, ")
            .And.EndWith(", @bm25Term30)");
        System.Text.RegularExpressions.Regex.Matches(filter, "@bm25Term").Should().HaveCount(31);
    }

    [Fact]
    public void Bm25QueryHelper_Should_Keep_Whole_Phrase_As_One_Keyword_Argument()
    {
        var terms = Bm25QueryHelper.PrepareTerms("capital city", "whole");

        Bm25QueryHelper.BuildKeywordRanking("text", terms).Should().Be("FullTextScore(c.text, @bm25Term0)");
        Bm25QueryHelper.BuildKeywordFilter("text", terms).Should().Be("FullTextContainsAny(c.text, @bm25Term0)");
    }

    [Fact]
    public void Bm25QueryHelper_Should_Preserve_Original_Phrase_As_One_Parameter()
    {
        const string text = "O'Reilly's distributed systems";
        var terms = Bm25QueryHelper.PrepareTerms(text, "whole");
        var query = Bm25QueryHelper.BindParameters(new QueryDefinition(Bm25QueryHelper.BuildHybridRanking("text", "vector", terms)), terms);

        query.QueryText.Should().Be("RRF(VectorDistance(c.vector, @embedding), FullTextScore(c.text, @bm25Term0))");
        query.QueryText.Should().NotContain(text);
        query.GetQueryParameters().Should().ContainSingle()
            .Which.Value.Should().Be(text);
    }

    [Theory]
    [InlineData("", "split")]
    [InlineData("   ", "split")]
    [InlineData("!!!", "split")]
    [InlineData("query", "unknown")]
    public void Bm25QueryHelper_Should_Reject_Invalid_Input(string text, string policy)
    {
        Action prepare = () => Bm25QueryHelper.PrepareTerms(text, policy);

        prepare.Should().Throw<ArgumentException>();
    }

    [Theory]
    [InlineData("unknown", 1)]
    [InlineData("terms", 31)]
    public async Task HybridSearch_Should_Validate_Bm25_Policy_Before_Using_External_Services(string policy, int termCount)
    {
        var client = new Mock<CosmosClient>();
        var service = new CosmosDbToolsService(client.Object, _loggerMock.Object, _configurationMock.Object);
        var text = string.Join(" ", Enumerable.Range(0, termCount).Select(index => $"term{index}"));

        var result = await service.HybridSearch("db", "container", text, "text", "vector", "id", bm25QueryPolicy: policy);

        JsonSerializer.Serialize(result).Should().Contain("error");
        client.VerifyNoOtherCalls();
        _configurationMock.VerifyNoOtherCalls();
    }

    [Fact]
    public void McpToolRequestValidator_Should_Accept_Bm25_Query_Policy()
    {
        var validator = new McpToolRequestValidator();
        using var document = JsonDocument.Parse(
            """
            {
                "name": "hybrid_search",
                "arguments": {
                    "databaseId": "db",
                    "containerId": "container",
                    "searchText": "machine learning",
                    "textProperty": "text",
                    "vectorProperty": "vector",
                    "selectProperties": "id",
                    "bm25QueryPolicy": "split"
                }
            }
            """);

        var result = validator.ValidateToolCall(document.RootElement);

        result.Arguments["bm25QueryPolicy"].Should().Be("split");
    }

    [Fact]
    public void HybridSearch_Should_Expose_Optional_Bm25_Policy_Without_Changing_Vector_Search()
    {
        var tools = typeof(global::CosmosDbTools);
        var hybrid = tools.GetMethod("HybridSearch")!;
        var policy = hybrid.GetParameters().Single(parameter => parameter.Name == "bm25QueryPolicy");

        policy.ParameterType.Should().Be(typeof(string));
        policy.IsOptional.Should().BeTrue();
        policy.DefaultValue.Should().Be(Bm25QueryHelper.DefaultPolicy);
        tools.GetMethod("VectorSearch")!.GetParameters()
            .Should().NotContain(parameter => parameter.Name == "bm25QueryPolicy");
    }

    [Fact]
    public void Bm25Search_Should_Be_ReadOnly_Keyword_Tool_Without_Vector_Arguments()
    {
        var method = typeof(global::CosmosDbTools).GetMethod("Bm25Search")!;
        var toolAttribute = method.GetCustomAttributes(typeof(McpServerToolAttribute), inherit: false)
            .Cast<McpServerToolAttribute>().Single();
        var policy = method.GetParameters().Single(parameter => parameter.Name == "bm25QueryPolicy");

        toolAttribute.Name.Should().Be("bm25_search");
        toolAttribute.ReadOnly.Should().BeTrue();
        method.GetParameters().Select(parameter => parameter.Name).Should().Equal(
            "databaseId", "containerId", "searchText", "textProperty", "selectProperties", "topN", "bm25QueryPolicy");
        policy.DefaultValue.Should().Be(Bm25QueryHelper.DefaultPolicy);
    }

    [Fact]
    public void Bm25QueryHelper_Should_Keep_Stop_Words_And_Repeated_Terms()
    {
        var terms = Bm25QueryHelper.PrepareTerms("the and alpha alpha 2026");
        var query = Bm25QueryHelper.BindParameters(new QueryDefinition(Bm25QueryHelper.BuildHybridRanking("text", "vector", terms)), terms);

        query.GetQueryParameters().Select(parameter => parameter.Value)
            .Should().Equal("the", "and", "alpha", "alpha", "2026");
    }

    [Fact]
    public void CosmosDbToolsService_Should_Exist()
    {
        // Arrange & Act
        var type = typeof(CosmosDbToolsService);
        
        // Assert
        type.Should().NotBeNull();
        type.Name.Should().Be("CosmosDbToolsService");
    }

    [Fact]
    public async Task TextSearch_Should_Validate_Property_Names()
    {
        // Arrange
        var mockCosmosClient = new Mock<CosmosClient>();
        var service = new CosmosDbToolsService(mockCosmosClient.Object, _loggerMock.Object, _configurationMock.Object);
        var invalidProperty = "invalid-property-name!";
        
        // Act
        var result = await service.TextSearch("testDb", "testContainer", invalidProperty, "search", 1);
        
        // Assert
        result.Should().NotBeNull();
        var resultDict = result as dynamic;
        var errorMessage = JsonSerializer.Serialize(result);
        errorMessage.Should().Contain("Invalid property name");
    }

    [Theory]
    [InlineData(0)]
    [InlineData(21)]
    [InlineData(-1)]
    public async Task GetRecentDocuments_Should_Validate_Count_Parameter(int n)
    {
        // Arrange
        var mockCosmosClient = new Mock<CosmosClient>();
        var service = new CosmosDbToolsService(mockCosmosClient.Object, _loggerMock.Object, _configurationMock.Object);
        
        // Act
        var result = await service.GetRecentDocuments("testDb", "testContainer", n);
        
        // Assert
        result.Should().NotBeNull();
        var errorMessage = JsonSerializer.Serialize(result);
        errorMessage.Should().Contain("must be a whole number between 1 and 20");
    }
    
    [Fact]
    public async Task FindDocumentByID_Should_Require_Parameters()
    {
        // Arrange
        var mockCosmosClient = new Mock<CosmosClient>();
        var service = new CosmosDbToolsService(mockCosmosClient.Object, _loggerMock.Object, _configurationMock.Object);
        
        // Act
        var result = await service.FindDocumentByID("", "", "");
        
        // Assert
        result.Should().NotBeNull();
        var errorMessage = JsonSerializer.Serialize(result);
        errorMessage.Should().Contain("required");
    }

    [Theory]
    [InlineData(0)]
    [InlineData(51)]
    [InlineData(-1)]
    public async Task HybridSearch_Should_Validate_TopN_Parameter(int topN)
    {
        // Arrange
        var mockCosmosClient = new Mock<CosmosClient>();
        var service = new CosmosDbToolsService(mockCosmosClient.Object, _loggerMock.Object, _configurationMock.Object);
        
        // Act
        var result = await service.HybridSearch("testDb", "testContainer", "search text", "text", "vector", "id,title", topN);
        
        // Assert
        result.Should().NotBeNull();
        var errorMessage = JsonSerializer.Serialize(result);
        errorMessage.Should().Contain("must be a whole number between 1 and 50");
    }

    [Fact]
    public async Task HybridSearch_Should_Reject_Wildcard_SelectProperties()
    {
        // Arrange
        var mockCosmosClient = new Mock<CosmosClient>();
        var service = new CosmosDbToolsService(mockCosmosClient.Object, _loggerMock.Object, _configurationMock.Object);
        
        // Act
        var result = await service.HybridSearch("testDb", "testContainer", "search text", "text", "vector", "*", 10);
        
        // Assert
        result.Should().NotBeNull();
        var errorMessage = JsonSerializer.Serialize(result);
        errorMessage.Should().Contain("cannot contain '*' wildcard");
    }

    [Fact]
    public async Task HybridSearch_Should_Validate_VectorProperty_Name()
    {
        // Arrange
        var mockCosmosClient = new Mock<CosmosClient>();
        var service = new CosmosDbToolsService(mockCosmosClient.Object, _loggerMock.Object, _configurationMock.Object);
        
        // Act
        var result = await service.HybridSearch("testDb", "testContainer", "search text", "text", "invalid-vector!", "id,title", 10);
        
        // Assert
        result.Should().NotBeNull();
        var errorMessage = JsonSerializer.Serialize(result);
        errorMessage.Should().Contain("Invalid vectorProperty name");
    }

    [Fact]
    public async Task HybridSearch_Should_Validate_TextProperty_Name()
    {
        // Arrange
        var mockCosmosClient = new Mock<CosmosClient>();
        var service = new CosmosDbToolsService(mockCosmosClient.Object, _loggerMock.Object, _configurationMock.Object);
        
        // Act
        var result = await service.HybridSearch("testDb", "testContainer", "search text", "invalid-text!", "vector", "id,title", 10);
        
        // Assert
        result.Should().NotBeNull();
        var errorMessage = JsonSerializer.Serialize(result);
        errorMessage.Should().Contain("Invalid textProperty name");
    }

    [Fact]
    public async Task HybridSearch_Should_Require_Parameters()
    {
        // Arrange
        var mockCosmosClient = new Mock<CosmosClient>();
        var service = new CosmosDbToolsService(mockCosmosClient.Object, _loggerMock.Object, _configurationMock.Object);
        
        // Act
        var result = await service.HybridSearch("", "", "", "", "", "", 10);
        
        // Assert
        result.Should().NotBeNull();
        var errorMessage = JsonSerializer.Serialize(result);
        errorMessage.Should().Contain("required");
    }

    [Fact]
    public void McpToolRequestValidator_Should_Accept_Valid_HybridSearch()
    {
        // Arrange
        var validator = new McpToolRequestValidator();
        using var document = JsonDocument.Parse(
            """
            {
                "name": "hybrid_search",
                "arguments": {
                    "databaseId": "db1",
                    "containerId": "container1",
                    "searchText": "machine learning",
                    "textProperty": "content",
                    "vectorProperty": "embedding",
                    "selectProperties": "id,title,content",
                    "topN": 10
                }
            }
            """);

        // Act
        var result = validator.ValidateToolCall(document.RootElement);

        // Assert
        result.ToolName.Should().Be("hybrid_search");
        result.Arguments["databaseId"].Should().Be("db1");
        result.Arguments["containerId"].Should().Be("container1");
        result.Arguments["searchText"].Should().Be("machine learning");
        result.Arguments["textProperty"].Should().Be("content");
        result.Arguments["vectorProperty"].Should().Be("embedding");
        result.Arguments["selectProperties"].Should().Be("id,title,content");
        result.Arguments["topN"].Should().Be(10);
    }

    [Fact]
    public void McpToolRequestValidator_Should_Reject_HybridSearch_Missing_TextProperty()
    {
        // Arrange
        var validator = new McpToolRequestValidator();
        using var document = JsonDocument.Parse(
            """
            {
                "name": "hybrid_search",
                "arguments": {
                    "databaseId": "db1",
                    "containerId": "container1",
                    "searchText": "machine learning",
                    "vectorProperty": "embedding",
                    "selectProperties": "id,title",
                    "topN": 10
                }
            }
            """);

        // Act
        Action act = () => validator.ValidateToolCall(document.RootElement);

        // Assert
        act.Should().Throw<ToolInputValidationException>()
            .WithMessage("*Missing required argument 'textProperty'*");
    }

    [Theory]
    [InlineData("", "text", "id", 10, "split", "required")]
    [InlineData("search text", "invalid-text!", "id", 10, "split", "Invalid textProperty name")]
    [InlineData("search text", "text", "*", 10, "split", "wildcard")]
    [InlineData("search text", "text", "id", 51, "split", "between 1 and 50")]
    [InlineData("search text", "text", "id", 10, "unknown", "BM25 query policy")]
    public async Task Bm25Search_Should_Reject_Invalid_Input_Before_Querying_Cosmos(
        string searchText, string textProperty, string selectProperties, int topN, string policy, string expectedError)
    {
        var client = new Mock<CosmosClient>();
        var service = new CosmosDbToolsService(client.Object, _loggerMock.Object, _configurationMock.Object);

        var result = await service.Bm25Search("db", "container", searchText, textProperty, selectProperties, topN, policy);

        JsonSerializer.Serialize(result).Should().Contain(expectedError);
        client.VerifyNoOtherCalls();
    }

    [Fact]
    public void McpToolRequestValidator_Should_Accept_Bm25Search_Without_VectorProperty()
    {
        var validator = new McpToolRequestValidator();
        using var document = JsonDocument.Parse(
            """
            {
                "name": "bm25_search",
                "arguments": {
                    "databaseId": "db",
                    "containerId": "container",
                    "searchText": "machine learning",
                    "textProperty": "text",
                    "selectProperties": "id",
                    "bm25QueryPolicy": "whole",
                    "topN": 5
                }
            }
            """);

        var result = validator.ValidateToolCall(document.RootElement);

        result.ToolName.Should().Be("bm25_search");
        result.Arguments["bm25QueryPolicy"].Should().Be("whole");
        result.Arguments["topN"].Should().Be(5);
    }

    [Fact]
    public void McpToolRequestValidator_Should_Reject_Bm25Search_VectorProperty()
    {
        var validator = new McpToolRequestValidator();
        using var document = JsonDocument.Parse(
            """
            {
                "name": "bm25_search",
                "arguments": {
                    "databaseId": "db",
                    "containerId": "container",
                    "searchText": "machine learning",
                    "textProperty": "text",
                    "vectorProperty": "vector",
                    "selectProperties": "id"
                }
            }
            """);

        Action act = () => validator.ValidateToolCall(document.RootElement);

        act.Should().Throw<ToolInputValidationException>()
            .WithMessage("*Unknown property 'vectorProperty' in arguments for 'bm25_search'.*");
    }

        [Fact]
        public void McpToolRequestValidator_Should_Reject_Unknown_Argument_Properties()
        {
                // Arrange
                var validator = new McpToolRequestValidator();
                using var document = JsonDocument.Parse(
                        """
                        {
                            "name": "list_collections",
                            "arguments": {
                                "databaseId": "db1",
                                "unexpected": "value"
                            }
                        }
                        """);

                // Act
                Action act = () => validator.ValidateToolCall(document.RootElement);

                // Assert
                act.Should().Throw<ToolInputValidationException>()
                        .WithMessage("*Unknown property 'unexpected' in arguments for 'list_collections'.*");
        }

        [Fact]
        public void McpToolRequestValidator_Should_Reject_Wrong_Types()
        {
                // Arrange
                var validator = new McpToolRequestValidator();
                using var document = JsonDocument.Parse(
                        """
                        {
                            "name": "get_recent_documents",
                            "arguments": {
                                "databaseId": "db1",
                                "containerId": "c1",
                                "n": "5"
                            }
                        }
                        """);

                // Act
                Action act = () => validator.ValidateToolCall(document.RootElement);

                // Assert
                act.Should().Throw<ToolInputValidationException>()
                        .WithMessage("*'n' must be an integer.*");
        }

        [Fact]
        public void McpToolRequestValidator_Should_Reject_Oversized_Freeform_Strings()
        {
                // Arrange
                var validator = new McpToolRequestValidator();
                var oversized = new string('a', 2049);
                using var document = JsonDocument.Parse(
                        $$"""
                        {
                            "name": "text_search",
                            "arguments": {
                                "databaseId": "db1",
                                "containerId": "c1",
                                "property": "title",
                                "searchPhrase": "{{oversized}}",
                                "n": 5
                            }
                        }
                        """);

                // Act
                Action act = () => validator.ValidateToolCall(document.RootElement);

                // Assert
                act.Should().Throw<ToolInputValidationException>()
                        .WithMessage("*'searchPhrase' exceeds the maximum length of 2048 characters.*");
        }

        [Fact]
        public void McpToolRequestValidator_Should_Normalize_Valid_Strings()
        {
                // Arrange
                var validator = new McpToolRequestValidator();
                using var document = JsonDocument.Parse(
                        """
                        {
                            "name": "list_collections",
                            "arguments": {
                                "databaseId": "db1"
                            }
                        }
                        """);

                // Act
                var result = validator.ValidateToolCall(document.RootElement);

                // Assert
                result.ToolName.Should().Be("list_collections");
                result.Arguments["databaseId"].Should().Be("db1");
        }
}