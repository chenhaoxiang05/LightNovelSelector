using LightNovelSelector.WinUI.Models;
using LightNovelSelector.WinUI.ViewModels;
using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Controls;

namespace LightNovelSelector.WinUI;

public sealed partial class MainPage
{
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
            RebuildPlanFilters();
            ApplyPlanFilters(selectedIndex);
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
        SetCount(ReadyCountText, snapshot.Counts.Ready);
        SetCount(SeriesCountText, snapshot.Counts.Series);
        SetCount(DuplicateCountText, snapshot.Counts.Duplicate);
        SetCount(AttentionCountText, snapshot.Counts.Conflict + snapshot.Counts.Error);
        UpdateOperation(snapshot.Operation);
        UpdateWorkflowRail(snapshot);
        UpdateReportAvailability();
    }

    private static void SetCount(TextBlock target, int value)
    {
        var next = value.ToString();
        if (target.Text != next)
        {
            target.Text = next;
        }
    }

    private void UpdateOperation(OperationState operation)
    {
        var running = operation.State == "running";
        var coreReady = ConnectionStateController.Describe(_connectionState).CanUseCore;
        var hasFolder = !string.IsNullOrWhiteSpace(_snapshot.Folder);
        var hasMovablePlans = Plans.Any(plan => plan.WillMove);
        OperationMessageText.Text = operation.Message;
        OperationProgressBar.IsIndeterminate = running && operation.Total <= 0;
        OperationProgressBar.Value = operation.Total > 0
            ? Math.Clamp((double)operation.Done / operation.Total * 100, 0, 100)
            : 0;
        OperationProgressText.Text = operation.Total > 0 ? $"{operation.Done} / {operation.Total}" : string.Empty;

        ChooseFolderButton.IsEnabled = coreReady && !running;
        ScanButton.IsEnabled = coreReady && hasFolder && !running;
        RefreshButton.IsEnabled = coreReady && hasFolder && !running;
        SaveSettingsButton.IsEnabled = coreReady && _settingsDirty && !running;
        ApplyButton.IsEnabled = coreReady && hasMovablePlans && !running;
        UndoButton.IsEnabled = coreReady && _snapshot.ReportPath is not null && !running;
        ActivityUndoButton.IsEnabled = UndoButton.IsEnabled;
        CancelButton.Visibility = coreReady && running && operation.CanCancel
            ? Visibility.Visible
            : Visibility.Collapsed;
        var scanning = running && operation.Kind == "scan";
        ScanProgressRing.IsActive = scanning;
        ScanProgressRing.Visibility = scanning ? Visibility.Visible : Visibility.Collapsed;
        ScanButtonIcon.Visibility = scanning ? Visibility.Collapsed : Visibility.Visible;
        ScanButtonText.Text = scanning ? "扫描中" : "扫描并预览";
        var applying = running && operation.Kind == "apply";
        ApplyProgressRing.IsActive = applying;
        ApplyProgressRing.Visibility = applying ? Visibility.Visible : Visibility.Collapsed;
        ApplyButtonIcon.Visibility = applying ? Visibility.Collapsed : Visibility.Visible;
        ApplyButtonText.Text = applying ? "整理中" : "确认整理";

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
        OperationIconSurface.Background = ResourceBrush(operation.State switch
        {
            "success" => "SuccessSubtleBrush",
            "error" => "ErrorSubtleBrush",
            "cancelled" => "WarningSubtleBrush",
            _ => "AccentSubtleBrush",
        });

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
        if (available)
        {
            return;
        }

        ReportStatusText.Text = "当前目录还没有分类报告。";
        ReportMovedText.Text = "移动 0";
        ReportSkippedText.Text = "跳过 0";
        ReportDuplicateText.Text = "重复 0";
        ReportErrorText.Text = "错误 0";
        ReportItems.Clear();
        ReportItemsEmptyState.Visibility = Visibility.Visible;
    }
}
