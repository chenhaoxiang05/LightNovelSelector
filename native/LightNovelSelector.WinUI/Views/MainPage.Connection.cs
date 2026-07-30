using LightNovelSelector.WinUI.Models;
using LightNovelSelector.WinUI.Services;
using LightNovelSelector.WinUI.ViewModels;
using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Controls;

namespace LightNovelSelector.WinUI;

public sealed partial class MainPage
{
    private async Task<bool> ConnectAndBootstrapAsync(bool restart)
    {
        var ping = restart
            ? await _sidecar.RestartAsync()
            : await _sidecar.StartAsync();
        var snapshot = await _sidecar.BootstrapAsync();

        if (restart)
        {
            ResetCoreSessionState();
        }
        VersionText.Text = $"版本 {snapshot.App.Version}";
        if (string.IsNullOrWhiteSpace(snapshot.App.Version))
        {
            VersionText.Text = $"核心进程 {ping.ProcessId}";
        }
        ApplySnapshot(snapshot);
        SetConnectionState(ConnectionState.Ready);
        _pollTimer.Interval = TimeSpan.FromSeconds(2);
        _pollTimer.Start();
        return true;
    }

    private async Task<bool> RecoverCoreAsync(Exception cause, bool automatic)
    {
        if (_disposing || _isRecovering)
        {
            return false;
        }

        _isRecovering = true;
        _pollTimer.Stop();
        SetConnectionState(ConnectionState.Recovering, cause.Message);
        try
        {
            if (automatic)
            {
                await Task.Delay(600);
            }
            await ConnectAndBootstrapAsync(restart: true);
            ShowToast(
                automatic
                    ? "分类核心已自动恢复。原预览已清空，请重新扫描后再整理。"
                    : "分类核心已重新连接。原预览已清空，请重新扫描后再整理。",
                ToastKind.Success,
                5500
            );
            return true;
        }
        catch (Exception exc)
        {
            SetConnectionState(ConnectionState.Disconnected, exc.Message);
            ShowToast($"分类核心恢复失败：{exc.Message}", ToastKind.Error, 6500);
            return false;
        }
        finally
        {
            _isRecovering = false;
        }
    }

    private void SetConnectionState(ConnectionState state, string? detail = null)
    {
        _connectionState = state;
        var presentation = ConnectionStateController.Describe(state);
        ConnectionText.Text = presentation.Label;
        ConnectionDot.Fill = ResourceBrush(presentation.ForegroundBrushKey);
        ConnectionBadge.Background = ResourceBrush(presentation.BackgroundBrushKey);
        ConnectionRecoveryBar.IsOpen = presentation.ShowRecoveryBar;
        ConnectionRecoveryBar.Severity = state == ConnectionState.Disconnected
            ? InfoBarSeverity.Error
            : InfoBarSeverity.Warning;
        ConnectionRecoveryBar.Title = state == ConnectionState.Recovering
            ? "正在恢复分类核心"
            : "分类核心连接中断";
        ConnectionRecoveryBar.Message = state == ConnectionState.Recovering
            ? "正在安全重启本地核心；恢复后需要重新扫描，不会自动移动文件。"
            : string.IsNullOrWhiteSpace(detail)
                ? "可重新连接本地核心。现有报告仍保留，恢复后请重新扫描预览。"
                : detail;

        var recovering = state == ConnectionState.Recovering;
        ReconnectButton.IsEnabled = state == ConnectionState.Disconnected;
        ReconnectProgressRing.IsActive = recovering;
        ReconnectProgressRing.Visibility = recovering ? Visibility.Visible : Visibility.Collapsed;
        ReconnectButtonIcon.Visibility = recovering ? Visibility.Collapsed : Visibility.Visible;
        ReconnectButtonText.Text = recovering ? "连接中" : "重新连接";
        UpdateOperation(_snapshot.Operation);
        UpdateCompactDetailButtonState();
        if (state == ConnectionState.Ready && ActivityView.Visibility == Visibility.Visible)
        {
            _ = RefreshReportAsync();
        }
    }

    private void ResetCoreSessionState()
    {
        _detailCancellation?.Cancel();
        _detailCancellation?.Dispose();
        _detailCancellation = null;
        _detail = null;
        _snapshot = new AppSnapshot();
        _logCursor = 0;
        _plansRevision = -1;
        _lastOperationId = 0;
        _lastOperationState = "idle";
        _settingsInitialized = false;
        _seenLogIds.Clear();
        _filterTimer.Stop();
        Logs.Clear();
        Plans = [];
        VisiblePlans = [];
        ResultsList.ItemsSource = VisiblePlans;
        _reportFolder = string.Empty;
        ClearReportView(clearHistory: true);
        RebuildPlanFilters();
        ApplyPlanFilters();
        ShowDetailEmpty();
    }

    private async void OnReconnectClick(object sender, RoutedEventArgs e)
    {
        if (_connectionState != ConnectionState.Disconnected)
        {
            return;
        }
        await RecoverCoreAsync(new SidecarUnavailableException("用户请求重新连接。"), automatic: false);
    }
}
