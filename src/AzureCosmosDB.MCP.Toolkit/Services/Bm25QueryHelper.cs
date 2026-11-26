using System.Text.RegularExpressions;
using Microsoft.Azure.Cosmos;

namespace AzureCosmosDB.MCP.Toolkit.Services;

public static class Bm25QueryHelper
{
    // Default "split" uses one BM25 call per group of at most 30 words.
    // For multiple groups, weighted RRF combines vector and group rank positions:
    // vector weight = total word count; group weight = that group's word count.
    // This heuristic discards BM25 score magnitudes and is not equivalent to
    // scoring every word together in one BM25 call.
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
        var keywordScores = BuildKeywordScores(textProperty, terms);
        var scores = new List<string> { $"VectorDistance(c.{vectorProperty}, @embedding)" };
        scores.AddRange(keywordScores.Select(score => score.Expression));

        if (keywordScores.Count > 1)
        {
            var weights = new[] { terms.Length }.Concat(keywordScores.Select(score => score.TermCount));
            scores.Add($"[{string.Join(", ", weights)}]");
        }

        return $"RRF({string.Join(", ", scores)})";
    }

    /// <summary>Builds a BM25 ranking expression; long queries are broken into groups weighted by word count.</summary>
    public static string BuildKeywordRanking(string textProperty, string[] terms)
    {
        var keywordScores = BuildKeywordScores(textProperty, terms);

        if (keywordScores.Count == 1)
        {
            return keywordScores[0].Expression;
        }

        var weights = keywordScores.Select(score => score.TermCount);
        return $"RRF({string.Join(", ", keywordScores.Select(score => score.Expression))}, [{string.Join(", ", weights)}])";
    }

    /// <summary>Keeps only documents containing at least one term; BM25 ranking alone also returns non-matches.</summary>
    public static string BuildKeywordFilter(string textProperty, string[] terms)
    {
        var parameters = Enumerable.Range(0, terms.Length).Select(index => $"@bm25Term{index}");
        return $"FullTextContainsAny(c.{textProperty}, {string.Join(", ", parameters)})";
    }

    /// <summary>Builds one BM25 score per group of at most 30 terms, with that group's term count.</summary>
    public static IReadOnlyList<(string Expression, int TermCount)> BuildKeywordScores(string textProperty, string[] terms)
    {
        var scores = new List<(string Expression, int TermCount)>();
        var termOffset = 0;

        foreach (var group in terms.Chunk(MaxTermsPerScore))
        {
            var parameters = Enumerable.Range(termOffset, group.Length)
                .Select(index => $"@bm25Term{index}");
            scores.Add(($"FullTextScore(c.{textProperty}, {string.Join(", ", parameters)})", group.Length));
            termOffset += group.Length;
        }

        return scores;
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