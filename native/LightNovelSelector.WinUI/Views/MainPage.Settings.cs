using LightNovelSelector.WinUI.Models;
using Microsoft.UI.Xaml;

namespace LightNovelSelector.WinUI;

public sealed partial class MainPage
{
    private void LoadSettings(AppSettings settings)
    {
        _settingsLoading = true;
        try
        {
            NetworkToggle.IsOn = settings.UseNetwork;
            RecursiveToggle.IsOn = settings.Recursive;
            AutoRenameToggle.IsOn = settings.AutoRename;
            Rules.Clear();
            foreach (var rule in settings.CustomRules)
            {
                Rules.Add(new EditableRule(rule.Pattern, rule.Series));
            }
            UpdateRulesEmptyState();
        }
        finally
        {
            _settingsLoading = false;
        }
        SetSettingsDirty(false);
    }

    private void UpdateRulesEmptyState() =>
        RulesEmptyText.Visibility = Rules.Count == 0 ? Visibility.Visible : Visibility.Collapsed;

    private void OnAddRuleClick(object sender, RoutedEventArgs e)
    {
        if (Rules.Count >= 200)
        {
            ShowToast("自定义规则最多 200 条。", ToastKind.Warning);
            return;
        }
        Rules.Add(new EditableRule());
    }

    private void OnDeleteRuleClick(object sender, RoutedEventArgs e)
    {
        if (sender is FrameworkElement { DataContext: EditableRule rule })
        {
            Rules.Remove(rule);
        }
    }

    private async void OnSaveSettingsClick(object sender, RoutedEventArgs e)
    {
        try
        {
            await SaveCurrentSettingsAsync(showResult: true);
        }
        catch (Exception exc)
        {
            ShowToast(exc.Message, ToastKind.Error);
        }
    }

    private async Task SaveCurrentSettingsAsync(bool showResult)
    {
        var invalidIndex = Rules
            .Select((rule, index) => (rule, index))
            .FirstOrDefault(item => string.IsNullOrWhiteSpace(item.rule.Pattern) || string.IsNullOrWhiteSpace(item.rule.Series));
        if (invalidIndex.rule is not null)
        {
            throw new InvalidOperationException($"第 {invalidIndex.index + 1} 条规则需要同时填写匹配文本和目标系列。");
        }

        var settings = new AppSettings
        {
            UseNetwork = NetworkToggle.IsOn,
            Recursive = RecursiveToggle.IsOn,
            AutoRename = AutoRenameToggle.IsOn,
            LastFolder = _snapshot.Folder,
            CustomRules = Rules.Select(rule => new CustomRule
            {
                Pattern = rule.Pattern.Trim(),
                Series = rule.Series.Trim(),
            }).ToArray(),
        };
        var result = await _sidecar.SaveSettingsAsync(settings);
        _settingsInitialized = true;
        ApplySnapshot(result.State);
        SetSettingsDirty(!result.Saved, result.Warning);
        if (!showResult)
        {
            return;
        }
        if (result.Saved)
        {
            ShowToast("设置已保存。", ToastKind.Success);
        }
        else
        {
            ShowToast($"设置已用于本次会话，但未能写入磁盘：{result.Warning}", ToastKind.Warning, 6000);
        }
    }

    private void OnResetSettingsClick(object sender, RoutedEventArgs e)
    {
        LoadSettings(_snapshot.Settings);
        ShowToast("已恢复为当前保存值。", ToastKind.Info);
    }
}
