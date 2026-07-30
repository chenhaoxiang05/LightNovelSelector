using LightNovelSelector.WinUI.ViewModels;
using Microsoft.VisualStudio.TestTools.UnitTesting;

namespace LightNovelSelector.WinUI.Tests;

[TestClass]
public sealed class FocusCycleControllerTests
{
    [TestMethod]
    public void ForwardTraversalStartsAtFirstRegion()
    {
        Assert.AreEqual(0, FocusCycleController.NextIndex(-1, 4, reverse: false));
    }

    [TestMethod]
    public void BackwardTraversalStartsAtLastRegion()
    {
        Assert.AreEqual(3, FocusCycleController.NextIndex(-1, 4, reverse: true));
    }

    [TestMethod]
    public void TraversalWrapsInBothDirections()
    {
        Assert.AreEqual(0, FocusCycleController.NextIndex(3, 4, reverse: false));
        Assert.AreEqual(3, FocusCycleController.NextIndex(0, 4, reverse: true));
    }

    [TestMethod]
    public void EmptyRegionSetHasNoTarget()
    {
        Assert.AreEqual(-1, FocusCycleController.NextIndex(0, 0, reverse: false));
        Assert.AreEqual(-1, FocusCycleController.NextIndex(0, -1, reverse: true));
    }

    [TestMethod]
    public void InvalidCurrentIndexRestartsDeterministically()
    {
        Assert.AreEqual(0, FocusCycleController.NextIndex(9, 3, reverse: false));
        Assert.AreEqual(2, FocusCycleController.NextIndex(9, 3, reverse: true));
    }
}
