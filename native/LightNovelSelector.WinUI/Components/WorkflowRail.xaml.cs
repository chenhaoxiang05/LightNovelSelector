using LightNovelSelector.WinUI.Models;
using Microsoft.UI;
using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Controls;
using Microsoft.UI.Xaml.Media;
using Windows.UI.Text;

namespace LightNovelSelector.WinUI.Components;

public sealed partial class WorkflowRail : UserControl
{
    private static readonly FontFamily WorkflowTextFont = new("Segoe UI Variable Text");
    private static readonly FontFamily WorkflowIconFont = new("Segoe Fluent Icons");

    public WorkflowRail()
    {
        InitializeComponent();
    }

    public void SetVersion(string text) => VersionText.Text = text;

    public void ApplyPaneLayout(bool paneExpanded, bool useCompactWorkflow)
    {
        WorkflowEyebrow.Visibility = paneExpanded ? Visibility.Visible : Visibility.Collapsed;
        VersionStack.Visibility = paneExpanded ? Visibility.Visible : Visibility.Collapsed;
        SafetyStatusText.Visibility = paneExpanded ? Visibility.Visible : Visibility.Collapsed;
        SafetyStatusBadge.Width = paneExpanded ? double.NaN : 36;
        SafetyStatusBadge.Height = paneExpanded ? double.NaN : 36;
        SafetyStatusBadge.Padding = paneExpanded ? new Thickness(9, 6, 9, 6) : new Thickness(0);
        SafetyStatusBadge.HorizontalAlignment = paneExpanded
            ? HorizontalAlignment.Stretch
            : HorizontalAlignment.Center;

        if (!paneExpanded)
        {
            WorkflowStepsPanel.Visibility = Visibility.Collapsed;
            CompactWorkflowSummary.Visibility = Visibility.Collapsed;
            return;
        }

        WorkflowStepsPanel.Visibility = useCompactWorkflow
            ? Visibility.Collapsed
            : Visibility.Visible;
        CompactWorkflowSummary.Visibility = useCompactWorkflow
            ? Visibility.Visible
            : Visibility.Collapsed;
    }

    public void Update(AppSnapshot snapshot, int planCount)
    {
        var hasFolder = !string.IsNullOrWhiteSpace(snapshot.Folder);
        var hasPlans = planCount > 0;
        var operation = snapshot.Operation;
        var isScanning = operation.Kind == "scan" && operation.State == "running";
        var isApplying = operation.Kind == "apply" && operation.State == "running";
        var applyCompleted = operation.Kind == "apply" && operation.State == "success";
        var applyFailed = operation.Kind == "apply" && operation.State is "error" or "cancelled";

        SetWorkflowStep(
            WorkflowStep1Badge,
            WorkflowStep1Glyph,
            WorkflowStep1Label,
            1,
            hasFolder ? WorkflowStepState.Completed : WorkflowStepState.Active
        );
        SetWorkflowStep(
            WorkflowStep2Badge,
            WorkflowStep2Glyph,
            WorkflowStep2Label,
            2,
            !hasFolder
                ? WorkflowStepState.Pending
                : isScanning || !hasPlans
                    ? WorkflowStepState.Active
                    : WorkflowStepState.Completed
        );
        SetWorkflowStep(
            WorkflowStep3Badge,
            WorkflowStep3Glyph,
            WorkflowStep3Label,
            3,
            !hasPlans || isScanning
                ? WorkflowStepState.Pending
                : isApplying || applyCompleted || applyFailed
                    ? WorkflowStepState.Completed
                    : WorkflowStepState.Active
        );
        SetWorkflowStep(
            WorkflowStep4Badge,
            WorkflowStep4Glyph,
            WorkflowStep4Label,
            4,
            applyCompleted
                ? WorkflowStepState.Completed
                : applyFailed
                    ? WorkflowStepState.Failed
                    : isApplying
                        ? WorkflowStepState.Active
                        : WorkflowStepState.Pending
        );

        CompactWorkflowStepText.Text = applyCompleted
            ? "当前：整理完成"
            : isApplying
                ? "当前：正在整理"
                : hasPlans
                    ? "当前：检查并修正"
                    : isScanning
                        ? "当前：扫描预览"
                        : hasFolder
                            ? "当前：扫描预览"
                            : "当前：选择目录";
    }

    private static void SetWorkflowStep(
        Border badge,
        TextBlock glyph,
        TextBlock label,
        int stepNumber,
        WorkflowStepState state
    )
    {
        if (badge.Tag is WorkflowStepState currentState && currentState == state)
        {
            return;
        }
        badge.Tag = state;

        var (surfaceKey, foregroundKey, text) = state switch
        {
            WorkflowStepState.Completed => ("SuccessSubtleBrush", "SuccessTextBrush", "\uE73E"),
            WorkflowStepState.Active => ("AccentSubtleBrush", "AppAccentBrush", stepNumber.ToString()),
            WorkflowStepState.Failed => ("ErrorSubtleBrush", "ErrorTextBrush", "\uE7BA"),
            _ => ("SubtleSurfaceBrush", "TextFillColorTertiaryBrush", stepNumber.ToString()),
        };

        badge.Background = ResourceBrush(surfaceKey);
        glyph.Foreground = ResourceBrush(foregroundKey);
        glyph.FontFamily = state is WorkflowStepState.Completed or WorkflowStepState.Failed
            ? WorkflowIconFont
            : WorkflowTextFont;
        glyph.Text = text;
        label.Foreground = ResourceBrush(
            state is WorkflowStepState.Active or WorkflowStepState.Failed
                ? foregroundKey
                : "TextFillColorSecondaryBrush"
        );
        label.FontWeight = new FontWeight
        {
            Weight = state == WorkflowStepState.Active ? (ushort)600 : (ushort)400,
        };
    }

    private static Brush ResourceBrush(string key) =>
        Application.Current.Resources[key] as Brush ?? new SolidColorBrush(Colors.Transparent);

    private enum WorkflowStepState
    {
        Pending,
        Active,
        Completed,
        Failed,
    }
}
