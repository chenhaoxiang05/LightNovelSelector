namespace LightNovelSelector.WinUI.Security;

public static class ReportPathSafety
{
    private const string CanonicalReportName = "classification_report.json";
    private const string HistoryRootName = ".lightnovel-selector";
    private const string HistoryDirectoryName = "history";
    private const string HistoryFilePrefix = "classification_report-";

    public static string ValidateLocalReportPath(string rootPath, string reportPath)
    {
        if (
            string.IsNullOrWhiteSpace(rootPath)
            || string.IsNullOrWhiteSpace(reportPath)
            || !Path.IsPathFullyQualified(rootPath)
            || !Path.IsPathFullyQualified(reportPath)
        )
        {
            throw new InvalidDataException("分类报告路径无效。");
        }

        var root = Path.TrimEndingDirectorySeparator(Path.GetFullPath(rootPath));
        var report = Path.GetFullPath(reportPath);
        var canonical = Path.Combine(root, CanonicalReportName);
        var historyRoot = Path.Combine(root, HistoryRootName);
        var historyDirectory = Path.Combine(historyRoot, HistoryDirectoryName);
        var reportParent = Path.GetDirectoryName(report);
        var isCanonical = string.Equals(report, canonical, StringComparison.OrdinalIgnoreCase);
        var isHistory =
            string.Equals(reportParent, historyDirectory, StringComparison.OrdinalIgnoreCase)
            && IsHistoryFileName(Path.GetFileName(report));
        if (!isCanonical && !isHistory)
        {
            throw new InvalidDataException("分类报告不属于当前目录的报告位置。");
        }

        EnsureRegularPath(root, expectDirectory: true);
        if (isHistory)
        {
            EnsureRegularPath(historyRoot, expectDirectory: true);
            EnsureRegularPath(historyDirectory, expectDirectory: true);
        }
        EnsureRegularPath(report, expectDirectory: false);
        return report;
    }

    private static bool IsHistoryFileName(string fileName)
    {
        if (
            !fileName.StartsWith(HistoryFilePrefix, StringComparison.Ordinal)
            || !fileName.EndsWith(".json", StringComparison.OrdinalIgnoreCase)
        )
        {
            return false;
        }

        var payload = fileName[
            HistoryFilePrefix.Length..^".json".Length
        ];
        if (
            payload.Length != 49
            || payload[8] != 'T'
            || payload[15] != 'Z'
            || payload[16] != '-'
        )
        {
            return false;
        }
        return payload[..8].All(char.IsAsciiDigit)
            && payload[9..15].All(char.IsAsciiDigit)
            && payload[17..].Length == 32
            && payload[17..].All(character =>
                char.IsAsciiDigit(character) || character is >= 'a' and <= 'f'
            );
    }

    private static void EnsureRegularPath(string path, bool expectDirectory)
    {
        FileAttributes attributes;
        try
        {
            attributes = File.GetAttributes(path);
        }
        catch (Exception exc) when (
            exc is IOException
                or UnauthorizedAccessException
                or System.Security.SecurityException
        )
        {
            throw new InvalidDataException("分类报告或其目录当前不可用。", exc);
        }

        if ((attributes & FileAttributes.ReparsePoint) != 0)
        {
            throw new InvalidDataException("分类报告路径不能包含符号链接或目录联接。");
        }
        var isDirectory = (attributes & FileAttributes.Directory) != 0;
        if (isDirectory != expectDirectory)
        {
            throw new InvalidDataException(
                expectDirectory ? "分类报告目录无效。" : "分类报告不是普通文件。"
            );
        }
    }
}
