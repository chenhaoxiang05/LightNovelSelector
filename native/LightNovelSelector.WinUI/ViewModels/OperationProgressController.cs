using LightNovelSelector.WinUI.Models;

namespace LightNovelSelector.WinUI.ViewModels;

public readonly record struct OperationProgressPresentation(
    bool IsIndeterminate,
    double Value,
    string Text,
    bool ShouldAnimate,
    string BrushKey
);

public static class OperationProgressController
{
    public static OperationProgressPresentation Describe(
        OperationState operation,
        int previousOperationId
    )
    {
        ArgumentNullException.ThrowIfNull(operation);

        var hasTotal = operation.Total > 0;
        var done = hasTotal ? Math.Clamp(operation.Done, 0, operation.Total) : 0;
        var value = hasTotal ? (double)done / operation.Total * 100 : 0;
        var brushKey = operation.State switch
        {
            "success" => "SuccessTextBrush",
            "error" => "ErrorTextBrush",
            "cancelled" => "WarningTextBrush",
            _ => "AppAccentBrush",
        };

        return new(
            IsIndeterminate: operation.State == "running" && !hasTotal,
            Value: value,
            Text: hasTotal ? $"{done} / {operation.Total}" : string.Empty,
            ShouldAnimate: hasTotal && operation.Id == previousOperationId,
            BrushKey: brushKey
        );
    }
}
