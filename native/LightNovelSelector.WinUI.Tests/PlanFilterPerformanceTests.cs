using System.Diagnostics;
using LightNovelSelector.WinUI.Models;
using LightNovelSelector.WinUI.ViewModels;
using Microsoft.VisualStudio.TestTools.UnitTesting;

namespace LightNovelSelector.WinUI.Tests;

[TestClass]
public sealed class PlanFilterPerformanceTests
{
    private const int RowCount = 10_000;

    [TestMethod]
    [TestCategory("Performance")]
    public void TenThousandRowsCanBeSearchedAndGroupedWithinBudget()
    {
        var plans = Enumerable
            .Range(0, RowCount)
            .Select(index => new PlanItem
            {
                Index = index,
                FileName = $"小说-{index:00000}.epub",
                BookTitle = $"作品 {index:00000}",
                SeriesName = $"系列 {index / 20:0000}",
                AuthorsLabel = $"作者 {index % 100:000}",
                LanguageLabel = index % 2 == 0 ? "简体中文" : "日语",
                TagsLabel = index % 3 == 0 ? "奇幻 · 冒险" : "校园 · 青春",
                TargetName = $"目标-{index:00000}.epub",
                ResolverSource = index % 2 == 0 ? "本地识别" : "元数据缓存",
                Status = index % 17 == 0 ? "duplicate" : "ready",
            })
            .ToArray();

        _ = PlanFilterController.Apply(
            plans,
            new PlanFilterState("目标-09999", string.Empty, string.Empty)
        );

        var stopwatch = Stopwatch.StartNew();
        IReadOnlyList<PlanItem> result = [];
        for (var iteration = 0; iteration < 10; iteration++)
        {
            result = PlanFilterController.Apply(
                plans,
                new PlanFilterState("目标-09999", string.Empty, "ready")
            );
        }
        var series = PlanFilterController.SeriesOptions(plans);
        stopwatch.Stop();

        Assert.AreEqual(1, result.Count);
        Assert.AreEqual(500, series.Count);
        Assert.IsTrue(
            stopwatch.Elapsed < TimeSpan.FromSeconds(2),
            $"10,000 行筛选耗时 {stopwatch.Elapsed.TotalMilliseconds:F0} ms，超过 2 秒预算。"
        );
    }
}
