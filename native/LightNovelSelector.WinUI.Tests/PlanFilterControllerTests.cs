using LightNovelSelector.WinUI.Models;
using LightNovelSelector.WinUI.ViewModels;
using Microsoft.VisualStudio.TestTools.UnitTesting;

namespace LightNovelSelector.WinUI.Tests;

[TestClass]
public sealed class PlanFilterControllerTests
{
    private static readonly IReadOnlyList<PlanItem> Plans =
    [
        new()
        {
            Index = 0,
            FileName = "青春物语 01.epub",
            BookTitle = "我的青春恋爱物语果然有问题",
            SeriesName = "青春物语",
            AuthorsLabel = "渡航",
            LanguageLabel = "简体中文",
            TagsLabel = "校园 · 青春",
            TargetName = "青春物语 第01卷.epub",
            ResolverSource = "自定义规则",
            Status = "ready",
        },
        new()
        {
            Index = 1,
            FileName = "Moon-02.txt",
            SeriesName = "月夜档案",
            TargetName = "月夜档案 02.txt",
            ResolverSource = "文件名识别",
            Status = "duplicate",
        },
        new()
        {
            Index = 2,
            FileName = "unknown.pdf",
            SeriesName = "待确认",
            TargetName = "unknown.pdf",
            ResolverSource = "元数据缓存",
            Status = "error",
        },
    ];

    [TestMethod]
    [DataRow("青春物语", 0)]
    [DataRow("第01卷", 0)]
    [DataRow("文件名识别", 1)]
    [DataRow("UNKNOWN", 2)]
    [DataRow("渡航", 0)]
    [DataRow("校园", 0)]
    [DataRow("简体中文", 0)]
    public void SearchCoversAllVisibleFields(string query, int expectedIndex)
    {
        var result = PlanFilterController.Apply(Plans, new PlanFilterState(query, string.Empty, string.Empty));

        Assert.AreEqual(1, result.Count);
        Assert.AreEqual(expectedIndex, result[0].Index);
    }

    [TestMethod]
    public void SeriesAndStatusFiltersCanBeCombined()
    {
        var result = PlanFilterController.Apply(Plans, new PlanFilterState(string.Empty, "月夜档案", "duplicate"));

        Assert.AreEqual(1, result.Count);
        Assert.AreEqual(1, result[0].Index);
    }

    [TestMethod]
    public void FilteringDoesNotMutateTheMasterPlan()
    {
        var result = PlanFilterController.Apply(Plans, new PlanFilterState("不存在", string.Empty, string.Empty));

        Assert.AreEqual(0, result.Count);
        Assert.AreEqual(3, Plans.Count);
        Assert.AreEqual("ready", Plans[0].Status);
    }

    [TestMethod]
    public void MalformedNullFieldsDoNotBreakFiltering()
    {
        var malformed = new PlanItem
        {
            FileName = null!,
            SeriesName = null!,
            TargetName = null!,
            ResolverSource = null!,
            Status = null!,
        };

        var result = PlanFilterController.Apply([malformed], new PlanFilterState("demo", string.Empty, string.Empty));

        Assert.AreEqual(0, result.Count);
    }

    [TestMethod]
    public void SeriesOptionsAreUniqueAndSorted()
    {
        var plans = Plans.Concat(
        [
            new PlanItem { SeriesName = "青春物语" },
            new PlanItem { SeriesName = "" },
        ]);

        var result = PlanFilterController.SeriesOptions(plans);

        var expected = new[] { "青春物语", "待确认", "月夜档案" }
            .OrderBy(name => name, StringComparer.CurrentCultureIgnoreCase)
            .ToArray();
        CollectionAssert.AreEqual(expected, result.ToArray());
    }
}
