using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Controls;

namespace LightNovelSelector.WinUI;

public sealed partial class MainPage
{
    private bool _settingsLoading;
    private bool _settingsDirty;

    private void OnSettingsToggleChanged(object sender, RoutedEventArgs e) =>
        MarkSettingsDirty();

    private void OnSettingsTextChanged(object sender, TextChangedEventArgs e) =>
        MarkSettingsDirty();

    private void MarkSettingsDirty()
    {
        if (IsLoaded && !_settingsLoading)
        {
            SetSettingsDirty(true);
        }
    }

    private void SetSettingsDirty(bool dirty, string? persistenceWarning = null)
    {
        _settingsDirty = dirty;
        if (persistenceWarning is not null)
        {
            SettingsDirtyIcon.Glyph = "\uE7BA";
            SettingsDirtyText.Text = "本次会话已采用，但尚未写入磁盘";
            SettingsDirtyText.Foreground = ResourceBrush("WarningTextBrush");
            SettingsDirtyIcon.Foreground = ResourceBrush("WarningTextBrush");
        }
        else if (dirty)
        {
            SettingsDirtyIcon.Glyph = "\uE70F";
            SettingsDirtyText.Text = "有未保存的识别设置";
            SettingsDirtyText.Foreground = ResourceBrush("AppAccentBrush");
            SettingsDirtyIcon.Foreground = ResourceBrush("AppAccentBrush");
        }
        else
        {
            SettingsDirtyIcon.Glyph = "\uE73E";
            SettingsDirtyText.Text = "识别设置已保存";
            SettingsDirtyText.Foreground = ResourceBrush("TextFillColorSecondaryBrush");
            SettingsDirtyIcon.Foreground = ResourceBrush("SuccessTextBrush");
        }

        var running = _snapshot.Operation.State == "running";
        SaveSettingsButton.IsEnabled = dirty && !running;
    }
}
