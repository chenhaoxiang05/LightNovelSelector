namespace LightNovelSelector.WinUI.ViewModels;

public enum WorkspaceLayoutMode
{
    Narrow,
    Compact,
    Wide,
}

public readonly record struct WorkspaceLayoutPresentation(
    WorkspaceLayoutMode Mode,
    bool ShowSideDetail,
    bool KeepNavigationPaneOpen,
    bool UseTwoColumnStats,
    bool StackFolderActions,
    bool StackFilters,
    bool StackOperationActions,
    bool UseCompactPadding,
    bool UseCompactWorkflow,
    bool UseWorkspaceScroll,
    double DetailWidth
);

public static class WorkspaceLayoutController
{
    public const double WideBreakpoint = 1280;
    public const double CompactBreakpoint = 800;
    public const double TwoColumnStatsBreakpoint = 760;
    public const double CompactPaddingBreakpoint = 960;
    public const double StackedFilterBreakpoint = 820;
    public const double StackedActionBreakpoint = 760;
    public const double ShortWindowBreakpoint = 760;
    public const double WorkspaceScrollHeightBreakpoint = 640;
    public const double NarrowWorkspaceScrollHeightBreakpoint = 820;

    public static WorkspaceLayoutPresentation Describe(double width, double height)
    {
        width = NormalizeDimension(width);
        height = NormalizeDimension(height);

        var mode = width >= WideBreakpoint
            ? WorkspaceLayoutMode.Wide
            : width >= CompactBreakpoint
                ? WorkspaceLayoutMode.Compact
                : WorkspaceLayoutMode.Narrow;
        var detailWidth = mode == WorkspaceLayoutMode.Wide
            ? width >= 1500 ? 380 : 340
            : Math.Clamp(width - 280, 320, 420);

        return new WorkspaceLayoutPresentation(
            mode,
            ShowSideDetail: mode == WorkspaceLayoutMode.Wide,
            KeepNavigationPaneOpen: mode == WorkspaceLayoutMode.Wide,
            UseTwoColumnStats: width < TwoColumnStatsBreakpoint,
            StackFolderActions: width < StackedActionBreakpoint,
            StackFilters: width < StackedFilterBreakpoint,
            StackOperationActions: width < StackedActionBreakpoint,
            UseCompactPadding: width < CompactPaddingBreakpoint,
            UseCompactWorkflow: height < ShortWindowBreakpoint,
            UseWorkspaceScroll: height < WorkspaceScrollHeightBreakpoint
                || (width < CompactBreakpoint && height < NarrowWorkspaceScrollHeightBreakpoint),
            DetailWidth: detailWidth
        );
    }

    private static double NormalizeDimension(double value) =>
        double.IsFinite(value) && value > 0 ? value : 0;
}
