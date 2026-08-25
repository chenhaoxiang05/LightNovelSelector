using LightNovelSelector.WinUI.ViewModels;
using Microsoft.VisualStudio.TestTools.UnitTesting;

namespace LightNovelSelector.WinUI.Tests;

[TestClass]
public sealed class TransientNotificationControllerTests
{
    [TestMethod]
    public void FirstNotificationBecomesCurrent()
    {
        var controller = new TransientNotificationController();

        var revision = controller.Begin();

        Assert.IsTrue(controller.IsCurrent(revision));
        Assert.AreEqual(revision, controller.CurrentRevision);
    }

    [TestMethod]
    public void ReplacementSupersedesPendingDismissal()
    {
        var controller = new TransientNotificationController();
        var dismissedRevision = controller.Begin();

        var replacementRevision = controller.Begin();

        Assert.IsFalse(controller.IsCurrent(dismissedRevision));
        Assert.IsTrue(controller.IsCurrent(replacementRevision));
    }

    [TestMethod]
    public void InvalidationPreventsLateCompletion()
    {
        var controller = new TransientNotificationController();
        var revision = controller.Begin();

        controller.Invalidate();

        Assert.IsFalse(controller.IsCurrent(revision));
    }

    [TestMethod]
    public void ReducedMotionRetainsShortOpacitySettleTime()
    {
        Assert.AreEqual(
            90,
            TransientNotificationController.HideSettleDelayMilliseconds(reducedMotion: true)
        );
        Assert.AreEqual(
            150,
            TransientNotificationController.HideSettleDelayMilliseconds(reducedMotion: false)
        );
    }
}
