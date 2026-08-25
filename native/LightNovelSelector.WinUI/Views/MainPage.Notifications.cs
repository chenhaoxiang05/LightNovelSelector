using LightNovelSelector.WinUI.Helpers;
using LightNovelSelector.WinUI.ViewModels;
using Microsoft.UI.Xaml;

namespace LightNovelSelector.WinUI;

public sealed partial class MainPage
{
    private CancellationTokenSource? _toastCancellation;

    private void ShowToast(string message, ToastKind kind, int durationMilliseconds = 3800)
    {
        var revision = _toastLifecycle.Begin();
        _toastCancellation?.Cancel();
        _toastCancellation?.Dispose();
        _toastCancellation = new CancellationTokenSource();
        _ = ShowToastAsync(
            message,
            kind,
            durationMilliseconds,
            revision,
            _toastCancellation.Token
        );
    }

    private async Task ShowToastAsync(
        string message,
        ToastKind kind,
        int durationMilliseconds,
        long revision,
        CancellationToken cancellationToken
    )
    {
        ToastMessageText.Text = message;
        var (glyph, brushKey) = kind switch
        {
            ToastKind.Success => ("\uE73E", "SuccessTextBrush"),
            ToastKind.Warning => ("\uE7BA", "WarningTextBrush"),
            ToastKind.Error => ("\uEA39", "ErrorTextBrush"),
            _ => ("\uE946", "AppAccentBrush"),
        };
        ToastIcon.Glyph = glyph;
        ToastIcon.Foreground = ResourceBrush(brushKey);
        ToastHost.Visibility = Visibility.Visible;
        Motion.ShowTransient(ToastHost, show: true);
        try
        {
            await Task.Delay(durationMilliseconds, cancellationToken);
            await HideToastAsync(revision, cancellationToken);
        }
        catch (OperationCanceledException)
        {
        }
    }

    private async Task HideToastAsync(
        long revision,
        CancellationToken cancellationToken = default
    )
    {
        if (!_toastLifecycle.IsCurrent(revision))
        {
            return;
        }

        Motion.ShowTransient(ToastHost, show: false);
        await Task.Delay(
            TransientNotificationController.HideSettleDelayMilliseconds(Motion.ReducedMotion),
            cancellationToken
        );
        if (!_toastLifecycle.IsCurrent(revision) || cancellationToken.IsCancellationRequested)
        {
            return;
        }
        ToastHost.Visibility = Visibility.Collapsed;
    }

    private async Task DismissToastAsync()
    {
        var revision = _toastLifecycle.CurrentRevision;
        _toastCancellation?.Cancel();
        try
        {
            await HideToastAsync(revision);
        }
        catch (OperationCanceledException)
        {
        }
    }

    private async void OnDismissToastClick(object sender, RoutedEventArgs e) =>
        await DismissToastAsync();

    private enum ToastKind
    {
        Info,
        Success,
        Warning,
        Error,
    }
}
