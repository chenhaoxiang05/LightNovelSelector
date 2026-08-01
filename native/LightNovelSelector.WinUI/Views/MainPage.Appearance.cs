using LightNovelSelector.WinUI.Appearance;
using LightNovelSelector.WinUI.Helpers;
using LightNovelSelector.WinUI.Models;
using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Controls;

namespace LightNovelSelector.WinUI;

public sealed partial class MainPage
{
    private bool _appearanceLoading;
    private bool _materialStateSubscribed;

    private void LoadAppearanceSmokeReport()
    {
        _reportRequestSerial++;
        _updatingReportHistory = true;
        try
        {
            ReportHistory.Clear();
            ReportHistory.Add(
                new ReportHistoryEntry
                {
                    ReportId = "0123456789abcdef0123456789abcdef",
                    Path = @"D:\Books\classification_report.json",
                    FileName = "classification_report.json",
                    CreatedAt = "2026-07-20T20:22:40+08:00",
                    Version = "2.1.0-dev.14",
                    IsLatest = true,
                    CanUndo = true,
                    Status = "available",
                    StatusLabel = "可撤销",
                    Summary = new ReportStats
                    {
                        Total = 3,
                        Moved = 2,
                        Skipped = 1,
                    },
                }
            );
            ReportHistory.Add(
                new ReportHistoryEntry
                {
                    ReportId = "abcdef0123456789abcdef0123456789",
                    Path = @"D:\Books\.lightnovel-selector\history\classification_report-old.json",
                    FileName = "classification_report-old.json",
                    CreatedAt = "2026-07-19T18:10:00+08:00",
                    Version = "2.1.0-dev.2",
                    UndoCompleted = true,
                    Status = "undone",
                    StatusLabel = "已撤销",
                    Summary = new ReportStats
                    {
                        Total = 2,
                        Moved = 2,
                    },
                }
            );
            _selectedReport = ReportHistory[0];
            ReportHistoryList.SelectedItem = _selectedReport;
        }
        finally
        {
            _updatingReportHistory = false;
        }

        ReportHistoryEmptyState.Visibility = Visibility.Collapsed;
        ReportHistoryStatusText.Text = "共 2 个批次";
        ReportHistoryWarningText.Visibility = Visibility.Collapsed;
        ReportStatusText.Text = @"生成于 2026-07-20 20:22:40 · D:\Books\classification_report.json";
        ReportMovedText.Text = "移动 2";
        ReportSkippedText.Text = "跳过 1";
        ReportDuplicateText.Text = "重复 0";
        ReportErrorText.Text = "错误 0";
        ReportItems.Clear();
        ReportItems.Add(
            new ReportItem
            {
                SourcePath = @"D:\Books\青春物语 第03卷.epub",
                TargetPath = @"D:\Books\青春物语\青春物语 第03卷.epub",
                ActualTargetPath = @"D:\Books\青春物语\青春物语 第03卷.epub",
                Status = "moved",
                Operation = "moved",
            }
        );
        ReportItems.Add(
            new ReportItem
            {
                SourcePath = @"D:\Books\青春物语 第04卷.epub",
                TargetPath = @"D:\Books\青春物语\青春物语 第04卷.epub",
                Status = "duplicate",
                Operation = "skipped",
            }
        );
        ReportItemsEmptyState.Visibility = Visibility.Collapsed;
        UpdateReportActionState();
    }

    private async Task RunAppearanceSmokeTestAsync()
    {
        if (App.MainWindow is not { } window)
        {
            throw new InvalidOperationException("外观冒烟测试无法访问主窗口。");
        }

        LoadAppearanceSmokeWorkspace();
        var smokeDetail = new BookDetail
        {
            Index = 0,
            PlansRevision = 1,
            Identity = new BookIdentity
            {
                Title = "青春物语 第03卷",
                SeriesName = "青春物语",
                Authors = ["示例作者"],
                VolumeNumber = 3,
                Language = "zh-Hans",
                Tags = ["校园", "青春"],
            },
            Title = "青春物语 第03卷",
            Summary = "用于验证候选比较、批量修正和玻璃主题下文字层级的本地测试详情。",
            CoverSource = "无封面",
            FileName = "青春物语 第03卷.epub",
            SourcePath = @"D:\Books\青春物语 第03卷.epub",
            TargetPath = @"D:\Books\青春物语\青春物语 第03卷.epub",
            SeriesName = "青春物语",
            Authors = ["示例作者"],
            AuthorsLabel = "示例作者",
            VolumeNumber = 3,
            VolumeLabel = "第 3 卷",
            Language = "zh-Hans",
            LanguageLabel = "简体中文",
            Tags = ["校园", "青春"],
            TagsLabel = "校园 · 青春",
            ResolverSource = "Bangumi",
            ConfidenceLabel = "86%",
            ConfidenceLevel = "高",
            ClassificationReason = "Bangumi 返回了当前最可靠的系列匹配。",
            ClassificationEvidence = ["标题相似度 93%", "识别到第 3 卷", "检测到语言信息"],
            Status = "ready",
            StatusLabel = "准备整理",
            Candidates =
            [
                new SeriesCandidate
                {
                    Title = "青春物语 第03卷",
                    SeriesName = "青春物语",
                    Source = "Bangumi",
                    Confidence = 0.86,
                    ConfidenceLabel = "86%",
                    IsCurrent = true,
                    CurrentLabel = "当前",
                },
                new SeriesCandidate
                {
                    Title = "我的青春恋爱物语果然有问题 第03卷",
                    SeriesName = "我的青春恋爱物语果然有问题",
                    Source = "本地识别",
                    Confidence = 0.62,
                    ConfidenceLabel = "62%",
                },
            ],
            MatchingSeriesCount = 3,
            CanLoadCandidates = true,
        };
        _detail = smokeDetail;
        await DetailPane.RenderAsync(smokeDetail);
        UpdateCandidateLookupState();
        UpdateCorrectionButtonState();
        DetailPane.SetBatchScopeChecked(true);
        await Task.Delay(180);
        DetailPane.SetBatchScopeChecked(false);
        if (Environment.GetEnvironmentVariable("LN_SELECTOR_WINUI_TEST_OPEN_DETAIL") == "1")
        {
            DetailSplitView.IsPaneOpen = true;
            UpdateCompactDetailButtonState();
            await Task.Yield();
        }
        if (
            int.TryParse(
                Environment.GetEnvironmentVariable("LN_SELECTOR_WINUI_APPEARANCE_HOLD_MS"),
                out var requestedHold
            )
            && requestedHold > 0
        )
        {
            await Task.Delay(Math.Min(requestedHold, 15_000));
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
        window.ApplyTheme(AppearancePreferences.LoadTheme());
        window.ApplyMaterial(AppearancePreferences.LoadMaterial());
        await Task.Delay(220);

        ShellNavigation.SelectedItem = ActivityNavigationItem;
        await Task.Delay(500);
        ShellNavigation.SelectedItem = ShellNavigation.SettingsItem;
        await Task.Delay(220);
        ShellNavigation.SelectedItem = WorkspaceNavigationItem;
        await Task.Delay(220);
    }

    private void LoadAppearanceSmokeWorkspace()
    {
        var plans = new[]
        {
            new PlanItem
            {
                Index = 0,
                FileName = "刀剑神域 第01卷.txt",
                Extension = ".txt",
                SourcePath = @"D:\Books\刀剑神域 第01卷.txt",
                BookTitle = "刀剑神域 第01卷",
                SeriesName = "刀剑神域",
                SeriesKey = "刀剑神域",
                TargetDir = @"D:\Books\刀剑神域",
                TargetPath = @"D:\Books\刀剑神域\刀剑神域 第01卷.txt",
                TargetName = "刀剑神域 第01卷.txt",
                ResolverSource = "Bangumi",
                Confidence = 1,
                ConfidenceLabel = "100%",
                ConfidenceLevel = "高",
                Status = "ready",
                StatusLabel = "可执行",
                WillMove = true,
            },
            new PlanItem
            {
                Index = 1,
                FileName = "无职转生 第13卷 副本.txt",
                Extension = ".txt",
                SourcePath = @"D:\Books\无职转生 第13卷 副本.txt",
                BookTitle = "无职转生 第13卷",
                SeriesName = "无职转生 ～到了异世界就拿出真本事～",
                SeriesKey = "无职转生",
                TargetDir = @"D:\Books\无职转生",
                TargetPath = @"D:\Books\无职转生\无职转生 第13卷.txt",
                TargetName = "无职转生 第13卷.txt",
                ResolverSource = "Bangumi",
                Confidence = 0.91,
                ConfidenceLabel = "91%",
                ConfidenceLevel = "高",
                Status = "ready",
                StatusLabel = "可执行",
                WillMove = true,
            },
            new PlanItem
            {
                Index = 2,
                FileName = "无职转生 第13卷.txt",
                Extension = ".txt",
                SourcePath = @"D:\Books\无职转生 第13卷.txt",
                BookTitle = "无职转生 第13卷",
                SeriesName = "无职转生",
                SeriesKey = "无职转生",
                TargetDir = @"D:\Books\无职转生",
                TargetPath = @"D:\Books\无职转生\无职转生 第13卷.txt",
                TargetName = "无职转生 第13卷.txt",
                ResolverSource = "重复文件检测",
                Confidence = 1,
                ConfidenceLabel = "100%",
                ConfidenceLevel = "高",
                Status = "duplicate",
                StatusLabel = "重复",
                Note = "与现有文件内容相同",
            },
        };

        ApplySnapshot(
            new AppSnapshot
            {
                App = _snapshot.App,
                MetadataProviders = _snapshot.MetadataProviders,
                Folder = @"D:\Books",
                Settings = _snapshot.Settings,
                Operation = new OperationState
                {
                    Id = 1,
                    Kind = "scan",
                    State = "success",
                    Message = "预览完成，共识别 3 个文件。",
                    Done = 3,
                    Total = 3,
                },
                Counts = new PlanCounts
                {
                    Ready = 2,
                    Duplicate = 1,
                    Series = 3,
                },
                PlansRevision = 1,
                Plans = plans,
            }
        );
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

}
