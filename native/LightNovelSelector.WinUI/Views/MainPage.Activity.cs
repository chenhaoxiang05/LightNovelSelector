using LightNovelSelector.WinUI.Models;
using Microsoft.UI.Xaml;
using Windows.Storage;
using Windows.System;

namespace LightNovelSelector.WinUI;

public sealed partial class MainPage
{
    private async Task RefreshReportAsync()
    {
        if (_snapshot.ReportPath is null)
        {
            UpdateReportAvailability();
            return;
        }
        if (_connectionState != ConnectionState.Ready)
        {
            ReportStatusText.Text = "分类核心尚未连接，仍可打开本地报告；重连后会刷新摘要。";
            OpenReportButton.IsEnabled = true;
            return;
        }
        try
        {
            var report = await _sidecar.GetReportAsync();
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
            OpenReportButton.IsEnabled = true;
        }
        catch (Exception exc)
        {
            ReportStatusText.Text = exc.Message;
            ReportItems.Clear();
            ReportItemsEmptyState.Visibility = Visibility.Visible;
            OpenReportButton.IsEnabled = _snapshot.ReportPath is not null;
        }
    }

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
}
