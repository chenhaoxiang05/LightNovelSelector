using LightNovelSelector.WinUI.Models;

namespace LightNovelSelector.WinUI.ViewModels;

public readonly record struct PlanFilterState(string Query, string Series, string Status)
{
    public bool IsActive =>
        !string.IsNullOrWhiteSpace(Query)
        || !string.IsNullOrWhiteSpace(Series)
        || !string.IsNullOrWhiteSpace(Status);
}

public static class PlanFilterController
{
    public static IReadOnlyList<PlanItem> Apply(
        IEnumerable<PlanItem> plans,
        PlanFilterState state
    )
    {
        var query = state.Query.Trim();
        return plans.Where(plan =>
                Matches(plan.SeriesName, state.Series)
                && Matches(plan.Status, state.Status)
                && (
                    query.Length == 0
                    || Contains(plan.FileName, query)
                    || Contains(plan.BookTitle, query)
                    || Contains(plan.SeriesName, query)
                    || Contains(plan.AuthorsLabel, query)
                    || Contains(plan.LanguageLabel, query)
                    || Contains(plan.TagsLabel, query)
                    || Contains(plan.TargetName, query)
                    || Contains(plan.ResolverSource, query)
                )
            )
            .ToArray();
    }

    public static IReadOnlyList<string> SeriesOptions(IEnumerable<PlanItem> plans) =>
        plans.Select(plan => plan.SeriesName)
            .Where(name => !string.IsNullOrWhiteSpace(name))
            .Distinct(StringComparer.CurrentCultureIgnoreCase)
            .OrderBy(name => name, StringComparer.CurrentCultureIgnoreCase)
            .ToArray();

    private static bool Contains(string? value, string query) =>
        !string.IsNullOrEmpty(value)
        && value.Contains(query, StringComparison.CurrentCultureIgnoreCase);

    private static bool Matches(string? value, string filter) =>
        string.IsNullOrWhiteSpace(filter)
        || string.Equals(value, filter, StringComparison.CurrentCultureIgnoreCase);
}
