using LightNovelSelector.WinUI.Models;
using LightNovelSelector.WinUI.ViewModels;
using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Controls;

namespace LightNovelSelector.WinUI;

public sealed partial class MainPage
{
    private bool _filterControlsLoading;

    private void RebuildPlanFilters()
    {
        var selectedSeries = SelectedFilterValue(SeriesFilter);
        _filterControlsLoading = true;
        SeriesFilter.Items.Clear();
        SeriesFilter.Items.Add(new ComboBoxItem { Content = "全部系列", Tag = string.Empty });
        foreach (var series in PlanFilterController.SeriesOptions(Plans))
        {
            SeriesFilter.Items.Add(new ComboBoxItem { Content = series, Tag = series });
        }

        var retainedItem = SeriesFilter.Items
            .OfType<ComboBoxItem>()
            .FirstOrDefault(item => string.Equals(item.Tag as string, selectedSeries, StringComparison.CurrentCultureIgnoreCase));
        SeriesFilter.SelectedItem = retainedItem ?? (ComboBoxItem)SeriesFilter.Items[0];
        if (StatusFilter.SelectedIndex < 0)
        {
            StatusFilter.SelectedIndex = 0;
        }
        _filterControlsLoading = false;
    }

    private void ApplyPlanFilters(int? selectedIndex = null)
    {
        if (!IsLoaded || _filterControlsLoading)
        {
            return;
        }

        selectedIndex ??= (ResultsList.SelectedItem as PlanItem)?.Index;
        var state = new PlanFilterState(
            ResultSearchBox.Text,
            SelectedFilterValue(SeriesFilter),
            SelectedFilterValue(StatusFilter)
        );
        VisiblePlans = PlanFilterController.Apply(Plans, state);
        ResultsList.ItemsSource = VisiblePlans;

        ResultCountText.Text = state.IsActive
            ? $"{VisiblePlans.Count} / {Plans.Count} 个文件"
            : $"{Plans.Count} 个文件";
        ResultsEmptyState.Visibility = VisiblePlans.Count == 0 ? Visibility.Visible : Visibility.Collapsed;
        ResultsEmptyTitleText.Text = Plans.Count == 0 ? "还没有分类预览" : "没有符合条件的文件";
        ResultsEmptyCopyText.Text = Plans.Count == 0
            ? string.IsNullOrWhiteSpace(_snapshot.Folder)
                ? "选择目录后开始扫描"
                : "点击“扫描并预览”生成分类预览"
            : "调整或清除当前筛选条件";
        ClearFiltersButton.IsEnabled = state.IsActive;

        ResultsList.SelectedItem = selectedIndex is null
            ? null
            : VisiblePlans.FirstOrDefault(item => item.Index == selectedIndex);
        if (ResultsList.SelectedItem is null && _detail is not null)
        {
            ShowDetailEmpty();
        }
    }

    private void OnResultSearchTextChanged(AutoSuggestBox sender, AutoSuggestBoxTextChangedEventArgs args)
    {
        if (_filterControlsLoading)
        {
            return;
        }
        _filterTimer.Stop();
        _filterTimer.Start();
    }

    private void OnFilterTimerTick(object? sender, object e)
    {
        _filterTimer.Stop();
        ApplyPlanFilters();
    }

    private void OnPlanFilterSelectionChanged(object sender, SelectionChangedEventArgs e)
    {
        if (_filterControlsLoading)
        {
            return;
        }
        _filterTimer.Stop();
        ApplyPlanFilters();
    }

    private void OnClearFiltersClick(object sender, RoutedEventArgs e)
    {
        _filterTimer.Stop();
        _filterControlsLoading = true;
        ResultSearchBox.Text = string.Empty;
        SeriesFilter.SelectedIndex = 0;
        StatusFilter.SelectedIndex = 0;
        _filterControlsLoading = false;
        ApplyPlanFilters();
        ResultSearchBox.Focus(FocusState.Programmatic);
    }

    private static string SelectedFilterValue(ComboBox comboBox) =>
        (comboBox.SelectedItem as ComboBoxItem)?.Tag as string ?? string.Empty;
}
