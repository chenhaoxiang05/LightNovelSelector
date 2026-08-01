using LightNovelSelector.WinUI.Models;
using LightNovelSelector.WinUI.Security;
using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Controls;
using Windows.System;

namespace LightNovelSelector.WinUI;

public sealed partial class MainPage
{
    private void InitializeDetailPane()
    {
        DetailPane.CloseRequested += OnCloseDetailClick;
        DetailPane.CandidateLookupRequested += OnLoadCandidatesClick;
        DetailPane.CorrectionRequested += OnSaveCorrectionClick;
        DetailPane.CorrectionScopeChanged += OnBatchScopeChanged;
        DetailPane.RetryRequested += OnRetryDetailClick;
        DetailPane.RevealFileRequested += OnRevealFileClick;
        DetailPane.OpenSubjectRequested += OnOpenSubjectClick;
        DetailSplitView.PaneClosed += (_, _) => UpdateCompactDetailButtonState();
    }

    private async void OnResultSelectionChanged(object sender, SelectionChangedEventArgs e)
    {
        await LoadSelectedDetailAsync();
    }

    private async void OnRetryDetailClick(object sender, RoutedEventArgs e)
    {
        await LoadSelectedDetailAsync();
    }

    private async Task LoadSelectedDetailAsync()
    {
        _detailCancellation?.Cancel();
        _detailCancellation?.Dispose();
        _detail = null;
        UpdateCompactDetailButtonState();
        var cancellation = new CancellationTokenSource();
        _detailCancellation = cancellation;
        if (ResultsList.SelectedItem is not PlanItem plan)
        {
            _detailCancellation = null;
            cancellation.Dispose();
            ShowDetailEmpty();
            return;
        }
        var plansRevision = _plansRevision;

        DetailPane.ShowLoading();
        var lockTaken = false;
        try
        {
            await Task.Delay(140, cancellation.Token);
            await _detailRequestLock.WaitAsync(cancellation.Token);
            lockTaken = true;
            _isDetailRequestActive = true;
            var detail = await _sidecar.GetDetailAsync(plan.Index, plansRevision);
            if (
                cancellation.IsCancellationRequested
                || (ResultsList.SelectedItem as PlanItem)?.Index != detail.Index
            )
            {
                return;
            }
            _detail = detail;
            await DetailPane.RenderAsync(detail);
            UpdateCandidateLookupState();
            UpdateCorrectionButtonState();
        }
        catch (OperationCanceledException)
        {
        }
        catch (Exception exc)
        {
            if (cancellation.IsCancellationRequested)
            {
                return;
            }
            DetailPane.ShowError(exc.Message);
            if (!_disposing)
            {
                ShowToast(exc.Message, ToastKind.Error);
            }
        }
        finally
        {
            if (lockTaken)
            {
                _isDetailRequestActive = false;
                _detailRequestLock.Release();
            }
            UpdateCompactDetailButtonState();
            if (ReferenceEquals(_detailCancellation, cancellation))
            {
                _detailCancellation = null;
            }
            cancellation.Dispose();
        }
    }

    private async void OnCompactDetailClick(object sender, RoutedEventArgs e)
    {
        if (
            ResultsList.SelectedItem is not PlanItem
            || _connectionState != ConnectionState.Ready
        )
        {
            return;
        }

        DetailSplitView.IsPaneOpen = true;
        UpdateCompactDetailButtonState();
        await Task.Yield();
        DetailPane.FocusInitial();
    }

    private void OnCloseDetailClick(object sender, RoutedEventArgs e)
    {
        if (_workspaceLayout is { ShowSideDetail: false })
        {
            DetailSplitView.IsPaneOpen = false;
            UpdateCompactDetailButtonState();
            CompactDetailButton.Focus(FocusState.Programmatic);
        }
    }

    private void UpdateCompactDetailButtonState()
    {
        CompactDetailButton.IsEnabled = CompactDetailButton.Visibility == Visibility.Visible
            && !DetailSplitView.IsPaneOpen
            && ResultsList.SelectedItem is PlanItem
            && _connectionState == ConnectionState.Ready;
    }

    private async void OnLoadCandidatesClick(object sender, RoutedEventArgs e)
    {
        if (_detail is null || _isCandidateLookupActive || _isSavingCorrection)
        {
            return;
        }

        var detailIndex = _detail.Index;
        var plansRevision = _detail.PlansRevision;
        _isCandidateLookupActive = true;
        UpdateCandidateLookupState();
        UpdateCorrectionButtonState();
        try
        {
            var result = await _sidecar.LoadCandidatesAsync(detailIndex, plansRevision);
            if (_detail?.Index != result.Index)
            {
                return;
            }
            DetailPane.SetCandidates(result.Candidates);
            if (!string.IsNullOrWhiteSpace(result.Warning))
            {
                ShowToast(result.Warning, ToastKind.Warning);
            }
            else
            {
                ShowToast($"已找到 {result.Candidates.Count} 个可比较结果。", ToastKind.Success);
            }
        }
        catch (Exception exc)
        {
            ShowToast(exc.Message, ToastKind.Error);
        }
        finally
        {
            _isCandidateLookupActive = false;
            UpdateCandidateLookupState();
            UpdateCorrectionButtonState();
        }
    }

    private void UpdateCandidateLookupState()
    {
        var enabled = !_isCandidateLookupActive
            && !_isSavingCorrection
            && _connectionState == ConnectionState.Ready
            && _detail is { CanLoadCandidates: true }
            && _snapshot.Operation.State != "running";
        DetailPane.SetCandidateLookupState(_isCandidateLookupActive, enabled);
    }

    private void OnBatchScopeChanged(object sender, RoutedEventArgs e)
    {
        UpdateCorrectionButtonState();
    }

    private void UpdateCorrectionButtonState()
    {
        var useBatch = DetailPane.ApplyToSeriesGroup
            && _detail is { MatchingSeriesCount: > 1 };
        var label = useBatch
            ? $"批量修正 {_detail!.MatchingSeriesCount} 项"
            : "保存修正";
        var enabled = !_isSavingCorrection
            && !_isCandidateLookupActive
            && _connectionState == ConnectionState.Ready
            && _snapshot.Operation.State != "running"
            && _detail is not null;
        DetailPane.SetCorrectionState(enabled, label);
    }

    private void ShowDetailEmpty()
    {
        _detail = null;
        DetailPane.ShowEmpty();
        if (_workspaceLayout is { ShowSideDetail: false })
        {
            DetailSplitView.IsPaneOpen = false;
        }
        UpdateCompactDetailButtonState();
    }

    private async void OnSaveCorrectionClick(object sender, RoutedEventArgs e)
    {
        if (_detail is not null)
        {
            await SaveCorrectionAsync(
                _detail.Index,
                DetailPane.EditedSeriesName,
                DetailPane.ApplyToSeriesGroup,
                _detail.MatchingSeriesCount,
                _detail.PlansRevision
            );
        }
    }

    private async Task SaveCorrectionAsync(
        int index,
        string value,
        bool useBatch,
        int matchingSeriesCount,
        int plansRevision
    )
    {
        if (_isSavingCorrection)
        {
            return;
        }
        if (_isCandidateLookupActive)
        {
            ShowToast("候选仍在加载，请稍候再保存修正。", ToastKind.Warning);
            return;
        }

        var seriesName = value.Trim();
        if (string.IsNullOrWhiteSpace(seriesName))
        {
            ShowToast("系列名称不能为空。", ToastKind.Warning);
            DetailPane.FocusSeriesEditor();
            return;
        }

        if (useBatch && matchingSeriesCount > 1)
        {
            var confirmation = new ContentDialog
            {
                XamlRoot = XamlRoot,
                Title = $"批量修正 {matchingSeriesCount} 个条目？",
                Content = $"这只会更新当前分类预览，不会立即移动文件。确认后，这些条目会统一归入「{seriesName}」。",
                PrimaryButtonText = $"修正 {matchingSeriesCount} 项",
                CloseButtonText = "取消",
                DefaultButton = ContentDialogButton.Close,
            };
            if (await confirmation.ShowAsync() != ContentDialogResult.Primary)
            {
                return;
            }
        }

        _isSavingCorrection = true;
        UpdateCandidateLookupState();
        UpdateCorrectionButtonState();
        try
        {
            var result = await _sidecar.EditPlansAsync(
                index,
                seriesName,
                useBatch ? "same_series" : "single",
                plansRevision
            );
            ApplySnapshot(result.Snapshot);
            ResultsList.SelectedItem = VisiblePlans.FirstOrDefault(item => item.Index == index);
            ShowToast(
                result.UpdatedCount > 1
                    ? $"已批量修正 {result.UpdatedCount} 个条目。"
                    : "分类结果已手动修正。",
                ToastKind.Success
            );
        }
        catch (Exception exc)
        {
            ShowToast(exc.Message, ToastKind.Error);
        }
        finally
        {
            _isSavingCorrection = false;
            UpdateCandidateLookupState();
            UpdateCorrectionButtonState();
        }
    }

    private async void OnRevealFileClick(object sender, RoutedEventArgs e)
    {
        if (_detail is not null)
        {
            await OpenInExplorerAsync(_detail.SourcePath, selectFile: true);
        }
    }

    private async void OnOpenSubjectClick(object sender, RoutedEventArgs e)
    {
        if (!UriSafety.TryCreatePublicHttpsUri(_detail?.SubjectUrl, out var uri) || uri is null)
        {
            ShowToast("条目链接无效或不是安全的 HTTPS 地址。", ToastKind.Warning);
            return;
        }
        try
        {
            if (!await Launcher.LaunchUriAsync(uri))
            {
                ShowToast("Windows 未能打开该条目链接。", ToastKind.Warning);
            }
        }
        catch (Exception exc)
        {
            ShowToast(exc.Message, ToastKind.Error);
        }
    }
}
