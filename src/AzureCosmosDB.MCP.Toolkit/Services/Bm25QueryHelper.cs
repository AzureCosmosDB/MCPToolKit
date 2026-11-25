using System.Text.RegularExpressions;
using Microsoft.Azure.Cosmos;

namespace AzureCosmosDB.MCP.Toolkit.Services;

public static class Bm25QueryHelper
{
    public const string DefaultPolicy = "split";
    private const int MaxTermsPerScore = 30;

    /// <summary>Prepares BM25 arguments by splitting the query into words or keeping it whole.</summary>
    public static string[] PrepareTerms(string searchText, string bm25QueryPolicy = DefaultPolicy)
    {
        ArgumentException.ThrowIfNullOrWhiteSpace(searchText);

        if (bm25QueryPolicy == "whole")
        {
            return [searchText];
        }

        if (bm25QueryPolicy != "split")
        {
            throw new ArgumentException("BM25 query policy must be 'split' or 'whole'.", nameof(bm25QueryPolicy));
        }

        var terms = Regex.Matches(searchText, @"\w+")
            .Select(match => match.Value)
            .ToArray();

        if (terms.Length == 0)
        {
            throw new ArgumentException("Search text must contain at least one word or number.", nameof(searchText));
        }

        return terms;
    }

    /// <summary>Builds a flat vector/BM25 ranking expression for validated property paths.</summary>
    public static string BuildHybridRanking(string textProperty, string vectorProperty, string[] terms)
    {
        var scores = new List<string> { $"VectorDistance(c.{vectorProperty}, @embedding)" };
        var groups = terms.Chunk(MaxTermsPerScore).ToArray();
        var termOffset = 0;

        foreach (var group in groups)
        {
            var parameters = Enumerable.Range(termOffset, group.Length)
                .Select(index => $"@bm25Term{index}");
            scores.Add($"FullTextScore(c.{textProperty}, {string.Join(", ", parameters)})");
            termOffset += group.Length;
        }

        if (groups.Length > 1)
        {
            var weights = new[] { terms.Length }.Concat(groups.Select(group => group.Length));
            scores.Add($"[{string.Join(", ", weights)}]");
        }

        return $"RRF({string.Join(", ", scores)})";
    }

    /// <summary>Binds every prepared term without interpolating search text into SQL.</summary>
    public static QueryDefinition BindParameters(QueryDefinition query, string[] terms)
    {
        for (var index = 0; index < terms.Length; index++)
        {
            query.WithParameter($"@bm25Term{index}", terms[index]);
        }

        return query;
    }
}