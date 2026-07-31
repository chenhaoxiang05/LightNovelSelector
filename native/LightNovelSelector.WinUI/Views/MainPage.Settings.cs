using LightNovelSelector.WinUI.Models;
using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Controls;

namespace LightNovelSelector.WinUI;

public sealed partial class MainPage
{
    private void LoadSettings(
        AppSettings settings,
        IReadOnlyList<MetadataProviderInfo> metadataProviders
    )
    {
        _settingsLoading = true;
        try
        {
            NetworkToggle.IsOn = settings.UseNetwork;
            RecursiveToggle.IsOn = settings.Recursive;
            AutoRenameToggle.IsOn = settings.AutoRename;
            Providers.Clear();
            foreach (var provider in metadataProviders)
            {
                Providers.Add(new EditableMetadataProvider(provider));
            }
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

    private void UpdateProviderHealth(IReadOnlyList<MetadataProviderInfo> metadataProviders)
    {
        var providersById = metadataProviders.ToDictionary(provider => provider.Id, StringComparer.Ordinal);
        foreach (var provider in Providers)
        {
            if (providersById.TryGetValue(provider.Id, out var info))
            {
                provider.UpdateHealth(info);
            }
        }
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

    private void OnProviderEnabledToggled(object sender, RoutedEventArgs e)
    {
        if (sender is ToggleSwitch toggle && toggle.DataContext is EditableMetadataProvider provider)
        {
            provider.Enabled = toggle.IsOn;
            MarkSettingsDirty();
        }
    }

    private void OnProviderPriorityChanged(NumberBox sender, NumberBoxValueChangedEventArgs args)
    {
        if (
            sender.DataContext is EditableMetadataProvider provider
            && double.IsFinite(args.NewValue)
        )
        {
            var priority = Math.Clamp(Math.Round(args.NewValue), 0, 1000);
            provider.Priority = priority;
            if (sender.Value != priority)
            {
                sender.Value = priority;
            }
            MarkSettingsDirty();
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
        var invalidProvider = Providers.FirstOrDefault(provider =>
            !double.IsFinite(provider.Priority)
            || provider.Priority < 0
            || provider.Priority > 1000
        );
        if (invalidProvider is not null)
        {
            throw new InvalidOperationException($"{invalidProvider.Name} 的优先级需要是 0 到 1000 之间的整数。");
        }

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
            ProviderSettings = Providers.Select(provider => new MetadataProviderSetting
            {
                ProviderId = provider.Id,
                Enabled = provider.Enabled,
                Priority = checked((int)Math.Round(provider.Priority)),
            }).ToArray(),
            CustomRules = Rules.Select(rule => new CustomRule
            {
                Pattern = rule.Pattern.Trim(),
                Series = rule.Series.Trim(),
            }).ToArray(),
        };
        var result = await _sidecar.SaveSettingsAsync(settings);
        _settingsInitialized = true;
        ApplySnapshot(result.State);
        LoadSettings(result.State.Settings, result.State.MetadataProviders);
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
        LoadSettings(_snapshot.Settings, _snapshot.MetadataProviders);
        ShowToast("已恢复为当前保存值。", ToastKind.Info);
    }
}
