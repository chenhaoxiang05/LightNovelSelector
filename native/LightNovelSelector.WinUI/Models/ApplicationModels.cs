namespace LightNovelSelector.WinUI.Models;

public enum ConnectionState
{
    Connecting,
    Ready,
    Recovering,
    Disconnected,
}

public sealed class AppSnapshot
{
    public AppInfo App { get; init; } = new();
    public string Folder { get; init; } = string.Empty;
    public AppSettings Settings { get; init; } = new();
    public OperationState Operation { get; init; } = new();
    public PlanCounts Counts { get; init; } = new();
    public string? ReportPath { get; init; }
    public int PlansRevision { get; init; }
    public IReadOnlyList<PlanItem>? Plans { get; init; }
    public IReadOnlyList<LogEntry> Logs { get; init; } = [];
    public int LogCursor { get; init; }
}

public sealed class AppInfo
{
    public string Name { get; init; } = string.Empty;
    public string Version { get; init; } = string.Empty;
}

public sealed class AppSettings
{
    public bool UseNetwork { get; init; } = true;
    public bool Recursive { get; init; }
    public bool AutoRename { get; init; }
    public IReadOnlyList<CustomRule> CustomRules { get; init; } = [];
    public string LastFolder { get; init; } = string.Empty;
}

public sealed class CustomRule
{
    public string Pattern { get; init; } = string.Empty;
    public string Series { get; init; } = string.Empty;
}

public sealed class OperationState
{
    public int Id { get; init; }
    public string Kind { get; init; } = "idle";
    public string State { get; init; } = "idle";
    public string Message { get; init; } = string.Empty;
    public int Done { get; init; }
    public int Total { get; init; }
    public bool CanCancel { get; init; }
    public string? Error { get; init; }
}

public sealed class PlanCounts
{
    public int Ready { get; init; }
    public int Duplicate { get; init; }
    public int Error { get; init; }
    public int Unchanged { get; init; }
    public int Moved { get; init; }
    public int Series { get; init; }
}

public sealed class BookIdentity
{
    public string Title { get; init; } = string.Empty;
    public string SeriesName { get; init; } = string.Empty;
    public IReadOnlyList<string> Authors { get; init; } = [];
    public int? VolumeNumber { get; init; }
    public string? Language { get; init; }
    public IReadOnlyList<string> Tags { get; init; } = [];
}

public sealed class PlanItem
{
    public int Index { get; set; }
    public string FileName { get; set; } = string.Empty;
    public string Extension { get; set; } = string.Empty;
    public string SourcePath { get; set; } = string.Empty;
    public BookIdentity Identity { get; set; } = new();
    public string BookTitle { get; set; } = string.Empty;
    public string SeriesName { get; set; } = string.Empty;
    public IReadOnlyList<string> Authors { get; set; } = [];
    public string AuthorsLabel { get; set; } = string.Empty;
    public int? VolumeNumber { get; set; }
    public string VolumeLabel { get; set; } = string.Empty;
    public string? Language { get; set; }
    public string LanguageLabel { get; set; } = string.Empty;
    public IReadOnlyList<string> Tags { get; set; } = [];
    public string TagsLabel { get; set; } = string.Empty;
    public string SeriesKey { get; set; } = string.Empty;
    public string TargetDir { get; set; } = string.Empty;
    public string TargetPath { get; set; } = string.Empty;
    public string TargetName { get; set; } = string.Empty;
    public string ResolverSource { get; set; } = string.Empty;
    public double Confidence { get; set; }
    public string ConfidenceLabel { get; set; } = string.Empty;
    public string Status { get; set; } = string.Empty;
    public string StatusLabel { get; set; } = string.Empty;
    public string Note { get; set; } = string.Empty;
    public string? DuplicateOf { get; set; }
    public string? RenameTo { get; set; }
    public string? MetadataTitle { get; set; }
    public string? MetadataUrl { get; set; }
    public bool HasLocalCover { get; set; }
    public bool WillMove { get; set; }
}

public sealed class LogEntry
{
    public int Id { get; set; }
    public string Time { get; set; } = string.Empty;
    public string Kind { get; set; } = "info";
    public string Message { get; set; } = string.Empty;
}

public sealed class BookDetail
{
    public int Index { get; init; }
    public BookIdentity Identity { get; init; } = new();
    public string Title { get; init; } = string.Empty;
    public string Summary { get; init; } = string.Empty;
    public string? SubjectUrl { get; init; }
    public string? CoverDataUrl { get; init; }
    public string CoverSource { get; init; } = string.Empty;
    public string FileName { get; init; } = string.Empty;
    public string SourcePath { get; init; } = string.Empty;
    public string TargetPath { get; init; } = string.Empty;
    public string SeriesName { get; init; } = string.Empty;
    public IReadOnlyList<string> Authors { get; init; } = [];
    public string AuthorsLabel { get; init; } = string.Empty;
    public int? VolumeNumber { get; init; }
    public string VolumeLabel { get; init; } = string.Empty;
    public string? Language { get; init; }
    public string LanguageLabel { get; init; } = string.Empty;
    public IReadOnlyList<string> Tags { get; init; } = [];
    public string TagsLabel { get; init; } = string.Empty;
    public string ResolverSource { get; init; } = string.Empty;
    public string ConfidenceLabel { get; init; } = string.Empty;
    public string Status { get; init; } = string.Empty;
    public string StatusLabel { get; init; } = string.Empty;
    public string Note { get; init; } = string.Empty;
    public string? Warning { get; init; }
}

public sealed class SaveSettingsResult
{
    public bool Saved { get; init; }
    public string? Warning { get; init; }
    public AppSnapshot State { get; init; } = new();
}

public sealed class CancelResult
{
    public bool Cancelled { get; init; }
    public AppSnapshot State { get; init; } = new();
}

public sealed class ReportSummary
{
    public string Path { get; init; } = string.Empty;
    public string? CreatedAt { get; init; }
    public int ItemCount { get; init; }
    public bool ItemsTruncated { get; init; }
    public ReportStats Summary { get; init; } = new();
    public IReadOnlyList<ReportItem> Items { get; init; } = [];
}

public sealed class ReportStats
{
    public int Total { get; init; }
    public int Moved { get; init; }
    public int Skipped { get; init; }
    public int Duplicates { get; init; }
    public int Errors { get; init; }
}

public sealed class ReportItem
{
    public string SourcePath { get; set; } = string.Empty;
    public string TargetPath { get; set; } = string.Empty;
    public string? ActualTargetPath { get; set; }
    public BookIdentity? Identity { get; set; }
    public string SeriesName { get; set; } = string.Empty;
    public string ResolverSource { get; set; } = string.Empty;
    public double Confidence { get; set; }
    public string Status { get; set; } = string.Empty;
    public string Operation { get; set; } = string.Empty;
    public string Note { get; set; } = string.Empty;

    public string FileName => System.IO.Path.GetFileName(SourcePath);
    public string DestinationPath => ActualTargetPath ?? TargetPath;
    public string OperationLabel => Operation == "moved" ? "已移动" : "已跳过";
}

public sealed class SidecarPing
{
    public int ProtocolVersion { get; init; }
    public string AppName { get; init; } = string.Empty;
    public string AppVersion { get; init; } = string.Empty;
    public int ProcessId { get; init; }
}
