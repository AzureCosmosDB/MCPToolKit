using System.Globalization;
using System.Text.Json.Nodes;

namespace AzureCosmosDB.MCP.Toolkit.Runtime;

/// <summary>
/// A deliberately minimal, safe boolean expression evaluator for bounded-composition assertions.
/// </summary>
/// <remarks>
/// Supports only comparisons (<c>== != &gt; &gt;= &lt; &lt;=</c>) combined with <c>&amp;&amp;</c> / <c>||</c>.
/// Operands are numeric literals, single-quoted string literals, boolean literals, or binding paths
/// (for example <c>input.amount</c> or <c>steps.source.balance</c>). There are no function calls,
/// loops, assignments, or arbitrary code — the engine cannot be used as a scripting runtime.
/// </remarks>
public static class SafeExpressionEvaluator
{
    public static bool Evaluate(string expression, BindingContext context, out string? error)
    {
        error = null;
        var expr = expression.Trim();
        if (expr.StartsWith("${", StringComparison.Ordinal) && expr.EndsWith('}'))
        {
            expr = expr[2..^1].Trim();
        }

        try
        {
            return EvaluateOr(expr, context);
        }
        catch (Exception ex)
        {
            error = $"Invalid assertion expression '{expression}': {ex.Message}";
            return false;
        }
    }

    private static bool EvaluateOr(string expr, BindingContext context)
    {
        var parts = SplitTopLevel(expr, "||");
        if (parts.Count > 1)
        {
            return parts.Any(p => EvaluateAnd(p, context));
        }

        return EvaluateAnd(expr, context);
    }

    private static bool EvaluateAnd(string expr, BindingContext context)
    {
        var parts = SplitTopLevel(expr, "&&");
        if (parts.Count > 1)
        {
            return parts.All(p => EvaluateComparison(p, context));
        }

        return EvaluateComparison(expr, context);
    }

    private static readonly string[] Operators = { ">=", "<=", "==", "!=", ">", "<" };

    private static bool EvaluateComparison(string expr, BindingContext context)
    {
        expr = expr.Trim();

        foreach (var op in Operators)
        {
            var idx = expr.IndexOf(op, StringComparison.Ordinal);
            if (idx > 0)
            {
                var left = ResolveOperand(expr[..idx].Trim(), context);
                var right = ResolveOperand(expr[(idx + op.Length)..].Trim(), context);
                return Compare(left, right, op);
            }
        }

        // A bare boolean operand.
        var single = ResolveOperand(expr, context);
        return single is JsonValue jv && jv.TryGetValue<bool>(out var b) && b;
    }

    private static JsonNode? ResolveOperand(string operand, BindingContext context)
    {
        if (operand.Length == 0)
        {
            throw new FormatException("empty operand");
        }

        if (operand.StartsWith('\'') && operand.EndsWith('\'') && operand.Length >= 2)
        {
            return JsonValue.Create(operand[1..^1]);
        }

        if (double.TryParse(operand, NumberStyles.Any, CultureInfo.InvariantCulture, out var number))
        {
            return JsonValue.Create(number);
        }

        if (bool.TryParse(operand, out var boolean))
        {
            return JsonValue.Create(boolean);
        }

        return context.BindTemplate("${" + operand + "}");
    }

    private static bool Compare(JsonNode? left, JsonNode? right, string op)
    {
        if (TryGetDouble(left, out var l) && TryGetDouble(right, out var r))
        {
            return op switch
            {
                ">=" => l >= r,
                "<=" => l <= r,
                ">" => l > r,
                "<" => l < r,
                "==" => l == r,
                "!=" => l != r,
                _ => false,
            };
        }

        var ls = left?.ToJsonString();
        var rs = right?.ToJsonString();
        return op switch
        {
            "==" => ls == rs,
            "!=" => ls != rs,
            _ => throw new FormatException($"operator '{op}' requires numeric operands"),
        };
    }

    private static bool TryGetDouble(JsonNode? node, out double value)
    {
        value = 0;
        if (node is JsonValue jv)
        {
            if (jv.TryGetValue<double>(out value))
            {
                return true;
            }

            if (jv.TryGetValue<string>(out var s) && double.TryParse(s, NumberStyles.Any, CultureInfo.InvariantCulture, out value))
            {
                return true;
            }
        }

        return false;
    }

    private static List<string> SplitTopLevel(string expr, string separator)
    {
        var parts = new List<string>();
        var depth = 0;
        var start = 0;
        for (var i = 0; i < expr.Length; i++)
        {
            var c = expr[i];
            if (c is '(' )
            {
                depth++;
            }
            else if (c is ')')
            {
                depth--;
            }
            else if (depth == 0 && i + separator.Length <= expr.Length && expr.Substring(i, separator.Length) == separator)
            {
                parts.Add(expr[start..i].Trim());
                i += separator.Length - 1;
                start = i + 1;
            }
        }

        parts.Add(expr[start..].Trim());
        return parts;
    }
}
