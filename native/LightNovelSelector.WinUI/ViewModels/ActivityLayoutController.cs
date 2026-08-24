namespace LightNovelSelector.WinUI.ViewModels;

public enum ActivityLayoutMode
{
    Split,
    Stacked,
}

public readonly record struct ActivityLayoutPresentation(
    ActivityLayoutMode Mode,
    bool StackSummaryActions,
    bool UseScroll,
    double HistoryWidth,
    double MainMinimumHeight,
    double HistoryViewportHeight,
    double ReportItemsViewportHeight,
    double LogsViewportHeight
);

public static class ActivityLayoutController
{
    public const double StackedContentBreakpoint = 960;
    public const double StackedSummaryBreakpoint = 760;
    public const double ShortWindowBreakpoint = 720;
    public const double StackedHistoryViewportHeight = 220;
    public const double StackedReportItemsViewportHeight = 260;
    public const double StackedLogsViewportHeight = 200;

    private const double RegionSpacing = 12;

    public static ActivityLayoutPresentation Describe(double width, double height)
    {
        width = NormalizeDimension(width);
        height = NormalizeDimension(height);

        var mode = width < StackedContentBreakpoint
            ? ActivityLayoutMode.Stacked
            : ActivityLayoutMode.Split;
        var stacked = mode == ActivityLayoutMode.Stacked;
        var useScroll = stacked || height < ShortWindowBreakpoint;
        var stackedMainHeight = StackedHistoryViewportHeight
            + StackedReportItemsViewportHeight
            + StackedLogsViewportHeight
            + (2 * RegionSpacing);

        return new ActivityLayoutPresentation(
            mode,
            StackSummaryActions: width < StackedSummaryBreakpoint,
            UseScroll: useScroll,
            HistoryWidth: stacked ? 0 : 270,
            MainMinimumHeight: stacked ? stackedMainHeight : useScroll ? 430 : 0,
            HistoryViewportHeight: stacked ? StackedHistoryViewportHeight : 0,
            ReportItemsViewportHeight: stacked ? StackedReportItemsViewportHeight : 0,
            LogsViewportHeight: stacked ? StackedLogsViewportHeight : 0
        );
    }

    private static double NormalizeDimension(double value) =>
        double.IsFinite(value) && value > 0 ? value : 0;
}
