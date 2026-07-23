using LightNovelSelector.WinUI.Models;

namespace LightNovelSelector.WinUI.ViewModels;

public readonly record struct ConnectionPresentation(
    string Label,
    string ForegroundBrushKey,
    string BackgroundBrushKey,
    bool CanUseCore,
    bool ShowRecoveryBar
);

public static class ConnectionStateController
{
    public static ConnectionPresentation Describe(ConnectionState state) => state switch
    {
        ConnectionState.Ready => new(
            "分类核心已连接",
            "SuccessTextBrush",
            "SuccessSubtleBrush",
            CanUseCore: true,
            ShowRecoveryBar: false
        ),
        ConnectionState.Recovering => new(
            "正在恢复分类核心",
            "WarningTextBrush",
            "WarningSubtleBrush",
            CanUseCore: false,
            ShowRecoveryBar: true
        ),
        ConnectionState.Disconnected => new(
            "分类核心连接中断",
            "ErrorTextBrush",
            "ErrorSubtleBrush",
            CanUseCore: false,
            ShowRecoveryBar: true
        ),
        _ => new(
            "正在连接分类核心",
            "AppAccentBrush",
            "AccentSubtleBrush",
            CanUseCore: false,
            ShowRecoveryBar: false
        ),
    };
}
