using LightNovelSelector.WinUI.ViewModels;
using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Controls;
using Microsoft.UI.Xaml.Input;
using Microsoft.UI.Xaml.Media;
using Windows.System;

namespace LightNovelSelector.WinUI;

public sealed partial class MainPage
{
    private enum ShortcutFocusTarget
    {
        None,
        WorkspacePrimary,
        ActivityPrimary,
        SettingsPrimary,
        Search,
    }

    private readonly record struct FocusRegion(FrameworkElement Container, Control[] Targets);

    private bool _suppressNextNavigationMotion;
    private ShortcutFocusTarget _focusAfterShortcutNavigation;

    private async void OnSectionShortcutInvoked(
        KeyboardAccelerator sender,
        KeyboardAcceleratorInvokedEventArgs args
    )
    {
        var selection = sender.Key switch
        {
            VirtualKey.Number1 => (
                Item: WorkspaceNavigationItem as NavigationViewItem,
                Focus: ShortcutFocusTarget.WorkspacePrimary
            ),
            VirtualKey.Number2 => (
                Item: ActivityNavigationItem as NavigationViewItem,
                Focus: ShortcutFocusTarget.ActivityPrimary
            ),
            VirtualKey.Number3 => (
                Item: ShellNavigation.SettingsItem as NavigationViewItem,
                Focus: ShortcutFocusTarget.SettingsPrimary
            ),
            _ => (Item: null, Focus: ShortcutFocusTarget.None),
        };

        if (selection.Item is null)
        {
            return;
        }

        args.Handled = true;
        await SelectNavigationItemFromKeyboardAsync(selection.Item, selection.Focus);
    }

    private async void OnSearchShortcutInvoked(
        KeyboardAccelerator sender,
        KeyboardAcceleratorInvokedEventArgs args
    )
    {
        args.Handled = true;
        await SelectNavigationItemFromKeyboardAsync(
            WorkspaceNavigationItem,
            ShortcutFocusTarget.Search
        );
    }

    private void OnCycleRegionForwardInvoked(
        KeyboardAccelerator sender,
        KeyboardAcceleratorInvokedEventArgs args
    ) => args.Handled = CycleFocusRegion(reverse: false);

    private void OnCycleRegionBackwardInvoked(
        KeyboardAccelerator sender,
        KeyboardAcceleratorInvokedEventArgs args
    ) => args.Handled = CycleFocusRegion(reverse: true);

    private void OnShellNavigationPreviewKeyDown(object sender, KeyRoutedEventArgs args)
    {
        if (args.Key is not (
            VirtualKey.Up
            or VirtualKey.Down
            or VirtualKey.Left
            or VirtualKey.Right
            or VirtualKey.Home
            or VirtualKey.End
            or VirtualKey.Enter
            or VirtualKey.Space
        ))
        {
            return;
        }

        _suppressNextNavigationMotion = true;
        DispatcherQueue.TryEnqueue(
            Microsoft.UI.Dispatching.DispatcherQueuePriority.Low,
            () => _suppressNextNavigationMotion = false
        );
    }

    private async Task SelectNavigationItemFromKeyboardAsync(
        NavigationViewItem navigationItem,
        ShortcutFocusTarget focusTarget
    )
    {
        _focusAfterShortcutNavigation = focusTarget;
        if (ReferenceEquals(ShellNavigation.SelectedItem, navigationItem))
        {
            await FocusPendingShortcutTargetAsync();
            return;
        }

        _suppressNextNavigationMotion = true;
        ShellNavigation.SelectedItem = navigationItem;
    }

    private async Task FocusPendingShortcutTargetAsync()
    {
        var target = _focusAfterShortcutNavigation;
        _focusAfterShortcutNavigation = ShortcutFocusTarget.None;
        if (target == ShortcutFocusTarget.None)
        {
            return;
        }

        await Task.Yield();
        RootLayout.UpdateLayout();

        Control[] controls = target switch
        {
            ShortcutFocusTarget.WorkspacePrimary =>
                [ChooseFolderButton, ResultSearchBox, WorkspaceNavigationItem],
            ShortcutFocusTarget.ActivityPrimary =>
                [RefreshReportButton, ReportHistoryList, ActivityNavigationItem],
            ShortcutFocusTarget.SettingsPrimary =>
                [
                    NetworkToggle,
                    ThemeSelector,
                    ShellNavigation.SettingsItem as Control ?? WorkspaceNavigationItem,
                ],
            ShortcutFocusTarget.Search => [ResultSearchBox, WorkspaceNavigationItem],
            _ => [],
        };
        if (!controls.Any(TryFocus))
        {
            return;
        }

        if (target == ShortcutFocusTarget.Search)
        {
            FindDescendant<TextBox>(ResultSearchBox)?.SelectAll();
        }
    }

    private bool CycleFocusRegion(bool reverse)
    {
        var regions = GetVisibleFocusRegions();
        if (regions.Count == 0)
        {
            return false;
        }

        var focused = XamlRoot is null
            ? null
            : FocusManager.GetFocusedElement(XamlRoot) as DependencyObject;
        var currentIndex = -1;
        for (var index = 0; index < regions.Count; index++)
        {
            if (focused is not null && IsDescendantOrSelf(focused, regions[index].Container))
            {
                currentIndex = index;
                break;
            }
        }

        var nextIndex = FocusCycleController.NextIndex(currentIndex, regions.Count, reverse);
        for (var attempt = 0; attempt < regions.Count; attempt++)
        {
            var region = regions[nextIndex];
            if (region.Targets.Any(TryFocus))
            {
                return true;
            }
            nextIndex = FocusCycleController.NextIndex(nextIndex, regions.Count, reverse);
        }

        return false;
    }

    private List<FocusRegion> GetVisibleFocusRegions()
    {
        var regions = new List<FocusRegion>();
        AddFocusRegion(regions, ShellNavigation, GetSelectedNavigationItem());

        if (WorkspaceView.Visibility == Visibility.Visible)
        {
            AddFocusRegion(regions, FolderCard, ChooseFolderButton, ScanButton, OpenFolderButton);
            AddFocusRegion(
                regions,
                ResultsCard,
                ResultSearchBox,
                ResultsList,
                CompactDetailButton
            );
            AddFocusRegion(
                regions,
                DetailCard,
                SeriesEditBox,
                CandidateList,
                SaveCorrectionButton,
                RevealFileButton
            );
            AddFocusRegion(regions, OperationCard, ApplyButton, UndoButton, CancelButton);
        }
        else if (ActivityView.Visibility == Visibility.Visible)
        {
            AddFocusRegion(regions, ActivityHeader, RefreshReportButton);
            AddFocusRegion(regions, ReportHistoryCard, ReportHistoryList);
            AddFocusRegion(regions, ReportItemsCard, ReportItemsList);
            AddFocusRegion(regions, LogsCard, LogsList);
        }
        else if (SettingsView.Visibility == Visibility.Visible)
        {
            AddFocusRegion(
                regions,
                SettingsContent,
                NetworkToggle,
                ThemeSelector,
                AddRuleButton,
                RulesList
            );
            AddFocusRegion(
                regions,
                SettingsSaveBar,
                SaveSettingsButton,
                ResetSettingsButton
            );
        }

        return regions;
    }

    private NavigationViewItem? GetSelectedNavigationItem()
    {
        if (ReferenceEquals(ShellNavigation.SelectedItem, ShellNavigation.SettingsItem))
        {
            return ShellNavigation.SettingsItem as NavigationViewItem;
        }

        return ShellNavigation.SelectedItem as NavigationViewItem ?? WorkspaceNavigationItem;
    }

    private static void AddFocusRegion(
        ICollection<FocusRegion> regions,
        FrameworkElement container,
        params Control?[] targets
    )
    {
        if (!IsVisible(container))
        {
            return;
        }

        var availableTargets = targets
            .Where(target => target is not null)
            .Cast<Control>()
            .ToArray();
        if (availableTargets.Length > 0)
        {
            regions.Add(new FocusRegion(container, availableTargets));
        }
    }

    private static bool TryFocus(Control control)
    {
        if (!control.IsEnabled || !IsVisible(control))
        {
            return false;
        }

        return control.Focus(FocusState.Keyboard);
    }

    private static bool IsVisible(FrameworkElement element)
    {
        DependencyObject? current = element;
        while (current is FrameworkElement frameworkElement)
        {
            if (frameworkElement.Visibility != Visibility.Visible)
            {
                return false;
            }
            current = VisualTreeHelper.GetParent(current);
        }
        return true;
    }

    private static bool IsDescendantOrSelf(DependencyObject element, DependencyObject ancestor)
    {
        DependencyObject? current = element;
        while (current is not null)
        {
            if (ReferenceEquals(current, ancestor))
            {
                return true;
            }
            current = VisualTreeHelper.GetParent(current);
        }
        return false;
    }

    private static T? FindDescendant<T>(DependencyObject root)
        where T : DependencyObject
    {
        for (var index = 0; index < VisualTreeHelper.GetChildrenCount(root); index++)
        {
            var child = VisualTreeHelper.GetChild(root, index);
            if (child is T match)
            {
                return match;
            }

            var descendant = FindDescendant<T>(child);
            if (descendant is not null)
            {
                return descendant;
            }
        }

        return null;
    }
}
