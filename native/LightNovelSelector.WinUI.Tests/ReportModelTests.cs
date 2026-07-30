using System.Text.Json;
using LightNovelSelector.WinUI.Models;
using Microsoft.VisualStudio.TestTools.UnitTesting;

namespace LightNovelSelector.WinUI.Tests;

[TestClass]
public sealed class ReportModelTests
{
    private static readonly JsonSerializerOptions JsonOptions = new(JsonSerializerDefaults.Web)
    {
        PropertyNameCaseInsensitive = true,
        PropertyNamingPolicy = JsonNamingPolicy.SnakeCaseLower,
    };

    [TestMethod]
    public void CurrentReportPayloadDeserializesToTypedModels()
    {
        const string payload = """
            {
              "path": "D:\\books\\classification_report.json",
              "report_id": "0123456789abcdef0123456789abcdef",
              "created_at": "2026-07-20T12:00:00+08:00",
              "can_undo": true,
              "item_count": 2,
              "items_truncated": true,
              "summary": { "total": 2, "moved": 1, "skipped": 1, "duplicates": 1, "errors": 0 },
              "items": [
                {
                  "source_path": "D:\\books\\demo.epub",
                  "target_path": "D:\\books\\Demo\\demo.epub",
                  "actual_target_path": "D:\\books\\Demo\\demo.epub",
                  "identity": {
                    "title": "Demo 第01卷",
                    "series_name": "Demo",
                    "authors": ["Example Author"],
                    "volume_number": 1,
                    "language": "en",
                    "tags": ["Fantasy"]
                  },
                  "series_name": "Demo",
                  "resolver_source": "文件名识别",
                  "confidence": 0.9,
                  "status": "moved",
                  "operation": "moved",
                  "note": ""
                }
              ]
            }
            """;

        var report = JsonSerializer.Deserialize<ReportSummary>(payload, JsonOptions);

        Assert.IsNotNull(report);
        Assert.AreEqual(1, report.Summary.Moved);
        Assert.AreEqual("0123456789abcdef0123456789abcdef", report.ReportId);
        Assert.IsTrue(report.CanUndo);
        Assert.AreEqual(2, report.ItemCount);
        Assert.IsTrue(report.ItemsTruncated);
        Assert.AreEqual(1, report.Items.Count);
        Assert.AreEqual("demo.epub", report.Items[0].FileName);
        Assert.AreEqual("已移动", report.Items[0].OperationLabel);
        Assert.AreEqual("Demo 第01卷", report.Items[0].Identity?.Title);
    }

    [TestMethod]
    public void OlderReportWithoutOptionalFieldsKeepsSafeDefaults()
    {
        const string payload = """
            {
              "path": "classification_report.json",
              "summary": { "moved": 0 },
              "items": [
                { "source_path": "old.txt", "target_path": "Archive\\old.txt", "operation": "skipped" }
              ]
            }
            """;

        var report = JsonSerializer.Deserialize<ReportSummary>(payload, JsonOptions);

        Assert.IsNotNull(report);
        Assert.AreEqual(0, report.Summary.Errors);
        Assert.AreEqual(0, report.ItemCount);
        Assert.IsFalse(report.ItemsTruncated);
        Assert.AreEqual("Archive\\old.txt", report.Items[0].DestinationPath);
        Assert.AreEqual("已跳过", report.Items[0].OperationLabel);
    }

    [TestMethod]
    public void ReportHistoryPayloadDeserializesWithDisplayLabels()
    {
        const string payload = """
            {
              "reports": [
                {
                  "report_id": "0123456789abcdef0123456789abcdef",
                  "path": "D:\\books\\.lightnovel-selector\\history\\classification_report.json",
                  "file_name": "classification_report.json",
                  "created_at": "2026-07-20T12:00:00+08:00",
                  "version": "2.1.0-dev.3",
                  "is_latest": true,
                  "undo_completed": false,
                  "can_undo": true,
                  "status": "available",
                  "status_label": "可撤销",
                  "summary": {
                    "total": 3,
                    "moved": 2,
                    "skipped": 1,
                    "duplicates": 0,
                    "errors": 0
                  }
                }
              ],
              "total_count": 1,
              "invalid_count": 0,
              "truncated": false,
              "warning": null
            }
            """;

        var history = JsonSerializer.Deserialize<ReportHistoryResult>(payload, JsonOptions);

        Assert.IsNotNull(history);
        Assert.AreEqual(1, history.TotalCount);
        Assert.AreEqual(1, history.Reports.Count);
        Assert.IsTrue(history.Reports[0].CanUndo);
        Assert.AreEqual("最近 · 可撤销", history.Reports[0].DisplayStatusLabel);
        StringAssert.Contains(history.Reports[0].TitleLabel, "2026-07-20");
        Assert.AreEqual("移动 2 · 跳过 1 · 错误 0", history.Reports[0].SummaryLabel);
        Assert.AreEqual(history.Reports[0].AccessibilityLabel, history.Reports[0].ToString());
        StringAssert.Contains(history.Reports[0].AccessibilityLabel, "最近 · 可撤销");
    }

    [TestMethod]
    public void OlderHistoryPayloadKeepsSafeDefaults()
    {
        const string payload = """
            {
              "reports": [
                {
                  "report_id": "latest",
                  "path": "classification_report.json",
                  "summary": { "moved": 0 }
                }
              ]
            }
            """;

        var history = JsonSerializer.Deserialize<ReportHistoryResult>(payload, JsonOptions);

        Assert.IsNotNull(history);
        Assert.AreEqual(0, history.InvalidCount);
        Assert.IsFalse(history.Truncated);
        Assert.AreEqual("latest", history.Reports[0].ReportId);
        Assert.AreEqual("时间未知", history.Reports[0].CreatedAtLabel);
        Assert.IsFalse(history.Reports[0].CanUndo);
    }
}
