using LightNovelSelector.WinUI.ViewModels;
using Microsoft.VisualStudio.TestTools.UnitTesting;

namespace LightNovelSelector.WinUI.Tests;

[TestClass]
public sealed class WindowCloseGuardControllerTests
{
    [TestMethod]
    public void CleanIdleWindowCanClose()
    {
        var action = WindowCloseGuardController.Describe(
            confirmedClose: false,
            criticalOperation: false,
            activeDialog: false,
            unsavedSettings: false
        );

        Assert.AreEqual(WindowCloseAction.Allow, action);
    }

    [TestMethod]
    public void CriticalFileOperationHasHighestBlockingPriority()
    {
        var action = WindowCloseGuardController.Describe(
            confirmedClose: false,
            criticalOperation: true,
            activeDialog: true,
            unsavedSettings: true
        );

        Assert.AreEqual(WindowCloseAction.BlockCriticalOperation, action);
    }

    [TestMethod]
    public void ActiveDialogPreventsAnotherClosePrompt()
    {
        var action = WindowCloseGuardController.Describe(
            confirmedClose: false,
            criticalOperation: false,
            activeDialog: true,
            unsavedSettings: true
        );

        Assert.AreEqual(WindowCloseAction.BlockActiveDialog, action);
    }

    [TestMethod]
    public void DirtySettingsRequireConfirmation()
    {
        var action = WindowCloseGuardController.Describe(
            confirmedClose: false,
            criticalOperation: false,
            activeDialog: false,
            unsavedSettings: true
        );

        Assert.AreEqual(WindowCloseAction.ConfirmUnsavedSettings, action);
    }

    [TestMethod]
    public void ConfirmedCloseCannotReenterTheGuard()
    {
        var action = WindowCloseGuardController.Describe(
            confirmedClose: true,
            criticalOperation: true,
            activeDialog: true,
            unsavedSettings: true
        );

        Assert.AreEqual(WindowCloseAction.Allow, action);
    }
}
