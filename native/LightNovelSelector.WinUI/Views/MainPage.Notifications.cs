using LightNovelSelector.WinUI.Helpers;
using Microsoft.UI.Xaml;

namespace LightNovelSelector.WinUI;

public sealed partial class MainPage
{
    private CancellationTokenSource? _toastCancellation;

    private void ShowToast(string message, ToastKind kind, int durationMilliseconds = 3800)
    {
        _toastCancellation?.Cancel();
        _toastCancellation?.Dispose();
        _toastCancellation = new CancellationTokenSource();
        _ = ShowToastAsync(message, kind, durationMilliseconds, _toastCancellation.Token);
    }

    private async Task ShowToastAsync(
        string message,
        ToastKind kind,
        int durationMilliseconds,
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
            await HideToastAsync(cancellationToken);
        }
        catch (OperationCanceledException)
        {
        }
    }

    private async Task HideToastAsync(CancellationToken cancellationToken = default)
    {
        Motion.ShowTransient(ToastHost, show: false);
        if (!Motion.ReducedMotion)
        {
            await Task.Delay(150, cancellationToken);
        }
        ToastHost.Visibility = Visibility.Collapsed;
    }

    private async void OnDismissToastClick(object sender, RoutedEventArgs e)
    {
        _toastCancellation?.Cancel();
        try
        {
            await HideToastAsync();
        }
        catch (OperationCanceledException)
        {
        }
    }

    private enum ToastKind
    {
        Info,
        Success,
        Warning,
        Error,
    }
}
