namespace Vivhite.Tests.Acceptance;

internal static class AcceptanceAssert
{
    public static void True(bool condition, string message)
    {
        if (!condition)
        {
            throw new AcceptanceFailureException(message);
        }
    }

    public static void Equal<T>(T expected, T actual, string message)
        where T : notnull
    {
        if (!EqualityComparer<T>.Default.Equals(expected, actual))
        {
            throw new AcceptanceFailureException($"{message}{Environment.NewLine}Expected: {expected}{Environment.NewLine}Actual:   {actual}");
        }
    }

    public static void Empty<T>(IReadOnlyCollection<T> values, string message)
    {
        if (values.Count > 0)
        {
            throw new AcceptanceFailureException($"{message}{Environment.NewLine}{string.Join(Environment.NewLine, values)}");
        }
    }

    public static void SetEqual(
        IReadOnlyCollection<string> expected,
        IReadOnlyCollection<string> actual,
        string message)
    {
        var missing = expected.Except(actual, StringComparer.Ordinal).Order(StringComparer.Ordinal).ToArray();
        var unexpected = actual.Except(expected, StringComparer.Ordinal).Order(StringComparer.Ordinal).ToArray();
        if (missing.Length == 0 && unexpected.Length == 0)
        {
            return;
        }

        var details = new List<string> { message };
        if (missing.Length > 0)
        {
            details.Add($"Missing: {string.Join(", ", missing)}");
        }
        if (unexpected.Length > 0)
        {
            details.Add($"Unexpected: {string.Join(", ", unexpected)}");
        }
        throw new AcceptanceFailureException(string.Join(Environment.NewLine, details));
    }
}

internal sealed class AcceptanceFailureException(string message) : Exception(message);
