using LightNovelSelector.WinUI.Models;
using Microsoft.VisualStudio.TestTools.UnitTesting;

namespace LightNovelSelector.WinUI.Tests;

[TestClass]
public sealed class AccessibilityLabelTests
{
    [TestMethod]
    public void PlanLabelSummarizesDecisionAndDestination()
    {
        var plan = new PlanItem
        {
            StatusLabel = "可执行",
            SeriesName = "测试系列",
            FileName = "第一卷.epub",
            TargetName = "测试系列 01.epub",
            ConfidenceLabel = "92%",
            ResolverSource = "文件名",
        };

        StringAssert.Contains(plan.AccessibilityLabel, "可执行");
        StringAssert.Contains(plan.AccessibilityLabel, "第一卷.epub");
        StringAssert.Contains(plan.AccessibilityLabel, "测试系列 01.epub");
        StringAssert.Contains(plan.AccessibilityLabel, "92%");
    }

    [TestMethod]
    public void CandidateLabelIdentifiesCurrentChoice()
    {
        var candidate = new SeriesCandidate
        {
            SeriesName = "测试系列",
            Source = "本地解析",
            ConfidenceLabel = "88%",
            IsCurrent = true,
        };

        Assert.AreEqual(
            "测试系列，来源 本地解析，置信度 88%，当前结果",
            candidate.AccessibilityLabel
        );
    }

    [TestMethod]
    public void LogAndReportLabelsExposeTheirStatus()
    {
        var log = new LogEntry
        {
            Time = "10:20:30",
            Kind = "warning",
            Message = "文件被占用",
        };
        var report = new ReportItem
        {
            SourcePath = @"D:\Books\demo.epub",
            TargetPath = @"D:\Books\Demo\demo.epub",
            Operation = "skipped",
        };

        Assert.AreEqual("10:20:30，警告，文件被占用", log.AccessibilityLabel);
        StringAssert.StartsWith(report.AccessibilityLabel, "已跳过，文件 demo.epub");
    }
}
