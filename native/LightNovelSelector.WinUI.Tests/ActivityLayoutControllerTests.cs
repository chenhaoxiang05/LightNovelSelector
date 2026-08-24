using LightNovelSelector.WinUI.ViewModels;
using Microsoft.VisualStudio.TestTools.UnitTesting;

namespace LightNovelSelector.WinUI.Tests;

[TestClass]
public sealed class ActivityLayoutControllerTests
{
    [TestMethod]
    public void WideWindowKeepsReportColumnsVisible()
    {
        var layout = ActivityLayoutController.Describe(1440, 900);

        Assert.AreEqual(ActivityLayoutMode.Split, layout.Mode);
        Assert.IsFalse(layout.StackSummaryActions);
        Assert.IsFalse(layout.UseScroll);
        Assert.AreEqual(270, layout.HistoryWidth);
        Assert.AreEqual(0, layout.MainMinimumHeight);
    }

    [TestMethod]
    public void ShortWindowKeepsColumnsAndEnablesScrolling()
    {
        var layout = ActivityLayoutController.Describe(1024, 700);

        Assert.AreEqual(ActivityLayoutMode.Split, layout.Mode);
        Assert.IsTrue(layout.UseScroll);
        Assert.AreEqual(430, layout.MainMinimumHeight);
    }

    [TestMethod]
    public void HalfScreenStacksReportRegionsWithBoundedListViewports()
    {
        var layout = ActivityLayoutController.Describe(853, 1019);

        Assert.AreEqual(ActivityLayoutMode.Stacked, layout.Mode);
        Assert.IsFalse(layout.StackSummaryActions);
        Assert.IsTrue(layout.UseScroll);
        Assert.AreEqual(220, layout.HistoryViewportHeight);
        Assert.AreEqual(260, layout.ReportItemsViewportHeight);
        Assert.AreEqual(200, layout.LogsViewportHeight);
    }

    [TestMethod]
    public void NarrowWindowAlsoStacksSummaryActions()
    {
        var layout = ActivityLayoutController.Describe(720, 680);

        Assert.AreEqual(ActivityLayoutMode.Stacked, layout.Mode);
        Assert.IsTrue(layout.StackSummaryActions);
        Assert.IsTrue(layout.UseScroll);
        Assert.AreEqual(704, layout.MainMinimumHeight);
    }

    [TestMethod]
    public void ContentBreakpointIsDeterministic()
    {
        Assert.AreEqual(
            ActivityLayoutMode.Stacked,
            ActivityLayoutController.Describe(
                ActivityLayoutController.StackedContentBreakpoint - 1,
                900
            ).Mode
        );
        Assert.AreEqual(
            ActivityLayoutMode.Split,
            ActivityLayoutController.Describe(
                ActivityLayoutController.StackedContentBreakpoint,
                900
            ).Mode
        );
    }

    [TestMethod]
    public void InvalidDimensionsFallBackToSafestLayout()
    {
        var layout = ActivityLayoutController.Describe(double.NaN, double.PositiveInfinity);

        Assert.AreEqual(ActivityLayoutMode.Stacked, layout.Mode);
        Assert.IsTrue(layout.StackSummaryActions);
        Assert.IsTrue(layout.UseScroll);
    }
}
