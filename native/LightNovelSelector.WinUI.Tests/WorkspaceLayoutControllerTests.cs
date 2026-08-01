using LightNovelSelector.WinUI.ViewModels;
using Microsoft.VisualStudio.TestTools.UnitTesting;

namespace LightNovelSelector.WinUI.Tests;

[TestClass]
public sealed class WorkspaceLayoutControllerTests
{
    [TestMethod]
    public void WideWindowKeepsNavigationAndDetailVisible()
    {
        var layout = WorkspaceLayoutController.Describe(1440, 900);

        Assert.AreEqual(WorkspaceLayoutMode.Wide, layout.Mode);
        Assert.IsTrue(layout.KeepNavigationPaneOpen);
        Assert.IsTrue(layout.ShowSideDetail);
        Assert.IsFalse(layout.UseTwoColumnStats);
        Assert.AreEqual(340, layout.DetailWidth);
    }

    [TestMethod]
    public void CompactWindowPrioritizesResultsWithoutLosingDetailAccess()
    {
        var layout = WorkspaceLayoutController.Describe(1024, 700);

        Assert.AreEqual(WorkspaceLayoutMode.Compact, layout.Mode);
        Assert.IsFalse(layout.KeepNavigationPaneOpen);
        Assert.IsFalse(layout.ShowSideDetail);
        Assert.IsFalse(layout.UseTwoColumnStats);
        Assert.IsTrue(layout.UseCompactWorkflow);
        Assert.IsFalse(layout.StackFilters);
        Assert.IsFalse(layout.UseWorkspaceScroll);
        Assert.AreEqual(420, layout.DetailWidth);
    }

    [TestMethod]
    public void NarrowWindowStacksDenseControls()
    {
        var layout = WorkspaceLayoutController.Describe(720, 680);

        Assert.AreEqual(WorkspaceLayoutMode.Narrow, layout.Mode);
        Assert.IsTrue(layout.StackFolderActions);
        Assert.IsTrue(layout.StackFilters);
        Assert.IsTrue(layout.StackOperationActions);
        Assert.IsTrue(layout.UseTwoColumnStats);
        Assert.IsTrue(layout.UseCompactPadding);
        Assert.IsTrue(layout.UseWorkspaceScroll);
        Assert.AreEqual(420, layout.DetailWidth);
    }

    [TestMethod]
    public void BreakpointsAreDeterministic()
    {
        Assert.AreEqual(
            WorkspaceLayoutMode.Compact,
            WorkspaceLayoutController.Describe(
                WorkspaceLayoutController.CompactBreakpoint,
                800
            ).Mode
        );
        Assert.AreEqual(
            WorkspaceLayoutMode.Wide,
            WorkspaceLayoutController.Describe(
                WorkspaceLayoutController.WideBreakpoint,
                800
            ).Mode
        );
    }

    [TestMethod]
    public void InvalidDimensionsFallBackToSafestLayout()
    {
        var layout = WorkspaceLayoutController.Describe(double.NaN, double.PositiveInfinity);

        Assert.AreEqual(WorkspaceLayoutMode.Narrow, layout.Mode);
        Assert.IsTrue(layout.StackFilters);
        Assert.IsTrue(layout.UseCompactWorkflow);
        Assert.IsTrue(layout.UseWorkspaceScroll);
        Assert.AreEqual(320, layout.DetailWidth);
    }
}
