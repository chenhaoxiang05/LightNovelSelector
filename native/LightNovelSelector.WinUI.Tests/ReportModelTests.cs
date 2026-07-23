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
              "created_at": "2026-07-20T12:00:00+08:00",
              "item_count": 2,
              "items_truncated": true,
              "summary": { "total": 2, "moved": 1, "skipped": 1, "duplicates": 1, "errors": 0 },
              "items": [
                {
                  "source_path": "D:\\books\\demo.epub",
                  "target_path": "D:\\books\\Demo\\demo.epub",
                  "actual_target_path": "D:\\books\\Demo\\demo.epub",
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
        Assert.AreEqual(2, report.ItemCount);
        Assert.IsTrue(report.ItemsTruncated);
        Assert.AreEqual(1, report.Items.Count);
        Assert.AreEqual("demo.epub", report.Items[0].FileName);
        Assert.AreEqual("已移动", report.Items[0].OperationLabel);
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
}
