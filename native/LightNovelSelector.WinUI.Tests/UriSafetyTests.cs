using LightNovelSelector.WinUI.Security;

namespace LightNovelSelector.WinUI.Tests;

[TestClass]
public sealed class UriSafetyTests
{
    [DataRow("https://bgm.tv/subject/123")]
    [DataRow("https://example.com:8443/path?q=1")]
    [TestMethod]
    public void PublicHttpsUrisAreAccepted(string value)
    {
        Assert.IsTrue(UriSafety.TryCreatePublicHttpsUri(value, out var uri));
        Assert.IsNotNull(uri);
        Assert.AreEqual(Uri.UriSchemeHttps, uri.Scheme);
    }

    [DataRow("http://bgm.tv/subject/123")]
    [DataRow("file:///C:/Windows/win.ini")]
    [DataRow("https://user:secret@example.com/path")]
    [DataRow("https://localhost/path")]
    [DataRow("https://127.0.0.1/path")]
    [DataRow("https://10.0.0.1/path")]
    [DataRow("https://192.168.1.1/path")]
    [DataRow("https://[::1]/path")]
    [DataRow("not a uri")]
    [TestMethod]
    public void UnsafeUrisAreRejected(string value)
    {
        Assert.IsFalse(UriSafety.TryCreatePublicHttpsUri(value, out var uri));
        Assert.IsNull(uri);
    }
}
