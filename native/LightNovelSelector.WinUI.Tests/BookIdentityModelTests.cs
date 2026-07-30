using System.Text.Json;
using LightNovelSelector.WinUI.Models;
using Microsoft.VisualStudio.TestTools.UnitTesting;

namespace LightNovelSelector.WinUI.Tests;

[TestClass]
public sealed class BookIdentityModelTests
{
    private static readonly JsonSerializerOptions JsonOptions = new(JsonSerializerDefaults.Web)
    {
        PropertyNameCaseInsensitive = true,
        PropertyNamingPolicy = JsonNamingPolicy.SnakeCaseLower,
    };

    [TestMethod]
    public void PlanPayloadDeserializesUnifiedIdentity()
    {
        const string payload = """
            {
              "file_name": "demo.epub",
              "book_title": "无职转生 第13卷",
              "series_name": "无职转生",
              "authors_label": "理不尽な孫の手",
              "volume_number": 13,
              "volume_label": "第 13 卷",
              "language": "zh-Hans",
              "language_label": "简体中文",
              "tags_label": "异世界 · 成长",
              "identity": {
                "title": "无职转生 第13卷",
                "series_name": "无职转生",
                "authors": ["理不尽な孫の手"],
                "volume_number": 13,
                "language": "zh-Hans",
                "tags": ["异世界", "成长"]
              }
            }
            """;

        var plan = JsonSerializer.Deserialize<PlanItem>(payload, JsonOptions);

        Assert.IsNotNull(plan);
        Assert.AreEqual("无职转生 第13卷", plan.Identity.Title);
        Assert.AreEqual("无职转生", plan.Identity.SeriesName);
        Assert.AreEqual(13, plan.Identity.VolumeNumber);
        CollectionAssert.AreEqual(new[] { "理不尽な孫の手" }, plan.Identity.Authors.ToArray());
        CollectionAssert.AreEqual(new[] { "异世界", "成长" }, plan.Identity.Tags.ToArray());
    }

    [TestMethod]
    public void OlderPayloadWithoutIdentityKeepsSafeDefaults()
    {
        const string payload = """
            { "file_name": "old.txt", "series_name": "旧系列" }
            """;

        var plan = JsonSerializer.Deserialize<PlanItem>(payload, JsonOptions);

        Assert.IsNotNull(plan);
        Assert.AreEqual("旧系列", plan.SeriesName);
        Assert.AreEqual(string.Empty, plan.Identity.Title);
        Assert.AreEqual(0, plan.Identity.Authors.Count);
        Assert.AreEqual(0, plan.Identity.Tags.Count);
    }
}
