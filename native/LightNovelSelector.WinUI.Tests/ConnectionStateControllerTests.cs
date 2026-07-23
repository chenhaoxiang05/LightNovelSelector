using LightNovelSelector.WinUI.Models;
using LightNovelSelector.WinUI.ViewModels;
using Microsoft.VisualStudio.TestTools.UnitTesting;

namespace LightNovelSelector.WinUI.Tests;

[TestClass]
public sealed class ConnectionStateControllerTests
{
    [TestMethod]
    [DataRow(ConnectionState.Connecting, false, false)]
    [DataRow(ConnectionState.Ready, true, false)]
    [DataRow(ConnectionState.Recovering, false, true)]
    [DataRow(ConnectionState.Disconnected, false, true)]
    public void PresentationControlsCoreActionsAndRecoveryBar(
        ConnectionState state,
        bool canUseCore,
        bool showRecoveryBar
    )
    {
        var presentation = ConnectionStateController.Describe(state);

        Assert.AreEqual(canUseCore, presentation.CanUseCore);
        Assert.AreEqual(showRecoveryBar, presentation.ShowRecoveryBar);
        Assert.IsFalse(string.IsNullOrWhiteSpace(presentation.Label));
        Assert.IsFalse(string.IsNullOrWhiteSpace(presentation.ForegroundBrushKey));
        Assert.IsFalse(string.IsNullOrWhiteSpace(presentation.BackgroundBrushKey));
    }
}
