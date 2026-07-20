using System.Collections.ObjectModel;
using System.Diagnostics;
using System.Text.Json;
using LightNovelSelector.WinUI.Helpers;
using LightNovelSelector.WinUI.Models;
using LightNovelSelector.WinUI.Services;
using Microsoft.UI;
using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Automation;
using Microsoft.UI.Xaml.Controls;
using Microsoft.UI.Xaml.Media;
using Microsoft.UI.Xaml.Media.Animation;
using Microsoft.UI.Xaml.Media.Imaging;
using Windows.ApplicationModel.DataTransfer;
using Windows.Storage;
using Windows.Storage.Pickers;
using Windows.Storage.Streams;
using Windows.System;
using WinRT.Interop;

namespace LightNovelSelector.WinUI;

public sealed partial class MainPage : Page
{
    private readonly PythonSidecarClient _sidecar = new();
    private readonly DispatcherTimer _pollTimer = new();
    private readonly HashSet<int> _seenLogIds = [];
    private CancellationTokenSource? _detailCancellation;
    private AppSnapshot _snapshot = new();
    private BookDetail? _detail;
    private int _logCursor;
    private int _plansRevision = -1;
    private int _lastOperationId;
    private string _lastOperationState = "idle";
    private bool _isPolling;
    private bool _settingsInitialized;
    private bool _disposing;

    public ObservableCollection<PlanItem> Plans { get; } = [];
    public ObservableCollection<LogEntry> Logs { get; } = [];
    public ObservableCollection<EditableRule> Rules { get; } = [];

    public bool IsCriticalOperation =>
        _snapshot.Operation.State == "running" && _snapshot.Operation.Kind is "apply" or "undo";

    public MainPage()
    {
        InitializeComponent();
        if (ShellNavigation.SettingsItem is NavigationViewItem settingsItem)
        {
            settingsItem.Content = "设置";
        }
        Loaded += OnLoaded;
        Unloaded += OnUnloaded;
        _pollTimer.Tick += OnPollTimerTick;
        Rules.CollectionChanged += (_, _) => UpdateRulesEmptyState();
    }

    public void NotifyCriticalClose()
    {
        ShowToast("文件移动或撤销尚未完成，请等待当前操作结束后再关闭窗口。", ToastKind.Warning, 5000);
    }

    private async void OnLoaded(object sender, RoutedEventArgs e)
    {
        Loaded -= OnLoaded;
        await Task.Yield();
        LocalizeSettingsItem();
        SubscribeToMaterialState();
        LoadAppearanceSettings();
        AttachMotionFeedback();

        try
        {
            await _sidecar.StartAsync();
            var snapshot = await _sidecar.BootstrapAsync();
            ConnectionText.Text = "分类核心已连接";
            ConnectionDot.Fill = ResourceBrush("SuccessTextBrush");
            VersionText.Text = $"版本 {snapshot.App.Version}";
            ApplySnapshot(snapshot);
            _pollTimer.Interval = TimeSpan.FromSeconds(2);
            _pollTimer.Start();
            AnimateWorkspaceEntrance();

            if (App.IsAppearanceSmokeTest)
            {
                await RunAppearanceSmokeTestAsync();
                Application.Current.Exit();
            }
            else if (App.IsSmokeTest)
            {
                await Task.Delay(750);
                Application.Current.Exit();
            }
        }
        catch (Exception exc)
        {
            ConnectionText.Text = "分类核心不可用";
            ConnectionDot.Fill = ResourceBrush("ErrorTextBrush");
            ShowToast(exc.Message, ToastKind.Error, 6000);
            if (App.IsAutomatedSmokeTest)
            {
                Environment.ExitCode = 1;
                Application.Current.Exit();
            }
        }
    }

    private void LocalizeSettingsItem()
    {
        if (ShellNavigation.SettingsItem is not NavigationViewItem settingsItem)
        {
            return;
        }
        settingsItem.Content = "设置";
        AutomationProperties.SetName(settingsItem, "设置");
    }

    private async void OnUnloaded(object sender, RoutedEventArgs e)
    {
        if (_disposing)
        {
            return;
        }
        _disposing = true;
        Unloaded -= OnUnloaded;
        UnsubscribeFromMaterialState();
        _pollTimer.Stop();
        _detailCancellation?.Cancel();
        _toastCancellation?.Cancel();
        try
        {
            if (_snapshot.Operation.State == "running" && _snapshot.Operation.CanCancel)
            {
                await _sidecar.CancelOperationAsync();
            }
        }
        catch (SidecarException)
        {
        }
        await _sidecar.DisposeAsync();
    }

    private void AttachMotionFeedback()
    {
        foreach (var button in Descendants<Button>(RootLayout))
        {
            Motion.AttachPressFeedback(button);
        }
    }

    private void AnimateWorkspaceEntrance()
    {
        Motion.Enter(WorkspaceHeader, 0);
        Motion.Enter(FolderCard, 24);
        Motion.Enter(StatsGrid, 48);
        Motion.Enter(ResultsCard, 72);
        Motion.Enter(DetailCard, 96);
        Motion.Enter(OperationCard, 120);
    }

    private static IEnumerable<T> Descendants<T>(DependencyObject root) where T : DependencyObject
    {
        var count = VisualTreeHelper.GetChildrenCount(root);
        for (var index = 0; index < count; index++)
        {
            var child = VisualTreeHelper.GetChild(root, index);
            if (child is T match)
            {
                yield return match;
            }
            foreach (var descendant in Descendants<T>(child))
            {
                yield return descendant;
            }
        }
    }

    private async void OnPollTimerTick(object? sender, object e)
    {
        if (_isPolling || !_sidecar.IsRunning)
        {
            return;
        }
        _isPolling = true;
        try
        {
            var snapshot = await _sidecar.PollAsync(_logCursor, _plansRevision);
            ApplySnapshot(snapshot);
            _pollTimer.Interval = snapshot.Operation.State == "running"
                ? TimeSpan.FromMilliseconds(350)
                : TimeSpan.FromSeconds(2);
        }
        catch (Exception exc) when (exc is SidecarException or TimeoutException or IOException)
        {
            _pollTimer.Stop();
            ConnectionText.Text = "分类核心连接中断";
            ConnectionDot.Fill = ResourceBrush("ErrorTextBrush");
            ShowToast(exc.Message, ToastKind.Error, 6000);
        }
        finally
        {
            _isPolling = false;
        }
    }

    private void ApplySnapshot(AppSnapshot snapshot)
    {
        var selectedIndex = (ResultsList.SelectedItem as PlanItem)?.Index;
        _snapshot = snapshot;
        _logCursor = snapshot.LogCursor;
        _plansRevision = snapshot.PlansRevision;

        if (snapshot.Plans is not null)
        {
            Plans.Clear();
            foreach (var plan in snapshot.Plans)
            {
                Plans.Add(plan);
            }
            ResultsEmptyState.Visibility = Plans.Count == 0 ? Visibility.Visible : Visibility.Collapsed;
            if (selectedIndex is not null)
            {
                ResultsList.SelectedItem = Plans.FirstOrDefault(item => item.Index == selectedIndex);
            }
        }

        foreach (var entry in snapshot.Logs)
        {
            if (_seenLogIds.Add(entry.Id))
            {
                Logs.Add(entry);
            }
        }
        while (Logs.Count > 300)
        {
            Logs.RemoveAt(0);
        }

        if (!_settingsInitialized)
        {
            LoadSettings(snapshot.Settings);
            _settingsInitialized = true;
        }

        FolderPathText.Text = string.IsNullOrWhiteSpace(snapshot.Folder)
            ? "选择一个目录，或将目录拖放到这里"
            : snapshot.Folder;
        OpenFolderButton.IsEnabled = !string.IsNullOrWhiteSpace(snapshot.Folder);
        ResultCountText.Text = $"{Plans.Count} 个文件";
        SetCount(ReadyCountText, snapshot.Counts.Ready);
        SetCount(SeriesCountText, snapshot.Counts.Series);
        SetCount(DuplicateCountText, snapshot.Counts.Duplicate);
        SetCount(AttentionCountText, snapshot.Counts.Conflict + snapshot.Counts.Error);
        UpdateOperation(snapshot.Operation);
        UpdateReportAvailability();
    }

    private void SetCount(TextBlock target, int value)
    {
        var next = value.ToString();
        if (target.Text == next)
        {
            return;
        }
        target.Text = next;
    }

    private void UpdateOperation(OperationState operation)
    {
        var running = operation.State == "running";
        var hasFolder = !string.IsNullOrWhiteSpace(_snapshot.Folder);
        var hasMovablePlans = Plans.Any(plan => plan.WillMove);
        OperationMessageText.Text = operation.Message;
        OperationProgressBar.IsIndeterminate = running && operation.Total <= 0;
        OperationProgressBar.Value = operation.Total > 0
            ? Math.Clamp((double)operation.Done / operation.Total * 100, 0, 100)
            : 0;
        OperationProgressText.Text = operation.Total > 0 ? $"{operation.Done} / {operation.Total}" : string.Empty;

        ChooseFolderButton.IsEnabled = !running;
        ScanButton.IsEnabled = hasFolder && !running;
        RefreshButton.IsEnabled = hasFolder && !running;
        SaveSettingsButton.IsEnabled = !running;
        ApplyButton.IsEnabled = hasMovablePlans && !running;
        UndoButton.IsEnabled = _snapshot.ReportPath is not null && !running;
        ActivityUndoButton.IsEnabled = UndoButton.IsEnabled;
        CancelButton.Visibility = running && operation.CanCancel ? Visibility.Visible : Visibility.Collapsed;

        var (glyph, brushKey) = operation.State switch
        {
            "success" => ("\uE73E", "SuccessTextBrush"),
            "error" => ("\uEA39", "ErrorTextBrush"),
            "cancelled" => ("\uE711", "WarningTextBrush"),
            "running" => ("\uE895", "AppAccentBrush"),
            _ => ("\uE946", "AppAccentBrush"),
        };
        OperationIcon.Glyph = glyph;
        OperationIcon.Foreground = ResourceBrush(brushKey);

        if (
            operation.Id == _lastOperationId
            && _lastOperationState == "running"
            && operation.State != "running"
        )
        {
            var kind = operation.State switch
            {
                "success" => ToastKind.Success,
                "error" => ToastKind.Error,
                "cancelled" => ToastKind.Warning,
                _ => ToastKind.Info,
            };
            ShowToast(operation.Error is null ? operation.Message : $"{operation.Message}：{operation.Error}", kind);
            if (operation.Kind is "apply" or "undo")
            {
                _ = RefreshReportAsync();
            }
        }
        _lastOperationId = operation.Id;
        _lastOperationState = operation.State;
    }

    private void UpdateReportAvailability()
    {
        var available = _snapshot.ReportPath is not null;
        OpenReportButton.IsEnabled = available;
        if (!available)
        {
            ReportStatusText.Text = "当前目录还没有分类报告。";
            ReportMovedText.Text = "移动 0";
            ReportSkippedText.Text = "跳过 0";
            ReportDuplicateText.Text = "重复 0";
        }
    }

    private void LoadSettings(AppSettings settings)
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

    private void UpdateRulesEmptyState()
    {
        RulesEmptyText.Visibility = Rules.Count == 0 ? Visibility.Visible : Visibility.Collapsed;
    }

    private async void OnNavigationSelectionChanged(NavigationView sender, NavigationViewSelectionChangedEventArgs args)
    {
        var target = args.IsSettingsSelected
            ? "settings"
            : (args.SelectedItemContainer as NavigationViewItem)?.Tag as string ?? "workspace";
        WorkspaceView.Visibility = target == "workspace" ? Visibility.Visible : Visibility.Collapsed;
        ActivityView.Visibility = target == "activity" ? Visibility.Visible : Visibility.Collapsed;
        SettingsView.Visibility = target == "settings" ? Visibility.Visible : Visibility.Collapsed;

        if (target == "workspace")
        {
            await Task.Yield();
            WorkspaceView.UpdateLayout();
            Motion.RevealPage(WorkspaceView);
        }
        else if (target == "activity")
        {
            await Task.Yield();
            ActivityView.UpdateLayout();
            Motion.RevealPage(ActivityView);
            await RefreshReportAsync();
        }
        else
        {
            await Task.Yield();
            SettingsView.UpdateLayout();
            Motion.RevealPage(SettingsContent);
        }
    }

    private async void OnChooseFolderClick(object sender, RoutedEventArgs e)
    {
        try
        {
            var picker = new FolderPicker { SuggestedStartLocation = PickerLocationId.DocumentsLibrary };
            picker.FileTypeFilter.Add("*");
            var window = App.MainWindow ?? throw new InvalidOperationException("主窗口尚未准备好。");
            InitializeWithWindow.Initialize(picker, WindowNative.GetWindowHandle(window));
            var folder = await picker.PickSingleFolderAsync();
            if (folder is null)
            {
                return;
            }
            await SelectFolderAsync(folder.Path);
        }
        catch (Exception exc)
        {
            ShowToast(exc.Message, ToastKind.Error);
        }
    }

    private void OnFolderDragEnter(object sender, DragEventArgs e)
    {
        var acceptsStorageItems = e.DataView.Contains(StandardDataFormats.StorageItems);
        SetFolderDragState(acceptsStorageItems);
        e.Handled = acceptsStorageItems;
    }

    private void OnFolderDragLeave(object sender, DragEventArgs e)
    {
        SetFolderDragState(false);
    }

    private void OnFolderDragOver(object sender, DragEventArgs e)
    {
        if (!e.DataView.Contains(StandardDataFormats.StorageItems))
        {
            SetFolderDragState(false);
            return;
        }
        SetFolderDragState(true);
        e.AcceptedOperation = DataPackageOperation.Link;
        e.DragUIOverride.Caption = "使用此目录";
        e.DragUIOverride.IsContentVisible = true;
        e.Handled = true;
    }

    private async void OnFolderDrop(object sender, DragEventArgs e)
    {
        SetFolderDragState(false);
        try
        {
            var items = await e.DataView.GetStorageItemsAsync();
            var folders = items.OfType<StorageFolder>().ToList();
            string? path = null;
            if (folders.Count == 1 && items.Count == 1)
            {
                path = folders[0].Path;
            }
            else if (folders.Count == 0 && items.OfType<StorageFile>().Any())
            {
                var parents = items
                    .OfType<StorageFile>()
                    .Select(file => Path.GetDirectoryName(file.Path))
                    .Where(parent => !string.IsNullOrWhiteSpace(parent))
                    .Distinct(StringComparer.OrdinalIgnoreCase)
                    .ToList();
                if (parents.Count == 1)
                {
                    path = parents[0];
                }
            }

            if (string.IsNullOrWhiteSpace(path))
            {
                ShowToast("请拖入一个目录，或拖入同一目录中的一批小说文件。", ToastKind.Warning);
                return;
            }
            await SelectFolderAsync(path);
        }
        catch (Exception exc)
        {
            ShowToast(exc.Message, ToastKind.Error);
        }
        finally
        {
            SetFolderDragState(false);
        }
    }

    private void SetFolderDragState(bool active)
    {
        if (FolderCard.BackgroundTransition is BrushTransition transition)
        {
            transition.Duration = TimeSpan.FromMilliseconds(active ? 100 : 120);
        }
        FolderCard.Background = ResourceBrush(active ? "CardHoverBrush" : "CardBackgroundBrush");
        FolderCard.BorderBrush = ResourceBrush(active ? "AppAccentBrush" : "CardBorderBrush");
        FolderCard.BorderThickness = new Thickness(active ? 2 : 1);
        Motion.SetEmphasis(FolderIconSurface, active);
    }

    private async Task SelectFolderAsync(string path)
    {
        var snapshot = await _sidecar.SetFolderAsync(path);
        ApplySnapshot(snapshot);
        ShowToast("目录已选择，可以开始扫描。", ToastKind.Success);
    }

    private async void OnScanClick(object sender, RoutedEventArgs e)
    {
        if (string.IsNullOrWhiteSpace(_snapshot.Folder))
        {
            ShowToast("请先选择轻小说目录。", ToastKind.Warning);
            return;
        }

        try
        {
            try
            {
                await SaveCurrentSettingsAsync(showResult: false);
            }
            catch (SidecarRemoteException exc)
            {
                ShowToast($"新设置未采用，将使用上次保存值：{exc.Message}", ToastKind.Warning, 5000);
            }
            var snapshot = await _sidecar.StartScanAsync();
            ApplySnapshot(snapshot);
            ShowToast("扫描已开始，原文件不会在预览阶段发生变化。", ToastKind.Info);
        }
        catch (Exception exc)
        {
            ShowToast(exc.Message, ToastKind.Error);
        }
    }

    private async void OnCancelClick(object sender, RoutedEventArgs e)
    {
        try
        {
            var result = await _sidecar.CancelOperationAsync();
            ApplySnapshot(result.State);
            if (result.Cancelled)
            {
                ShowToast("正在安全停止扫描。", ToastKind.Info);
            }
        }
        catch (Exception exc)
        {
            ShowToast(exc.Message, ToastKind.Error);
        }
    }

    private async void OnApplyClick(object sender, RoutedEventArgs e)
    {
        var movable = Plans.Count(plan => plan.WillMove);
        if (movable == 0)
        {
            ShowToast("当前预览没有可移动的文件。", ToastKind.Warning);
            return;
        }

        var dialog = new ContentDialog
        {
            XamlRoot = XamlRoot,
            Title = "确认整理这些文件？",
            Content = $"将移动 {movable} 个文件。执行过程会写入分类报告，完成后可按报告撤销。",
            PrimaryButtonText = "开始整理",
            CloseButtonText = "返回检查",
            DefaultButton = ContentDialogButton.Primary,
        };
        if (await dialog.ShowAsync() != ContentDialogResult.Primary)
        {
            return;
        }

        try
        {
            var snapshot = await _sidecar.StartApplyAsync();
            ApplySnapshot(snapshot);
            ShowToast("正在整理文件，请保持窗口开启。", ToastKind.Info);
        }
        catch (Exception exc)
        {
            ShowToast(exc.Message, ToastKind.Error);
        }
    }

    private async void OnUndoClick(object sender, RoutedEventArgs e)
    {
        var dialog = new ContentDialog
        {
            XamlRoot = XamlRoot,
            Title = "撤销上次分类？",
            Content = "软件会按最近的分类报告将已移动文件恢复到原位置；目标位置已有同名文件时会安全跳过。",
            PrimaryButtonText = "开始撤销",
            CloseButtonText = "取消",
            DefaultButton = ContentDialogButton.Close,
        };
        if (await dialog.ShowAsync() != ContentDialogResult.Primary)
        {
            return;
        }

        try
        {
            var snapshot = await _sidecar.StartUndoAsync();
            ApplySnapshot(snapshot);
            ShowToast("正在按报告恢复文件，请保持窗口开启。", ToastKind.Info);
        }
        catch (Exception exc)
        {
            ShowToast(exc.Message, ToastKind.Error);
        }
    }

    private async void OnResultSelectionChanged(object sender, SelectionChangedEventArgs e)
    {
        _detailCancellation?.Cancel();
        _detailCancellation?.Dispose();
        _detailCancellation = new CancellationTokenSource();
        if (ResultsList.SelectedItem is not PlanItem plan)
        {
            ShowDetailEmpty();
            return;
        }

        DetailEmptyState.Visibility = Visibility.Collapsed;
        DetailContent.Visibility = Visibility.Collapsed;
        DetailLoadingState.Visibility = Visibility.Visible;
        try
        {
            var detail = await _sidecar.GetDetailAsync(plan.Index, _detailCancellation.Token);
            if (_detailCancellation.IsCancellationRequested || (ResultsList.SelectedItem as PlanItem)?.Index != detail.Index)
            {
                return;
            }
            _detail = detail;
            await RenderDetailAsync(detail);
        }
        catch (OperationCanceledException)
        {
        }
        catch (Exception exc)
        {
            DetailLoadingState.Visibility = Visibility.Collapsed;
            DetailEmptyState.Visibility = Visibility.Visible;
            ShowToast(exc.Message, ToastKind.Error);
        }
    }

    private async Task RenderDetailAsync(BookDetail detail)
    {
        DetailTitleText.Text = detail.Title;
        DetailSummaryText.Text = detail.Summary;
        DetailTargetText.Text = detail.TargetPath;
        DetailConfidenceText.Text = $"{detail.ResolverSource} · 置信度 {detail.ConfidenceLabel}";
        DetailCoverSourceText.Text = detail.CoverSource;
        DetailStatusText.Text = detail.StatusLabel;
        DetailStatusIcon.Text = StatusGlyph(detail.Status);
        DetailStatusBadge.Background = StatusBrush(detail.Status, background: true);
        DetailStatusText.Foreground = StatusBrush(detail.Status, background: false);
        DetailStatusIcon.Foreground = StatusBrush(detail.Status, background: false);
        SeriesEditBox.Text = detail.SeriesName;
        DetailWarningBar.IsOpen = !string.IsNullOrWhiteSpace(detail.Warning);
        DetailWarningBar.Message = detail.Warning ?? string.Empty;
        OpenSubjectButton.IsEnabled = Uri.TryCreate(detail.SubjectUrl, UriKind.Absolute, out _);
        await SetCoverAsync(detail.CoverDataUrl);
        DetailLoadingState.Visibility = Visibility.Collapsed;
        DetailEmptyState.Visibility = Visibility.Collapsed;
        DetailContent.Visibility = Visibility.Visible;
        Motion.Enter(DetailContent);
        if (DetailCard.Visibility == Visibility.Collapsed)
        {
            await ShowCompactDetailDialogAsync(detail);
        }
    }

    private async Task ShowCompactDetailDialogAsync(BookDetail detail)
    {
        var editor = new TextBox
        {
            Header = "系列文件夹名称",
            Text = detail.SeriesName,
        };
        var panel = new StackPanel { Spacing = 12, MaxWidth = 460 };
        panel.Children.Add(new TextBlock
        {
            Text = $"{detail.StatusLabel} · {detail.ResolverSource} · 置信度 {detail.ConfidenceLabel}",
            Foreground = ResourceBrush("TextFillColorSecondaryBrush"),
        });
        panel.Children.Add(new TextBlock
        {
            Text = detail.Summary,
            MaxLines = 6,
            TextWrapping = TextWrapping.Wrap,
            Foreground = ResourceBrush("TextFillColorSecondaryBrush"),
        });
        panel.Children.Add(editor);
        panel.Children.Add(new TextBlock
        {
            Text = detail.TargetPath,
            TextWrapping = TextWrapping.Wrap,
            FontSize = 12,
            Foreground = ResourceBrush("TextFillColorTertiaryBrush"),
        });

        var dialog = new ContentDialog
        {
            XamlRoot = XamlRoot,
            Title = detail.Title,
            Content = panel,
            PrimaryButtonText = "保存修正",
            CloseButtonText = "关闭",
            DefaultButton = ContentDialogButton.Close,
        };
        if (await dialog.ShowAsync() == ContentDialogResult.Primary)
        {
            await SaveCorrectionAsync(detail.Index, editor.Text);
        }
    }

    private async Task SetCoverAsync(string? dataUri)
    {
        CoverImage.Source = null;
        CoverPlaceholder.Visibility = Visibility.Visible;
        if (string.IsNullOrWhiteSpace(dataUri))
        {
            return;
        }

        var commaIndex = dataUri.IndexOf(',');
        if (commaIndex < 0 || commaIndex == dataUri.Length - 1)
        {
            return;
        }
        try
        {
            var bytes = Convert.FromBase64String(dataUri[(commaIndex + 1)..]);
            using var stream = new InMemoryRandomAccessStream();
            using (var writer = new DataWriter(stream))
            {
                writer.WriteBytes(bytes);
                await writer.StoreAsync();
                await writer.FlushAsync();
                writer.DetachStream();
            }
            stream.Seek(0);
            var image = new BitmapImage();
            await image.SetSourceAsync(stream);
            CoverImage.Source = image;
            CoverPlaceholder.Visibility = Visibility.Collapsed;
        }
        catch (Exception exc) when (exc is FormatException or ArgumentException)
        {
            CoverImage.Source = null;
        }
    }

    private void ShowDetailEmpty()
    {
        _detail = null;
        CoverImage.Source = null;
        DetailLoadingState.Visibility = Visibility.Collapsed;
        DetailContent.Visibility = Visibility.Collapsed;
        DetailEmptyState.Visibility = Visibility.Visible;
    }

    private async void OnSaveCorrectionClick(object sender, RoutedEventArgs e)
    {
        if (_detail is null)
        {
            return;
        }
        await SaveCorrectionAsync(_detail.Index, SeriesEditBox.Text);
    }

    private async Task SaveCorrectionAsync(int index, string value)
    {
        var seriesName = value.Trim();
        if (string.IsNullOrWhiteSpace(seriesName))
        {
            ShowToast("系列名称不能为空。", ToastKind.Warning);
            SeriesEditBox.Focus(FocusState.Programmatic);
            return;
        }

        try
        {
            var snapshot = await _sidecar.EditPlanAsync(index, seriesName);
            ApplySnapshot(snapshot);
            ResultsList.SelectedItem = Plans.FirstOrDefault(item => item.Index == index);
            ShowToast("分类结果已手动修正。", ToastKind.Success);
        }
        catch (Exception exc)
        {
            ShowToast(exc.Message, ToastKind.Error);
        }
    }

    private void OnOpenFolderClick(object sender, RoutedEventArgs e)
    {
        if (!string.IsNullOrWhiteSpace(_snapshot.Folder))
        {
            OpenInExplorer(_snapshot.Folder);
        }
    }

    private void OnRevealFileClick(object sender, RoutedEventArgs e)
    {
        if (_detail is not null)
        {
            OpenInExplorer(_detail.SourcePath, selectFile: true);
        }
    }

    private async void OnOpenSubjectClick(object sender, RoutedEventArgs e)
    {
        if (_detail?.SubjectUrl is not null && Uri.TryCreate(_detail.SubjectUrl, UriKind.Absolute, out var uri))
        {
            await Launcher.LaunchUriAsync(uri);
        }
    }

    private static void OpenInExplorer(string path, bool selectFile = false)
    {
        var startInfo = new ProcessStartInfo
        {
            FileName = "explorer.exe",
            UseShellExecute = true,
        };
        startInfo.ArgumentList.Add(selectFile ? $"/select,{path}" : path);
        Process.Start(startInfo);
    }

    private async Task RefreshReportAsync()
    {
        if (_snapshot.ReportPath is null)
        {
            UpdateReportAvailability();
            return;
        }
        try
        {
            var report = await _sidecar.GetReportAsync();
            var createdAt = DateTimeOffset.TryParse(report.CreatedAt, out var timestamp)
                ? timestamp.ToLocalTime().ToString("yyyy-MM-dd HH:mm:ss")
                : report.CreatedAt;
            ReportStatusText.Text = string.IsNullOrWhiteSpace(createdAt)
                ? report.Path
                : $"生成于 {createdAt} · {report.Path}";
            ReportMovedText.Text = $"移动 {JsonInt(report.Summary, "moved")}";
            ReportSkippedText.Text = $"跳过 {JsonInt(report.Summary, "skipped")}";
            ReportDuplicateText.Text = $"重复 {JsonInt(report.Summary, "duplicates")}";
            OpenReportButton.IsEnabled = true;
        }
        catch (Exception exc)
        {
            ReportStatusText.Text = exc.Message;
            OpenReportButton.IsEnabled = false;
        }
    }

    private static int JsonInt(JsonElement element, string name) =>
        element.ValueKind == JsonValueKind.Object
        && element.TryGetProperty(name, out var value)
        && value.TryGetInt32(out var number)
            ? number
            : 0;

    private async void OnOpenReportClick(object sender, RoutedEventArgs e)
    {
        if (_snapshot.ReportPath is null)
        {
            return;
        }
        try
        {
            var file = await StorageFile.GetFileFromPathAsync(_snapshot.ReportPath);
            if (!await Launcher.LaunchFileAsync(file))
            {
                ShowToast("Windows 没有可用于打开 JSON 报告的应用。", ToastKind.Warning);
            }
        }
        catch (Exception exc)
        {
            ShowToast(exc.Message, ToastKind.Error);
        }
    }

    private void OnClearVisibleLogsClick(object sender, RoutedEventArgs e)
    {
        Logs.Clear();
        ShowToast("已清空当前显示；后台日志游标保持不变。", ToastKind.Info);
    }

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

    private static Brush ResourceBrush(string key) =>
        Application.Current.Resources[key] as Brush ?? new SolidColorBrush(Colors.Transparent);

    private static Brush StatusBrush(string status, bool background)
    {
        var key = status switch
        {
            "ready" or "moved" or "unchanged" => background ? "SuccessSubtleBrush" : "SuccessTextBrush",
            "duplicate" or "conflict" => background ? "WarningSubtleBrush" : "WarningTextBrush",
            "error" => background ? "ErrorSubtleBrush" : "ErrorTextBrush",
            _ => background ? "AccentSubtleBrush" : "AppAccentBrush",
        };
        return ResourceBrush(key);
    }

    private static string StatusGlyph(string status) => status switch
    {
        "ready" or "moved" or "unchanged" => "\uE73E",
        "duplicate" => "\uE8C8",
        "conflict" => "\uE7BA",
        "error" => "\uEA39",
        _ => "\uE946",
    };

}
