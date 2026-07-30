using LightNovelSelector.WinUI.Security;

namespace LightNovelSelector.WinUI.Tests;

[TestClass]
public sealed class ReportPathSafetyTests
{
    [TestMethod]
    public void CanonicalAndArchivedReportsAreAccepted()
    {
        using var temporary = new TemporaryDirectory();
        var root = temporary.Path;
        var canonical = Path.Combine(root, "classification_report.json");
        File.WriteAllText(canonical, "{}");
        var history = Path.Combine(root, ".lightnovel-selector", "history");
        Directory.CreateDirectory(history);
        var archived = Path.Combine(
            history,
            "classification_report-20260720T120000Z-0123456789abcdef0123456789abcdef.json"
        );
        File.WriteAllText(archived, "{}");

        Assert.AreEqual(
            Path.GetFullPath(canonical),
            ReportPathSafety.ValidateLocalReportPath(root, canonical)
        );
        Assert.AreEqual(
            Path.GetFullPath(archived),
            ReportPathSafety.ValidateLocalReportPath(root, archived)
        );
    }

    [TestMethod]
    public void OutsideAndUnexpectedHistoryFilesAreRejected()
    {
        using var temporary = new TemporaryDirectory();
        var root = Path.Combine(temporary.Path, "library");
        Directory.CreateDirectory(root);
        var outside = Path.Combine(temporary.Path, "classification_report.json");
        File.WriteAllText(outside, "{}");
        var history = Path.Combine(root, ".lightnovel-selector", "history");
        Directory.CreateDirectory(history);
        var unexpected = Path.Combine(history, "other.json");
        File.WriteAllText(unexpected, "{}");
        var malformed = Path.Combine(history, "classification_report-not-an-id.json");
        File.WriteAllText(malformed, "{}");

        Assert.Throws<InvalidDataException>(
            () => ReportPathSafety.ValidateLocalReportPath(root, outside)
        );
        Assert.Throws<InvalidDataException>(
            () => ReportPathSafety.ValidateLocalReportPath(root, unexpected)
        );
        Assert.Throws<InvalidDataException>(
            () => ReportPathSafety.ValidateLocalReportPath(root, malformed)
        );
    }

    [TestMethod]
    public void SymbolicLinkReportIsRejectedWhenSupported()
    {
        using var temporary = new TemporaryDirectory();
        var root = Path.Combine(temporary.Path, "library");
        Directory.CreateDirectory(root);
        var outside = Path.Combine(temporary.Path, "outside.json");
        File.WriteAllText(outside, "{}");
        var report = Path.Combine(root, "classification_report.json");
        try
        {
            File.CreateSymbolicLink(report, outside);
        }
        catch (Exception exc) when (
            exc is IOException
                or UnauthorizedAccessException
                or PlatformNotSupportedException
        )
        {
            Assert.Inconclusive($"当前环境无法创建符号链接：{exc.Message}");
        }

        Assert.Throws<InvalidDataException>(
            () => ReportPathSafety.ValidateLocalReportPath(root, report)
        );
    }

    private sealed class TemporaryDirectory : IDisposable
    {
        public string Path { get; } = System.IO.Path.Combine(
            System.IO.Path.GetTempPath(),
            $"LightNovelSelector.Tests.{Guid.NewGuid():N}"
        );

        public TemporaryDirectory()
        {
            Directory.CreateDirectory(Path);
        }

        public void Dispose()
        {
            try
            {
                Directory.Delete(Path, recursive: true);
            }
            catch (IOException)
            {
            }
            catch (UnauthorizedAccessException)
            {
            }
        }
    }
}
