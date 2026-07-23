using LightNovelSelector.WinUI.Appearance;
using LightNovelSelector.WinUI.Helpers;
using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Controls;

namespace LightNovelSelector.WinUI;

public sealed partial class MainPage
{
    private bool _appearanceLoading;
    private bool _materialStateSubscribed;

    private async Task RunAppearanceSmokeTestAsync()
    {
        if (App.MainWindow is not { } window)
        {
            throw new InvalidOperationException("外观冒烟测试无法访问主窗口。");
        }

        foreach (var theme in new[] { "light", "dark", "system", "dark" })
        {
            window.ApplyTheme(theme);
            await Task.Delay(180);
            foreach (var material in new[]
                     {
                         WindowMaterial.Acrylic,
                         WindowMaterial.Mica,
                         WindowMaterial.Solid,
                     })
            {
                window.ApplyMaterial(material);
                await Task.Delay(180);
            }
        }

        ShellNavigation.SelectedItem = ActivityNavigationItem;
        await Task.Delay(220);
        ShellNavigation.SelectedItem = ShellNavigation.SettingsItem;
        await Task.Delay(220);
        ShellNavigation.SelectedItem = WorkspaceNavigationItem;
        await Task.Delay(220);
    }

    private void LoadAppearanceSettings()
    {
        _appearanceLoading = true;
        var theme = AppearancePreferences.LoadTheme();
        var material = AppearancePreferences.LoadMaterial();
        ThemeSelector.SelectedIndex = theme switch
        {
            "light" => 1,
            "dark" => 2,
            _ => 0,
        };
        MaterialSelector.SelectedIndex = material switch
        {
            WindowMaterial.Mica => 1,
            WindowMaterial.Solid => 2,
            _ => 0,
        };
        ReducedMotionToggle.IsOn = Motion.ReducedMotion;
        UpdateMaterialStatus();
        _appearanceLoading = false;
    }

    private void SubscribeToMaterialState()
    {
        if (_materialStateSubscribed || App.MainWindow is not { } window)
        {
            return;
        }
        window.MaterialStateChanged += OnMaterialStateChanged;
        window.ActualThemeChanged += OnActualThemeChanged;
        _materialStateSubscribed = true;
    }

    private void UnsubscribeFromMaterialState()
    {
        if (!_materialStateSubscribed || App.MainWindow is not { } window)
        {
            return;
        }
        window.MaterialStateChanged -= OnMaterialStateChanged;
        window.ActualThemeChanged -= OnActualThemeChanged;
        _materialStateSubscribed = false;
    }

    private void OnMaterialStateChanged(object? sender, EventArgs e) => UpdateMaterialStatus();

    private void OnActualThemeChanged(object? sender, EventArgs e) => UpdateSystemThemeStatus();

    private void UpdateMaterialStatus()
    {
        if (App.MainWindow is not { } window)
        {
            return;
        }
        MaterialStatusText.Text = window.MaterialState.StatusText;
        MaterialStatusText.Foreground = ResourceBrush(
            window.MaterialState.IsFallback ? "WarningTextBrush" : "AppAccentBrush"
        );
        UpdateSystemThemeStatus();
    }

    private void UpdateSystemThemeStatus()
    {
        if (App.MainWindow is not { } window)
        {
            return;
        }

        var effectiveTheme = window.ActualTheme == ElementTheme.Dark ? "深色" : "浅色";
        var selectedTheme = ThemeSelector.SelectedItem is ComboBoxItem item
            ? item.Tag as string
            : "system";
        SystemThemeStatusText.Text = selectedTheme == "system"
            ? $"当前跟随 Windows（{effectiveTheme}）"
            : $"当前固定为{effectiveTheme}";
    }

    private void OnThemeSelectionChanged(object sender, SelectionChangedEventArgs e)
    {
        if (_appearanceLoading || ThemeSelector.SelectedItem is not ComboBoxItem item)
        {
            return;
        }
        var theme = item.Tag as string ?? "system";
        App.MainWindow?.ApplyTheme(theme);
        UpdateSystemThemeStatus();
        if (!AppearancePreferences.TrySaveTheme(theme))
        {
            ShowToast("颜色模式已应用，但未能保存到当前账户。", ToastKind.Warning);
        }
    }

    private void OnMaterialSelectionChanged(object sender, SelectionChangedEventArgs e)
    {
        if (_appearanceLoading || MaterialSelector.SelectedItem is not ComboBoxItem item)
        {
            return;
        }
        var material = AppearancePreferences.FromSettingValue(item.Tag as string);
        App.MainWindow?.ApplyMaterial(material);
        UpdateMaterialStatus();
        if (!AppearancePreferences.TrySaveMaterial(material))
        {
            ShowToast("窗口材质已应用，但未能保存到当前账户。", ToastKind.Warning);
        }
    }

    private void OnReducedMotionToggled(object sender, RoutedEventArgs e)
    {
        if (_appearanceLoading)
        {
            return;
        }
        if (!Motion.TrySetReducedMotion(ReducedMotionToggle.IsOn))
        {
            ShowToast("动态效果偏好已应用，但未能保存到当前账户。", ToastKind.Warning);
            return;
        }
        ShowToast(
            ReducedMotionToggle.IsOn ? "已减少非必要动态效果。" : "已恢复界面动态效果。",
            ToastKind.Info
        );
    }

    private void OnRootLayoutSizeChanged(object sender, SizeChangedEventArgs e)
    {
        var compact = e.NewSize.Height < 760;
        WorkflowStepsPanel.Visibility = compact ? Visibility.Collapsed : Visibility.Visible;
        CompactWorkflowSummary.Visibility = compact ? Visibility.Visible : Visibility.Collapsed;
    }
}
