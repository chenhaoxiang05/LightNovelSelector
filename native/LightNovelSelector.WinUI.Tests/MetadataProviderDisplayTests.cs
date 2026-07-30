using LightNovelSelector.WinUI.Models;
using LightNovelSelector.WinUI.ViewModels;
using Microsoft.VisualStudio.TestTools.UnitTesting;

namespace LightNovelSelector.WinUI.Tests;

[TestClass]
public sealed class MetadataProviderDisplayTests
{
    [TestMethod]
    public void DescriptionUsesActualDistinctProviderNames()
    {
        var providers = new[]
        {
            new MetadataProviderInfo { Name = "Bangumi" },
            new MetadataProviderInfo { Name = " AniList " },
            new MetadataProviderInfo { Name = "Bangumi" },
            new MetadataProviderInfo { Name = " " },
        };

        var description = MetadataProviderDisplay.BuildDescription(providers);

        Assert.AreEqual(
            "当前来源：Bangumi、AniList。来源彼此隔离，部分不可用时仍会保留成功结果。",
            description
        );
    }

    [TestMethod]
    public void EmptyInventoryExplainsLocalFallback()
    {
        var description = MetadataProviderDisplay.BuildDescription([]);

        Assert.AreEqual(
            "当前没有可用的联网元数据来源，本地识别仍可正常使用。",
            description
        );
    }
}
