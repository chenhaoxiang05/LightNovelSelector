using System.Collections.ObjectModel;
using LightNovelSelector.WinUI.Helpers;
using LightNovelSelector.WinUI.Models;
using LightNovelSelector.WinUI.Services;
using Microsoft.UI;
using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Automation;
using Microsoft.UI.Xaml.Controls;
using Microsoft.UI.Xaml.Media;

namespace LightNovelSelector.WinUI;

public sealed partial class MainPage : Page
{
    private readonly PythonSidecarClient _sidecar = new();
    private readonly DispatcherTimer _pollTimer = new();
    private readonly DispatcherTimer _filterTimer = new();
    private readonly SemaphoreSlim _detailRequestLock = new(1, 1);
    private readonly HashSet<int> _seenLogIds = [];
    private CancellationTokenSource? _detailCancellation;
    private AppSnapshot _snapshot = new();
    private BookDetail? _detail;
    private int _logCursor;
    private int _plansRevision = -1;
    private int _lastOperationId;
    private string _lastOperationState = "idle";
    private bool _isPolling;
    private bool _isDetailRequestActive;
    private bool _isCandidateLookupActive;
    private bool _isSavingCorrection;
    private bool _isRecovering;
    private bool _settingsInitialized;
    private bool _disposing;
    private bool _updatingReportHistory;
    private int _reportRequestSerial;
    private string _reportFolder = string.Empty;
    private ReportHistoryEntry? _selectedReport;
    private ConnectionState _connectionState = ConnectionState.Connecting;

    public IReadOnlyList<PlanItem> Plans { get; private set; } = [];
    public IReadOnlyList<PlanItem> VisiblePlans { get; private set; } = [];
    public ObservableCollection<LogEntry> Logs { get; } = [];
    public ObservableCollection<EditableRule> Rules { get; } = [];
    public ObservableCollection<ReportItem> ReportItems { get; } = [];
    public ObservableCollection<ReportHistoryEntry> ReportHistory { get; } = [];

    public bool IsCriticalOperation =>
        _connectionState == ConnectionState.Ready
        && _snapshot.Operation.State == "running"
        && _snapshot.Operation.Kind is "apply" or "undo";

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
        _filterTimer.Interval = TimeSpan.FromMilliseconds(120);
        _filterTimer.Tick += OnFilterTimerTick;
        Rules.CollectionChanged += (_, _) =>
        {
            UpdateRulesEmptyState();
            MarkSettingsDirty();
        };
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

        SetConnectionState(ConnectionState.Connecting);
        var connected = false;
        try
        {
            connected = await ConnectAndBootstrapAsync(restart: false);
        }
        catch (Exception exc)
        {
            connected = await RecoverCoreAsync(exc, automatic: true);
        }

        if (!connected)
        {
            if (App.IsAutomatedSmokeTest)
            {
                Environment.ExitCode = 1;
                Application.Current.Exit();
            }
            return;
        }

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
        _filterTimer.Stop();
        _reportRequestSerial++;
        _detailCancellation?.Cancel();
        _detailCancellation?.Dispose();
        _detailCancellation = null;
        _toastCancellation?.Cancel();
        _toastCancellation?.Dispose();
        _toastCancellation = null;
        try
        {
            if (_sidecar.IsRunning && _snapshot.Operation.State == "running" && _snapshot.Operation.CanCancel)
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
        if (_isPolling || _isDetailRequestActive || _isCandidateLookupActive)
        {
            return;
        }
        _isPolling = true;
        try
        {
            if (!_sidecar.IsRunning)
            {
                await RecoverCoreAsync(
                    new SidecarUnavailableException("Python 服务进程已经退出。"),
                    automatic: true
                );
                return;
            }
            var snapshot = await _sidecar.PollAsync(_logCursor, _plansRevision);
            ApplySnapshot(snapshot);
            _pollTimer.Interval = snapshot.Operation.State == "running"
                ? TimeSpan.FromMilliseconds(350)
                : TimeSpan.FromSeconds(2);
        }
        catch (Exception exc) when (exc is SidecarException or TimeoutException or IOException)
        {
            await RecoverCoreAsync(exc, automatic: true);
        }
        finally
        {
            _isPolling = false;
        }
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
            if (App.IsAppearanceSmokeTest)
            {
                LoadAppearanceSmokeReport();
            }
            else
            {
                await RefreshReportAsync();
            }
        }
        else
        {
            await Task.Yield();
            SettingsView.UpdateLayout();
            Motion.RevealPage(SettingsContent);
        }
    }

    private static Brush ResourceBrush(string key) =>
        Application.Current.Resources[key] as Brush ?? new SolidColorBrush(Colors.Transparent);

    private static Brush StatusBrush(string status, bool background)
    {
        var key = status switch
        {
            "ready" or "moved" or "unchanged" => background ? "SuccessSubtleBrush" : "SuccessTextBrush",
            "duplicate" => background ? "WarningSubtleBrush" : "WarningTextBrush",
            "error" => background ? "ErrorSubtleBrush" : "ErrorTextBrush",
            _ => background ? "AccentSubtleBrush" : "AppAccentBrush",
        };
        return ResourceBrush(key);
    }

    private static string StatusGlyph(string status) => status switch
    {
        "ready" or "moved" or "unchanged" => "\uE73E",
        "duplicate" => "\uE8C8",
        "error" => "\uEA39",
        _ => "\uE946",
    };

}
