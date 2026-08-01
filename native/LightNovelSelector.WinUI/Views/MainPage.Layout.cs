using LightNovelSelector.WinUI.ViewModels;
using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Controls;

namespace LightNovelSelector.WinUI;

public sealed partial class MainPage
{
    private WorkspaceLayoutPresentation? _workspaceLayout;

    private void OnRootLayoutSizeChanged(object sender, SizeChangedEventArgs e)
    {
        ApplyWorkspaceLayout(
            WorkspaceLayoutController.Describe(e.NewSize.Width, e.NewSize.Height)
        );
    }

    private void ApplyWorkspaceLayout(WorkspaceLayoutPresentation layout)
    {
        if (_workspaceLayout == layout)
        {
            return;
        }

        var keepOverlayDetailOpen = _workspaceLayout is { ShowSideDetail: false }
            && !layout.ShowSideDetail
            && DetailSplitView.IsPaneOpen
            && _detail is not null;
        var resetWorkspaceScroll = _workspaceLayout is { UseWorkspaceScroll: true }
            && !layout.UseWorkspaceScroll;
        _workspaceLayout = layout;
        ShellNavigation.IsPaneOpen = layout.KeepNavigationPaneOpen;
        ShellContentGrid.Padding = layout.UseCompactPadding
            ? new Thickness(16, 14, 16, 18)
            : new Thickness(26, 18, 26, 24);

        DetailSplitView.DisplayMode = layout.ShowSideDetail
            ? SplitViewDisplayMode.Inline
            : SplitViewDisplayMode.Overlay;
        DetailSplitView.OpenPaneLength = layout.DetailWidth;
        DetailSplitView.IsPaneOpen = layout.ShowSideDetail || keepOverlayDetailOpen;
        DetailCard.Style = Application.Current.Resources[
            layout.ShowSideDetail
                ? "DetailRegionBorderStyle"
                : "OverlayDetailRegionBorderStyle"
        ] as Style;
        DetailPane.SetCompactMode(!layout.ShowSideDetail);
        CompactDetailButton.Visibility = layout.ShowSideDetail
            ? Visibility.Collapsed
            : Visibility.Visible;
        UpdateCompactDetailButtonState();

        WorkspaceView.MinHeight = layout.UseWorkspaceScroll ? 860 : 0;
        WorkspaceScrollViewer.VerticalScrollMode = layout.UseWorkspaceScroll
            ? ScrollMode.Enabled
            : ScrollMode.Disabled;
        WorkspaceScrollViewer.VerticalScrollBarVisibility = layout.UseWorkspaceScroll
            ? ScrollBarVisibility.Auto
            : ScrollBarVisibility.Hidden;
        if (resetWorkspaceScroll)
        {
            WorkspaceScrollViewer.ChangeView(
                horizontalOffset: null,
                verticalOffset: 0,
                zoomFactor: null,
                disableAnimation: true
            );
        }

        ApplyStatsLayout(layout.UseTwoColumnStats);
        ApplyFolderLayout(layout.StackFolderActions);
        ApplyFilterLayout(layout.StackFilters);
        ApplyOperationLayout(layout.StackOperationActions);
        ApplyPaneFooterLayout(ShellNavigation.IsPaneOpen, layout.UseCompactWorkflow);
    }

    private void ApplyStatsLayout(bool useTwoColumns)
    {
        for (var index = 0; index < StatsGrid.ColumnDefinitions.Count; index++)
        {
            StatsGrid.ColumnDefinitions[index].Width = useTwoColumns && index >= 2
                ? new GridLength(0)
                : new GridLength(1, GridUnitType.Star);
        }

        PositionMetricTile(ReadyMetricTile, row: 0, column: 0);
        PositionMetricTile(SeriesMetricTile, row: 0, column: 1);
        PositionMetricTile(
            DuplicateMetricTile,
            row: useTwoColumns ? 1 : 0,
            column: useTwoColumns ? 0 : 2
        );
        PositionMetricTile(
            AttentionMetricTile,
            row: useTwoColumns ? 1 : 0,
            column: useTwoColumns ? 1 : 3
        );
    }

    private static void PositionMetricTile(Border tile, int row, int column)
    {
        Grid.SetRow(tile, row);
        Grid.SetColumn(tile, column);
    }

    private void ApplyFolderLayout(bool stackActions)
    {
        Grid.SetRow(FolderActions, stackActions ? 1 : 0);
        Grid.SetColumn(FolderActions, stackActions ? 0 : 2);
        Grid.SetColumnSpan(FolderActions, stackActions ? 3 : 1);
        FolderActions.Margin = stackActions ? new Thickness(60, 0, 0, 0) : new Thickness(0);
    }

    private void ApplyFilterLayout(bool stackFilters)
    {
        if (stackFilters)
        {
            FilterGrid.ColumnDefinitions[0].Width = new GridLength(1, GridUnitType.Star);
            FilterGrid.ColumnDefinitions[1].Width = new GridLength(1, GridUnitType.Star);
            FilterGrid.ColumnDefinitions[2].Width = new GridLength(1, GridUnitType.Star);
            FilterGrid.ColumnDefinitions[3].Width = new GridLength(1, GridUnitType.Star);
            FilterGrid.ColumnDefinitions[4].Width = new GridLength(36);

            PositionFilter(ResultSearchBox, row: 0, column: 0, columnSpan: 5);
            PositionFilter(SeriesFilter, row: 1, column: 0, columnSpan: 2);
            PositionFilter(StatusFilter, row: 1, column: 2, columnSpan: 2);
            PositionFilter(ClearFiltersButton, row: 1, column: 4);
            FilterScopeInfoIcon.Visibility = Visibility.Collapsed;
            return;
        }

        FilterGrid.ColumnDefinitions[0].Width = new GridLength(1, GridUnitType.Star);
        FilterGrid.ColumnDefinitions[1].Width = new GridLength(180);
        FilterGrid.ColumnDefinitions[2].Width = new GridLength(150);
        FilterGrid.ColumnDefinitions[3].Width = new GridLength(36);
        FilterGrid.ColumnDefinitions[4].Width = GridLength.Auto;

        PositionFilter(ResultSearchBox, row: 0, column: 0);
        PositionFilter(SeriesFilter, row: 0, column: 1);
        PositionFilter(StatusFilter, row: 0, column: 2);
        PositionFilter(ClearFiltersButton, row: 0, column: 3);
        PositionFilter(FilterScopeInfoIcon, row: 0, column: 4);
        FilterScopeInfoIcon.Visibility = Visibility.Visible;
    }

    private static void PositionFilter(
        FrameworkElement element,
        int row,
        int column,
        int columnSpan = 1
    )
    {
        Grid.SetRow(element, row);
        Grid.SetColumn(element, column);
        Grid.SetColumnSpan(element, columnSpan);
    }

    private void ApplyOperationLayout(bool stackActions)
    {
        Grid.SetRow(OperationActions, stackActions ? 1 : 0);
        Grid.SetColumn(OperationActions, stackActions ? 0 : 2);
        Grid.SetColumnSpan(OperationActions, stackActions ? 3 : 1);
        OperationActions.Margin = stackActions ? new Thickness(50, 0, 0, 0) : new Thickness(0);
    }

    private void ApplyPaneFooterLayout(bool paneExpanded, bool useCompactWorkflow)
    {
        WorkflowRail.ApplyPaneLayout(paneExpanded, useCompactWorkflow);
    }

    private void OnNavigationPaneOpened(NavigationView sender, object args) =>
        RefreshPaneFooterLayout();

    private void OnNavigationPaneClosed(NavigationView sender, object args) =>
        RefreshPaneFooterLayout();

    private void RefreshPaneFooterLayout()
    {
        if (_workspaceLayout is { } layout)
        {
            ApplyPaneFooterLayout(ShellNavigation.IsPaneOpen, layout.UseCompactWorkflow);
        }
    }
}
