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
            "当前没有启用的联网元数据来源，本地识别仍可正常使用。",
            description
        );
    }

    [TestMethod]
    public void DescriptionReportsCoolingWithoutHidingHealthySources()
    {
        var description = MetadataProviderDisplay.BuildDescription(
            [
                new MetadataProviderInfo
                {
                    Name = "Bangumi",
                    Status = "cooldown",
                },
                new MetadataProviderInfo
                {
                    Name = "AniList",
                    Status = "healthy",
                },
                new MetadataProviderInfo
                {
                    Name = "Jikan",
                    Enabled = false,
                    Status = "disabled",
                },
            ]
        );

        Assert.AreEqual(
            "当前来源：Bangumi、AniList。当前有 1 个来源正在冷却，其余来源和本地识别继续工作。",
            description
        );
    }

    [TestMethod]
    public void EditableProviderBuildsReadableHealthDetail()
    {
        var provider = new EditableMetadataProvider(
            new MetadataProviderInfo
            {
                Id = "demo",
                Name = "示例来源",
                Status = "cooldown",
                StatusLabel = "暂时冷却",
                CooldownRemainingSeconds = 12,
                LastError = "请求超时",
            }
        );

        Assert.AreEqual("暂时冷却", provider.StatusLabel);
        Assert.AreEqual("12 秒后可重试 · 请求超时", provider.StatusDetail);
    }
}
