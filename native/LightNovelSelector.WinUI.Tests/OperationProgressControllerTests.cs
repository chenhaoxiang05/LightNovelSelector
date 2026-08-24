using LightNovelSelector.WinUI.Models;
using LightNovelSelector.WinUI.ViewModels;
using Microsoft.VisualStudio.TestTools.UnitTesting;

namespace LightNovelSelector.WinUI.Tests;

[TestClass]
public sealed class OperationProgressControllerTests
{
    [TestMethod]
    public void ExistingOperationUsesDeterminateAnimatedProgress()
    {
        var presentation = OperationProgressController.Describe(
            Operation(id: 7, state: "running", done: 2, total: 5),
            previousOperationId: 7
        );

        Assert.IsFalse(presentation.IsIndeterminate);
        Assert.AreEqual(40, presentation.Value, 0.001);
        Assert.AreEqual("2 / 5", presentation.Text);
        Assert.IsTrue(presentation.ShouldAnimate);
        Assert.AreEqual("AppAccentBrush", presentation.BrushKey);
    }

    [TestMethod]
    public void NewOperationResetsProgressWithoutAnimation()
    {
        var presentation = OperationProgressController.Describe(
            Operation(id: 8, state: "running", done: 1, total: 5),
            previousOperationId: 7
        );

        Assert.AreEqual(20, presentation.Value, 0.001);
        Assert.IsFalse(presentation.ShouldAnimate);
    }

    [TestMethod]
    [DataRow(-2, 0, "0 / 5")]
    [DataRow(7, 100, "5 / 5")]
    public void InvalidCompletedCountsAreClampedForPresentation(
        int done,
        double expectedValue,
        string expectedText
    )
    {
        var presentation = OperationProgressController.Describe(
            Operation(id: 3, state: "running", done: done, total: 5),
            previousOperationId: 3
        );

        Assert.AreEqual(expectedValue, presentation.Value, 0.001);
        Assert.AreEqual(expectedText, presentation.Text);
    }

    [TestMethod]
    [DataRow("running", true)]
    [DataRow("error", false)]
    [DataRow("cancelled", false)]
    public void MissingTotalIsOnlyIndeterminateWhileRunning(string state, bool expected)
    {
        var presentation = OperationProgressController.Describe(
            Operation(id: 4, state: state, done: 0, total: 0),
            previousOperationId: 4
        );

        Assert.AreEqual(expected, presentation.IsIndeterminate);
        Assert.AreEqual(0, presentation.Value);
        Assert.AreEqual(string.Empty, presentation.Text);
        Assert.IsFalse(presentation.ShouldAnimate);
    }

    [TestMethod]
    [DataRow("success", "SuccessTextBrush")]
    [DataRow("error", "ErrorTextBrush")]
    [DataRow("cancelled", "WarningTextBrush")]
    [DataRow("running", "AppAccentBrush")]
    public void TerminalStateSelectsSemanticProgressBrush(string state, string expectedBrush)
    {
        var presentation = OperationProgressController.Describe(
            Operation(id: 5, state: state, done: 2, total: 5),
            previousOperationId: 5
        );

        Assert.AreEqual(expectedBrush, presentation.BrushKey);
    }

    private static OperationState Operation(int id, string state, int done, int total) => new()
    {
        Id = id,
        Kind = "scan",
        State = state,
        Done = done,
        Total = total,
    };
}
