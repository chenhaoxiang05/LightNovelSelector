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

    private async void OnResultSelectionChanged(object sender, SelectionChangedEventArgs e)
    {
        _detailCancellation?.Cancel();
        _detailCancellation?.Dispose();
        var cancellation = new CancellationTokenSource();
        _detailCancellation = cancellation;
        if (ResultsList.SelectedItem is not PlanItem plan)
        {
            _detailCancellation = null;
            cancellation.Dispose();
            ShowDetailEmpty();
            return;
        }

        DetailEmptyState.Visibility = Visibility.Collapsed;
        DetailContent.Visibility = Visibility.Collapsed;
        DetailLoadingState.Visibility = Visibility.Visible;
        try
        {
            var detail = await _sidecar.GetDetailAsync(plan.Index, cancellation.Token);
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
            ShowToast(exc.Message, ToastKind.Error);
        }
        finally
        {
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
        OpenSubjectButton.IsEnabled = UriSafety.TryCreatePublicHttpsUri(detail.SubjectUrl, out _);
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
            MaxLength = 120,
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
        CoverImage.Source = null;
        DetailLoadingState.Visibility = Visibility.Collapsed;
        DetailContent.Visibility = Visibility.Collapsed;
        DetailEmptyState.Visibility = Visibility.Visible;
    }

    private async void OnSaveCorrectionClick(object sender, RoutedEventArgs e)
    {
        if (_detail is not null)
        {
            await SaveCorrectionAsync(_detail.Index, SeriesEditBox.Text);
        }
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
            ResultsList.SelectedItem = VisiblePlans.FirstOrDefault(item => item.Index == index);
            ShowToast("分类结果已手动修正。", ToastKind.Success);
        }
        catch (Exception exc)
        {
            ShowToast(exc.Message, ToastKind.Error);
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
