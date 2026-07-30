using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Data;
using Microsoft.UI.Xaml.Media;

namespace LightNovelSelector.WinUI.Converters;

public sealed class StatusBrushConverter : IValueConverter
{
    public object Convert(object value, Type targetType, object parameter, string language)
    {
        var status = value as string ?? string.Empty;
        var background = string.Equals(parameter as string, "background", StringComparison.OrdinalIgnoreCase);
        var key = status switch
        {
            "ready" or "moved" or "unchanged" => background ? "SuccessSubtleBrush" : "SuccessTextBrush",
            "duplicate" => background ? "WarningSubtleBrush" : "WarningTextBrush",
            "error" => background ? "ErrorSubtleBrush" : "ErrorTextBrush",
            _ => background ? "AccentSubtleBrush" : "AppAccentBrush",
        };
        return Application.Current.Resources[key] as Brush ?? new SolidColorBrush(Microsoft.UI.Colors.Transparent);
    }

    public object ConvertBack(object value, Type targetType, object parameter, string language) =>
        throw new NotSupportedException();
}

public sealed class StatusGlyphConverter : IValueConverter
{
    public object Convert(object value, Type targetType, object parameter, string language) => (value as string) switch
    {
        "ready" or "moved" or "unchanged" => "\uE73E",
        "duplicate" => "\uE8C8",
        "error" => "\uEA39",
        _ => "\uE946",
    };

    public object ConvertBack(object value, Type targetType, object parameter, string language) =>
        throw new NotSupportedException();
}

public sealed class LogKindConverter : IValueConverter
{
    public object Convert(object value, Type targetType, object parameter, string language) => (value as string) switch
    {
        "success" => "成功",
        "warning" => "提醒",
        "error" => "错误",
        _ => "信息",
    };

    public object ConvertBack(object value, Type targetType, object parameter, string language) =>
        throw new NotSupportedException();
}
