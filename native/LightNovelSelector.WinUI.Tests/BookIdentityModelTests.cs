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
              "confidence_label": "92%",
              "confidence_level": "高",
              "classification_reason": "命中了本地修正记忆。",
              "classification_evidence": ["人工修正记忆精确匹配", "识别到第 13 卷"],
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
        Assert.AreEqual("92% · 高", plan.ConfidenceDisplayLabel);
        Assert.AreEqual("命中了本地修正记忆。", plan.ClassificationReason);
        CollectionAssert.AreEqual(
            new[] { "人工修正记忆精确匹配", "识别到第 13 卷" },
            plan.ClassificationEvidence.ToArray()
        );
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

    [TestMethod]
    public void CandidateLookupPayloadDeserializesComparisonFields()
    {
        const string payload = """
            {
              "index": 2,
              "warning": null,
              "candidates": [
                {
                  "title": "Demo 第03卷",
                  "series_name": "Demo",
                  "authors_label": "Example Author",
                  "volume_label": "第 3 卷",
                  "language_label": "英语",
                  "tags_label": "Fantasy",
                  "source": "Bangumi",
                  "confidence": 0.91,
                  "confidence_label": "91%",
                  "is_current": true,
                  "current_label": "当前",
                  "identity": {
                    "title": "Demo 第03卷",
                    "series_name": "Demo"
                  }
                }
              ]
            }
            """;

        var result = JsonSerializer.Deserialize<CandidateLookupResult>(payload, JsonOptions);

        Assert.IsNotNull(result);
        Assert.AreEqual(2, result.Index);
        Assert.AreEqual(1, result.Candidates.Count);
        Assert.IsTrue(result.Candidates[0].IsCurrent);
        Assert.AreEqual("Demo · Bangumi 91%", result.Candidates[0].DisplayLabel);
    }

    [TestMethod]
    public void BatchEditPayloadKeepsUpdatedCountAndSnapshot()
    {
        const string payload = """
            {
              "updated_count": 3,
              "updated_indices": [0, 1, 4],
              "snapshot": {
                "plans_revision": 7,
                "plans": []
              }
            }
            """;

        var result = JsonSerializer.Deserialize<EditPlansResult>(payload, JsonOptions);

        Assert.IsNotNull(result);
        Assert.AreEqual(3, result.UpdatedCount);
        CollectionAssert.AreEqual(new[] { 0, 1, 4 }, result.UpdatedIndices.ToArray());
        Assert.AreEqual(7, result.Snapshot.PlansRevision);
    }

    [TestMethod]
    public void SnapshotDeserializesMetadataProviderInventory()
    {
        const string payload = """
            {
              "metadata_providers": [
                {
                  "id": "bangumi",
                  "name": "Bangumi",
                  "priority": 10,
                  "enabled": false,
                  "status": "disabled",
                  "status_label": "已禁用"
                },
                {
                  "id": "community",
                  "name": "社区书库",
                  "priority": 40,
                  "status": "cooldown",
                  "status_label": "暂时冷却",
                  "cooldown_remaining_seconds": 18
                }
              ],
              "settings": {
                "provider_settings": [
                  { "provider_id": "community", "enabled": true, "priority": 40 }
                ]
              }
            }
            """;

        var snapshot = JsonSerializer.Deserialize<AppSnapshot>(payload, JsonOptions);

        Assert.IsNotNull(snapshot);
        Assert.AreEqual(2, snapshot.MetadataProviders.Count);
        Assert.AreEqual("community", snapshot.MetadataProviders[1].Id);
        Assert.AreEqual("社区书库", snapshot.MetadataProviders[1].Name);
        Assert.AreEqual(40, snapshot.MetadataProviders[1].Priority);
        Assert.AreEqual("cooldown", snapshot.MetadataProviders[1].Status);
        Assert.AreEqual(18, snapshot.MetadataProviders[1].CooldownRemainingSeconds);
        Assert.IsFalse(snapshot.MetadataProviders[0].Enabled);
        Assert.AreEqual("community", snapshot.Settings.ProviderSettings[0].ProviderId);
    }

    [TestMethod]
    public void SettingsSerializeProviderControlsWithSnakeCaseContract()
    {
        var settings = new AppSettings
        {
            ProviderSettings =
            [
                new MetadataProviderSetting
                {
                    ProviderId = "bangumi",
                    Enabled = false,
                    Priority = 25,
                },
            ],
        };

        var payload = JsonSerializer.Serialize(settings, JsonOptions);
        using var document = JsonDocument.Parse(payload);
        var provider = document.RootElement.GetProperty("provider_settings")[0];

        Assert.AreEqual("bangumi", provider.GetProperty("provider_id").GetString());
        Assert.IsFalse(provider.GetProperty("enabled").GetBoolean());
        Assert.AreEqual(25, provider.GetProperty("priority").GetInt32());
    }
}
