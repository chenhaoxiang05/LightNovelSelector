using LightNovelSelector.WinUI.Helpers;
using LightNovelSelector.WinUI.Models;
using LightNovelSelector.WinUI.Security;
using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Controls;
using Microsoft.UI.Xaml.Media.Imaging;
using Windows.Storage.Streams;
using Windows.System;

namespace LightNovelSelector.WinUI;

public sealed partial class MainPage
{
    private const int MaxCoverDataUriChars = 12 * 1024 * 1024;
    private bool _compactDetailDialogOpen;

    private async void OnResultSelectionChanged(object sender, SelectionChangedEventArgs e)
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

        DetailEmptyState.Visibility = Visibility.Collapsed;
        DetailContent.Visibility = Visibility.Collapsed;
        DetailLoadingState.Visibility = Visibility.Visible;
        var lockTaken = false;
        try
        {
            await Task.Delay(140, cancellation.Token);
            await _detailRequestLock.WaitAsync(cancellation.Token);
            lockTaken = true;
            _isDetailRequestActive = true;
            var detail = await _sidecar.GetDetailAsync(plan.Index, plansRevision);
            if (cancellation.IsCancellationRequested || (ResultsList.SelectedItem as PlanItem)?.Index != detail.Index)
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

    private async Task RenderDetailAsync(BookDetail detail)
    {
        DetailTitleText.Text = detail.Title;
        DetailAuthorsText.Text = detail.AuthorsLabel;
        DetailVolumeText.Text = detail.VolumeLabel;
        DetailLanguageText.Text = detail.LanguageLabel;
        DetailTagsText.Text = detail.TagsLabel;
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
        RenderCandidates(detail.Candidates);
        ApplySeriesGroupCheckBox.IsChecked = false;
        ApplySeriesGroupCheckBox.Content = $"同时修正当前系列的 {detail.MatchingSeriesCount} 个条目";
        ApplySeriesGroupCheckBox.Visibility = detail.MatchingSeriesCount > 1
            ? Visibility.Visible
            : Visibility.Collapsed;
        LoadCandidatesButton.Visibility = detail.CanLoadCandidates
            ? Visibility.Visible
            : Visibility.Collapsed;
        UpdateCandidateLookupState();
        UpdateCorrectionButtonState();
        DetailWarningBar.IsOpen = !string.IsNullOrWhiteSpace(detail.Warning);
        DetailWarningBar.Message = detail.Warning ?? string.Empty;
        OpenSubjectButton.IsEnabled = UriSafety.TryCreatePublicHttpsUri(detail.SubjectUrl, out _);
        await SetCoverAsync(detail.CoverDataUrl);
        DetailLoadingState.Visibility = Visibility.Collapsed;
        DetailEmptyState.Visibility = Visibility.Collapsed;
        DetailContent.Visibility = Visibility.Visible;
        UpdateCompactDetailButtonState();
        Motion.Enter(DetailContent);
    }

    private async void OnCompactDetailClick(object sender, RoutedEventArgs e)
    {
        if (_detail is null || _compactDetailDialogOpen)
        {
            return;
        }

        _compactDetailDialogOpen = true;
        UpdateCompactDetailButtonState();
        try
        {
            await ShowCompactDetailDialogAsync(_detail);
        }
        finally
        {
            _compactDetailDialogOpen = false;
            UpdateCompactDetailButtonState();
        }
    }

    private void UpdateCompactDetailButtonState()
    {
        CompactDetailButton.IsEnabled = CompactDetailButton.Visibility == Visibility.Visible
            && _detail is not null
            && !_compactDetailDialogOpen
            && !_isDetailRequestActive
            && _connectionState == ConnectionState.Ready;
    }

    private void RenderCandidates(IReadOnlyList<SeriesCandidate> candidates)
    {
        CandidateList.ItemsSource = candidates;
        CandidateList.SelectedItem = candidates.FirstOrDefault(candidate => candidate.IsCurrent)
            ?? candidates.FirstOrDefault();
    }

    private void OnCandidateSelectionChanged(object sender, SelectionChangedEventArgs e)
    {
        if (CandidateList.SelectedItem is SeriesCandidate candidate)
        {
            SeriesEditBox.Text = candidate.SeriesName;
        }
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
            RenderCandidates(result.Candidates);
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
        CandidateLookupProgress.IsActive = _isCandidateLookupActive;
        CandidateLookupProgress.Visibility = _isCandidateLookupActive
            ? Visibility.Visible
            : Visibility.Collapsed;
        LoadCandidatesButton.IsEnabled = !_isCandidateLookupActive
            && !_isSavingCorrection
            && _connectionState == ConnectionState.Ready
            && _detail is { CanLoadCandidates: true }
            && _snapshot.Operation.State != "running";
    }

    private void OnBatchScopeChanged(object sender, RoutedEventArgs e)
    {
        UpdateCorrectionButtonState();
    }

    private void UpdateCorrectionButtonState()
    {
        var useBatch = ApplySeriesGroupCheckBox.IsChecked == true
            && _detail is { MatchingSeriesCount: > 1 };
        SaveCorrectionText.Text = useBatch
            ? $"批量修正 {_detail!.MatchingSeriesCount} 项"
            : "保存修正";
        SaveCorrectionButton.IsEnabled = !_isSavingCorrection
            && !_isCandidateLookupActive
            && _connectionState == ConnectionState.Ready
            && _snapshot.Operation.State != "running"
            && _detail is not null;
    }

    private async Task ShowCompactDetailDialogAsync(BookDetail detail)
    {
        var editor = new TextBox
        {
            Header = "系列文件夹名称",
            Text = detail.SeriesName,
            MaxLength = 120,
        };
        var candidates = new ComboBox
        {
            Header = "候选系列",
            DisplayMemberPath = nameof(SeriesCandidate.DisplayLabel),
            ItemsSource = detail.Candidates,
            HorizontalAlignment = HorizontalAlignment.Stretch,
        };
        candidates.SelectedItem = detail.Candidates.FirstOrDefault(candidate => candidate.IsCurrent)
            ?? detail.Candidates.FirstOrDefault();
        candidates.SelectionChanged += (_, _) =>
        {
            if (candidates.SelectedItem is SeriesCandidate candidate)
            {
                editor.Text = candidate.SeriesName;
            }
        };
        var batchScope = new CheckBox
        {
            Content = $"同时修正当前系列的 {detail.MatchingSeriesCount} 个条目",
            Visibility = detail.MatchingSeriesCount > 1
                ? Visibility.Visible
                : Visibility.Collapsed,
        };
        var lookupButton = new Button
        {
            Content = "联网查找更多候选",
            IsEnabled = detail.CanLoadCandidates,
            HorizontalAlignment = HorizontalAlignment.Left,
        };
        lookupButton.Click += async (_, _) =>
        {
            if (_isCandidateLookupActive || _isSavingCorrection)
            {
                return;
            }
            _isCandidateLookupActive = true;
            lookupButton.IsEnabled = false;
            UpdateCandidateLookupState();
            UpdateCorrectionButtonState();
            try
            {
                var result = await _sidecar.LoadCandidatesAsync(detail.Index, detail.PlansRevision);
                candidates.ItemsSource = result.Candidates;
                candidates.SelectedItem = result.Candidates.FirstOrDefault(candidate => candidate.IsCurrent)
                    ?? result.Candidates.FirstOrDefault();
                if (!string.IsNullOrWhiteSpace(result.Warning))
                {
                    ShowToast(result.Warning, ToastKind.Warning);
                }
            }
            catch (Exception exc)
            {
                ShowToast(exc.Message, ToastKind.Error);
            }
            finally
            {
                _isCandidateLookupActive = false;
                lookupButton.IsEnabled = detail.CanLoadCandidates
                    && _connectionState == ConnectionState.Ready
                    && _snapshot.Operation.State != "running";
                UpdateCandidateLookupState();
                UpdateCorrectionButtonState();
            }
        };
        var panel = new StackPanel { Spacing = 12, MaxWidth = 460 };
        panel.Children.Add(new TextBlock
        {
            Text = $"{detail.StatusLabel} · {detail.ResolverSource} · 置信度 {detail.ConfidenceLabel}",
            Foreground = ResourceBrush("TextFillColorSecondaryBrush"),
        });
        panel.Children.Add(new TextBlock
        {
            Text = $"作者：{detail.AuthorsLabel}　卷号：{detail.VolumeLabel}　语言：{detail.LanguageLabel}",
            TextWrapping = TextWrapping.Wrap,
            Foreground = ResourceBrush("TextFillColorSecondaryBrush"),
        });
        panel.Children.Add(new TextBlock
        {
            Text = $"标签：{detail.TagsLabel}",
            TextWrapping = TextWrapping.Wrap,
            Foreground = ResourceBrush("TextFillColorTertiaryBrush"),
        });
        panel.Children.Add(new TextBlock
        {
            Text = detail.Summary,
            MaxLines = 6,
            TextWrapping = TextWrapping.Wrap,
            Foreground = ResourceBrush("TextFillColorSecondaryBrush"),
        });
        panel.Children.Add(candidates);
        panel.Children.Add(lookupButton);
        panel.Children.Add(editor);
        panel.Children.Add(batchScope);
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
            await SaveCorrectionAsync(
                detail.Index,
                editor.Text,
                batchScope.IsChecked == true,
                detail.MatchingSeriesCount,
                detail.PlansRevision
            );
        }
    }

    private async Task SetCoverAsync(string? dataUri)
    {
        CoverImage.Source = null;
        CoverPlaceholder.Visibility = Visibility.Visible;
        if (string.IsNullOrWhiteSpace(dataUri) || dataUri.Length > MaxCoverDataUriChars)
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
            var image = new BitmapImage
            {
                DecodePixelWidth = 480,
                CreateOptions = BitmapCreateOptions.IgnoreImageCache,
            };
            await image.SetSourceAsync(stream);
            CoverImage.Source = image;
            CoverPlaceholder.Visibility = Visibility.Collapsed;
        }
        catch (Exception)
        {
            CoverImage.Source = null;
            CoverPlaceholder.Visibility = Visibility.Visible;
        }
    }

    private void ShowDetailEmpty()
    {
        _detail = null;
        CandidateList.ItemsSource = null;
        ApplySeriesGroupCheckBox.IsChecked = false;
        ApplySeriesGroupCheckBox.Visibility = Visibility.Collapsed;
        LoadCandidatesButton.Visibility = Visibility.Collapsed;
        CoverImage.Source = null;
        DetailLoadingState.Visibility = Visibility.Collapsed;
        DetailContent.Visibility = Visibility.Collapsed;
        DetailEmptyState.Visibility = Visibility.Visible;
        UpdateCompactDetailButtonState();
    }

    private async void OnSaveCorrectionClick(object sender, RoutedEventArgs e)
    {
        if (_detail is not null)
        {
            await SaveCorrectionAsync(
                _detail.Index,
                SeriesEditBox.Text,
                ApplySeriesGroupCheckBox.IsChecked == true,
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
            SeriesEditBox.Focus(FocusState.Programmatic);
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
