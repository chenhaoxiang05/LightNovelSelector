using LightNovelSelector.WinUI.Models;
using LightNovelSelector.WinUI.Security;
using Microsoft.UI;
using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Controls;
using Microsoft.UI.Xaml.Media;
using Microsoft.UI.Xaml.Media.Imaging;
using Windows.Storage.Streams;

namespace LightNovelSelector.WinUI.Components;

public sealed partial class FileDetailPane : UserControl
{
    private const int MaxCoverDataUriChars = 12 * 1024 * 1024;

    public event RoutedEventHandler? CloseRequested;
    public event RoutedEventHandler? CandidateLookupRequested;
    public event RoutedEventHandler? CorrectionRequested;
    public event RoutedEventHandler? CorrectionScopeChanged;
    public event RoutedEventHandler? RetryRequested;
    public event RoutedEventHandler? RevealFileRequested;
    public event RoutedEventHandler? OpenSubjectRequested;

    public Control SeriesEditorFocusTarget => SeriesEditBox;
    public Control CandidateListFocusTarget => CandidateList;
    public Control SaveCorrectionFocusTarget => SaveCorrectionButton;
    public Control RevealFileFocusTarget => RevealFileButton;
    public string EditedSeriesName => SeriesEditBox.Text;
    public bool ApplyToSeriesGroup => ApplySeriesGroupCheckBox.IsChecked == true;

    public FileDetailPane()
    {
        InitializeComponent();
    }

    public void SetCompactMode(bool compact)
    {
        CloseDetailButton.Visibility = compact ? Visibility.Visible : Visibility.Collapsed;
    }

    public void FocusInitial()
    {
        Control target = CloseDetailButton.Visibility == Visibility.Visible
            ? CloseDetailButton
            : SeriesEditBox;
        target.Focus(FocusState.Programmatic);
    }

    public void FocusSeriesEditor() => SeriesEditBox.Focus(FocusState.Programmatic);

    public void SetBatchScopeChecked(bool value) => ApplySeriesGroupCheckBox.IsChecked = value;

    public void ShowLoading()
    {
        DetailEmptyState.Visibility = Visibility.Collapsed;
        DetailErrorState.Visibility = Visibility.Collapsed;
        DetailContent.Visibility = Visibility.Collapsed;
        DetailLoadingState.Visibility = Visibility.Visible;
    }

    public void ShowError(string message)
    {
        DetailLoadingState.Visibility = Visibility.Collapsed;
        DetailEmptyState.Visibility = Visibility.Collapsed;
        DetailContent.Visibility = Visibility.Collapsed;
        DetailErrorMessageText.Text = string.IsNullOrWhiteSpace(message)
            ? "请稍后重试。"
            : message;
        DetailErrorState.Visibility = Visibility.Visible;
    }

    public void ShowEmpty()
    {
        CandidateList.ItemsSource = null;
        ApplySeriesGroupCheckBox.IsChecked = false;
        ApplySeriesGroupCheckBox.Visibility = Visibility.Collapsed;
        LoadCandidatesButton.Visibility = Visibility.Collapsed;
        CoverImage.Source = null;
        CoverPlaceholder.Visibility = Visibility.Visible;
        DetailWarningBar.IsOpen = false;
        DetailLoadingState.Visibility = Visibility.Collapsed;
        DetailErrorState.Visibility = Visibility.Collapsed;
        DetailContent.Visibility = Visibility.Collapsed;
        DetailEmptyState.Visibility = Visibility.Visible;
    }

    public async Task RenderAsync(BookDetail detail)
    {
        DetailTitleText.Text = detail.Title;
        DetailAuthorsText.Text = detail.AuthorsLabel;
        DetailVolumeText.Text = detail.VolumeLabel;
        DetailLanguageText.Text = detail.LanguageLabel;
        DetailTagsText.Text = detail.TagsLabel;
        DetailSummaryText.Text = detail.Summary;
        DetailTargetText.Text = detail.TargetPath;
        DetailConfidenceText.Text =
            $"{detail.ResolverSource} · 置信度 {detail.ConfidenceLabel} · {detail.ConfidenceLevel}";
        DetailReasonText.Text = detail.ClassificationReason;
        DetailEvidenceText.Text = detail.ClassificationEvidence.Count > 0
            ? string.Join(" · ", detail.ClassificationEvidence)
            : "当前结果没有额外证据。";
        DetailCoverSourceText.Text = detail.CoverSource;
        DetailStatusText.Text = detail.StatusLabel;
        DetailStatusIcon.Text = StatusGlyph(detail.Status);
        DetailStatusBadge.Background = StatusBrush(detail.Status, background: true);
        DetailStatusText.Foreground = StatusBrush(detail.Status, background: false);
        DetailStatusIcon.Foreground = StatusBrush(detail.Status, background: false);
        SeriesEditBox.Text = detail.SeriesName;
        SetCandidates(detail.Candidates);
        ApplySeriesGroupCheckBox.IsChecked = false;
        ApplySeriesGroupCheckBox.Content = $"同时修正当前系列的 {detail.MatchingSeriesCount} 个条目";
        ApplySeriesGroupCheckBox.Visibility = detail.MatchingSeriesCount > 1
            ? Visibility.Visible
            : Visibility.Collapsed;
        LoadCandidatesButton.Visibility = detail.CanLoadCandidates
            ? Visibility.Visible
            : Visibility.Collapsed;
        DetailWarningBar.IsOpen = !string.IsNullOrWhiteSpace(detail.Warning);
        DetailWarningBar.Message = detail.Warning ?? string.Empty;
        OpenSubjectButton.IsEnabled = UriSafety.TryCreatePublicHttpsUri(detail.SubjectUrl, out _);
        await SetCoverAsync(detail.CoverDataUrl);
        DetailLoadingState.Visibility = Visibility.Collapsed;
        DetailErrorState.Visibility = Visibility.Collapsed;
        DetailEmptyState.Visibility = Visibility.Collapsed;
        DetailContent.Visibility = Visibility.Visible;
    }

    public void SetCandidates(IReadOnlyList<SeriesCandidate> candidates)
    {
        CandidateList.ItemsSource = candidates;
        CandidateList.SelectedItem = candidates.FirstOrDefault(candidate => candidate.IsCurrent)
            ?? candidates.FirstOrDefault();
    }

    public void SetCandidateLookupState(bool active, bool enabled)
    {
        CandidateLookupProgress.IsActive = active;
        CandidateLookupProgress.Visibility = active
            ? Visibility.Visible
            : Visibility.Collapsed;
        LoadCandidatesButton.IsEnabled = enabled;
    }

    public void SetCorrectionState(bool enabled, string label)
    {
        SaveCorrectionText.Text = label;
        SaveCorrectionButton.IsEnabled = enabled;
    }

    private async Task SetCoverAsync(string? dataUri)
    {
        CoverImage.Source = null;
        CoverPlaceholder.Visibility = Visibility.Visible;
        if (
            string.IsNullOrWhiteSpace(dataUri)
            || dataUri.Length > MaxCoverDataUriChars
            || !dataUri.StartsWith("data:image/", StringComparison.OrdinalIgnoreCase)
        )
        {
            return;
        }

        var markerIndex = dataUri.IndexOf(";base64,", StringComparison.OrdinalIgnoreCase);
        if (markerIndex < 0 || markerIndex + 8 >= dataUri.Length)
        {
            return;
        }
        try
        {
            var bytes = Convert.FromBase64String(dataUri[(markerIndex + 8)..]);
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
        catch
        {
            CoverImage.Source = null;
            CoverPlaceholder.Visibility = Visibility.Visible;
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

    private void OnCloseDetailClick(object sender, RoutedEventArgs e) =>
        CloseRequested?.Invoke(this, e);

    private void OnCandidateLookupClick(object sender, RoutedEventArgs e) =>
        CandidateLookupRequested?.Invoke(this, e);

    private void OnCorrectionClick(object sender, RoutedEventArgs e) =>
        CorrectionRequested?.Invoke(this, e);

    private void OnCorrectionScopeChanged(object sender, RoutedEventArgs e) =>
        CorrectionScopeChanged?.Invoke(this, e);

    private void OnRetryDetailClick(object sender, RoutedEventArgs e) =>
        RetryRequested?.Invoke(this, e);

    private void OnRevealFileClick(object sender, RoutedEventArgs e) =>
        RevealFileRequested?.Invoke(this, e);

    private void OnOpenSubjectClick(object sender, RoutedEventArgs e) =>
        OpenSubjectRequested?.Invoke(this, e);

    private void OnCandidateSelectionChanged(object sender, SelectionChangedEventArgs e)
    {
        if (CandidateList.SelectedItem is SeriesCandidate candidate)
        {
            SeriesEditBox.Text = candidate.SeriesName;
        }
    }
}
