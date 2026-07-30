using LightNovelSelector.WinUI.Models;
using LightNovelSelector.WinUI.Security;
using LightNovelSelector.WinUI.ViewModels;
using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Controls;
using Windows.Storage;
using Windows.Storage.Pickers;
using Windows.System;
using WinRT.Interop;

namespace LightNovelSelector.WinUI;

public sealed partial class MainPage
{
    private string? ActiveReportPath =>
        !string.IsNullOrWhiteSpace(_selectedReport?.Path)
            ? _selectedReport.Path
            : ReportHistory.Count == 0 ? _snapshot.ReportPath : null;

    private async Task RefreshReportAsync()
    {
        var folder = _snapshot.Folder;
        if (string.IsNullOrWhiteSpace(folder))
        {
            _reportFolder = string.Empty;
            ClearReportView(clearHistory: true);
            ReportHistoryStatusText.Text = "选择分类目录后会显示历史批次。";
            return;
        }

        if (!string.Equals(_reportFolder, folder, StringComparison.OrdinalIgnoreCase))
        {
            _reportFolder = folder;
            ClearReportView(clearHistory: true);
        }

        var requestSerial = ++_reportRequestSerial;
        if (_connectionState != ConnectionState.Ready)
        {
            ReportStatusText.Text = "分类核心尚未连接；已有本地报告仍可打开或导出。";
            ReportHistoryStatusText.Text = "重新连接后可读取历史摘要。";
            UpdateReportActionState();
            return;
        }

        SetReportLoading(true);
        try
        {
            var selectedId = _selectedReport?.ReportId;
            var history = await _sidecar.GetReportHistoryAsync();
            if (requestSerial != _reportRequestSerial || _disposing)
            {
                return;
            }

            _updatingReportHistory = true;
            try
            {
                ReportHistory.Clear();
                foreach (var entry in history.Reports)
                {
                    ReportHistory.Add(entry);
                }

                _selectedReport =
                    ReportHistory.FirstOrDefault(entry => entry.ReportId == selectedId)
                    ?? ReportHistory.FirstOrDefault(entry => entry.IsLatest)
                    ?? ReportHistory.FirstOrDefault();
                ReportHistoryList.SelectedItem = _selectedReport;
            }
            finally
            {
                _updatingReportHistory = false;
            }

            ReportHistoryEmptyState.Visibility = ReportHistory.Count == 0
                ? Visibility.Visible
                : Visibility.Collapsed;
            ReportHistoryStatusText.Text = BuildHistoryStatus(history);
            SetHistoryWarning(history);
            UpdateReportActionState();

            if (_selectedReport is null)
            {
                ClearReportSummary();
                return;
            }
            await LoadSelectedReportAsync(_selectedReport, requestSerial);
        }
        catch (Exception exc)
        {
            if (requestSerial != _reportRequestSerial || _disposing)
            {
                return;
            }
            ReportHistoryStatusText.Text = "读取分类历史失败。";
            ReportHistoryWarningText.Text = exc.Message;
            ReportHistoryWarningText.Visibility = Visibility.Visible;
            ReportStatusText.Text = exc.Message;
            UpdateReportActionState();
        }
        finally
        {
            if (requestSerial == _reportRequestSerial)
            {
                SetReportLoading(false);
            }
        }
    }

    private static string BuildHistoryStatus(ReportHistoryResult history)
    {
        var parts = new List<string> { $"共 {history.TotalCount} 个批次" };
        if (history.InvalidCount > 0)
        {
            parts.Add($"已忽略 {history.InvalidCount} 个无效报告");
        }
        if (history.Truncated)
        {
            parts.Add("仅显示最近记录");
        }
        return string.Join(" · ", parts);
    }

    private void SetHistoryWarning(ReportHistoryResult history)
    {
        var messages = new List<string>();
        if (!string.IsNullOrWhiteSpace(history.Warning))
        {
            messages.Add(history.Warning);
        }
        if (history.InvalidCount > 0)
        {
            messages.Add("无效或越界报告已安全忽略，不会用于撤销。");
        }
        ReportHistoryWarningText.Text = string.Join(" ", messages);
        ReportHistoryWarningText.Visibility = messages.Count > 0
            ? Visibility.Visible
            : Visibility.Collapsed;
    }

    private async Task LoadSelectedReportAsync(
        ReportHistoryEntry selected,
        int requestSerial
    )
    {
        _selectedReport = selected;
        UpdateReportActionState();
        if (_connectionState != ConnectionState.Ready)
        {
            ClearReportSummary();
            ReportStatusText.Text = "重新连接后可读取所选批次；本地 JSON 仍可打开或导出。";
            return;
        }

        ReportStatusText.Text = $"正在读取 {selected.CreatedAtLabel} 的分类报告…";
        try
        {
            var report = await _sidecar.GetReportAsync(selected.ReportId);
            if (
                requestSerial != _reportRequestSerial
                || _disposing
                || _selectedReport?.ReportId != selected.ReportId
            )
            {
                return;
            }

            var createdAt = DateTimeOffset.TryParse(report.CreatedAt, out var timestamp)
                ? timestamp.ToLocalTime().ToString("yyyy-MM-dd HH:mm:ss")
                : report.CreatedAt;
            var reportStatus = string.IsNullOrWhiteSpace(createdAt)
                ? report.Path
                : $"生成于 {createdAt} · {report.Path}";
            ReportStatusText.Text = report.ItemsTruncated
                ? $"{reportStatus} · 显示前 {report.Items.Count} / {report.ItemCount} 项"
                : reportStatus;
            ReportMovedText.Text = $"移动 {report.Summary.Moved}";
            ReportSkippedText.Text = $"跳过 {report.Summary.Skipped}";
            ReportDuplicateText.Text = $"重复 {report.Summary.Duplicates}";
            ReportErrorText.Text = $"错误 {report.Summary.Errors}";
            ReportItems.Clear();
            foreach (var item in report.Items)
            {
                ReportItems.Add(item);
            }
            ReportItemsEmptyState.Visibility = ReportItems.Count == 0
                ? Visibility.Visible
                : Visibility.Collapsed;
        }
        catch (Exception exc)
        {
            if (requestSerial != _reportRequestSerial || _disposing)
            {
                return;
            }
            ClearReportSummary();
            ReportStatusText.Text = exc.Message;
        }
        finally
        {
            UpdateReportActionState();
        }
    }

    private void SetReportLoading(bool loading)
    {
        ReportHistoryProgressRing.IsActive = loading;
        ReportHistoryProgressRing.Visibility = loading
            ? Visibility.Visible
            : Visibility.Collapsed;
        RefreshReportButton.IsEnabled =
            !loading
            && _connectionState == ConnectionState.Ready
            && !string.IsNullOrWhiteSpace(_snapshot.Folder)
            && _snapshot.Operation.State != "running";
    }

    private void ClearReportView(bool clearHistory)
    {
        _reportRequestSerial++;
        ReportHistoryProgressRing.IsActive = false;
        ReportHistoryProgressRing.Visibility = Visibility.Collapsed;
        if (clearHistory)
        {
            _updatingReportHistory = true;
            try
            {
                ReportHistoryList.SelectedItem = null;
                ReportHistory.Clear();
                _selectedReport = null;
            }
            finally
            {
                _updatingReportHistory = false;
            }
            ReportHistoryEmptyState.Visibility = Visibility.Visible;
            ReportHistoryWarningText.Visibility = Visibility.Collapsed;
        }
        ClearReportSummary();
        UpdateReportActionState();
    }

    private void ClearReportSummary()
    {
        ReportStatusText.Text = "选择一个历史批次查看完整报告。";
        ReportMovedText.Text = "移动 0";
        ReportSkippedText.Text = "跳过 0";
        ReportDuplicateText.Text = "重复 0";
        ReportErrorText.Text = "错误 0";
        ReportItems.Clear();
        ReportItemsEmptyState.Visibility = Visibility.Visible;
    }

    private void UpdateReportActionState()
    {
        var coreReady = ConnectionStateController.Describe(_connectionState).CanUseCore;
        var running = _snapshot.Operation.State == "running";
        var hasReportPath = !string.IsNullOrWhiteSpace(ActiveReportPath);
        var latest = ReportHistory.FirstOrDefault(entry => entry.IsLatest);

        OpenReportButton.IsEnabled = hasReportPath;
        ExportReportButton.IsEnabled = hasReportPath;
        ActivityUndoButton.IsEnabled =
            coreReady
            && !running
            && _selectedReport is { CanUndo: true };
        UndoButton.IsEnabled =
            coreReady
            && !running
            && (latest?.CanUndo ?? (ReportHistory.Count == 0 && _snapshot.ReportPath is not null));
        RefreshReportButton.IsEnabled =
            coreReady
            && !running
            && !string.IsNullOrWhiteSpace(_snapshot.Folder)
            && !ReportHistoryProgressRing.IsActive;
    }

    private async void OnReportHistorySelectionChanged(
        object sender,
        SelectionChangedEventArgs e
    )
    {
        if (_updatingReportHistory)
        {
            return;
        }

        SetReportLoading(false);
        var requestSerial = ++_reportRequestSerial;
        if (ReportHistoryList.SelectedItem is not ReportHistoryEntry selected)
        {
            _selectedReport = null;
            ClearReportSummary();
            UpdateReportActionState();
            return;
        }
        await LoadSelectedReportAsync(selected, requestSerial);
    }

    private async void OnRefreshReportClick(object sender, RoutedEventArgs e)
    {
        await RefreshReportAsync();
    }

    private async void OnOpenReportClick(object sender, RoutedEventArgs e)
    {
        var reportPath = ActiveReportPath;
        if (string.IsNullOrWhiteSpace(reportPath))
        {
            return;
        }
        try
        {
            reportPath = ReportPathSafety.ValidateLocalReportPath(_snapshot.Folder, reportPath);
            var file = await StorageFile.GetFileFromPathAsync(reportPath);
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

    private async void OnExportReportClick(object sender, RoutedEventArgs e)
    {
        var reportPath = ActiveReportPath;
        if (string.IsNullOrWhiteSpace(reportPath))
        {
            return;
        }

        try
        {
            reportPath = ReportPathSafety.ValidateLocalReportPath(_snapshot.Folder, reportPath);
            var picker = new FileSavePicker
            {
                SuggestedStartLocation = PickerLocationId.DocumentsLibrary,
                SuggestedFileName = Path.GetFileNameWithoutExtension(reportPath),
            };
            picker.FileTypeChoices.Add("JSON 分类报告", [".json"]);
            var window = App.MainWindow ?? throw new InvalidOperationException("主窗口尚未准备好。");
            InitializeWithWindow.Initialize(picker, WindowNative.GetWindowHandle(window));
            var destination = await picker.PickSaveFileAsync();
            if (destination is null)
            {
                return;
            }

            var sourceFullPath = Path.GetFullPath(reportPath);
            var destinationFullPath = Path.GetFullPath(destination.Path);
            if (string.Equals(sourceFullPath, destinationFullPath, StringComparison.OrdinalIgnoreCase))
            {
                ShowToast("所选位置就是当前报告，无需重复导出。", ToastKind.Info);
                return;
            }
            await Task.Run(
                () => File.Copy(sourceFullPath, destinationFullPath, overwrite: true)
            );
            ShowToast("分类报告已导出。", ToastKind.Success);
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
}
