using LightNovelSelector.WinUI.ViewModels;
using Microsoft.VisualStudio.TestTools.UnitTesting;

namespace LightNovelSelector.WinUI.Tests;

[TestClass]
public sealed class WindowLaunchSizeControllerTests
{
    [TestMethod]
    [DataRow("1024x700", 1024, 700)]
    [DataRow("1440X900", 1440, 900)]
    public void ValidSmokeSizeIsParsed(string value, int width, int height)
    {
        Assert.IsTrue(WindowLaunchSizeController.TryParse(value, out var size));
        Assert.AreEqual(width, size.Width);
        Assert.AreEqual(height, size.Height);
    }

    [TestMethod]
    [DataRow(null)]
    [DataRow("")]
    [DataRow("639x700")]
    [DataRow("1024x479")]
    [DataRow("wide")]
    public void InvalidSmokeSizeIsRejected(string? value)
    {
        Assert.IsFalse(WindowLaunchSizeController.TryParse(value, out _));
    }
}
