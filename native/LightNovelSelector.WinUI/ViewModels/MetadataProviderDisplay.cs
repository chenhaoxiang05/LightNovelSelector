using LightNovelSelector.WinUI.Models;

namespace LightNovelSelector.WinUI.ViewModels;

public static class MetadataProviderDisplay
{
    public static string BuildDescription(
        IEnumerable<MetadataProviderInfo>? providers
    )
    {
        var activeProviders = (providers ?? [])
            .Where(provider => provider.Enabled)
            .ToArray();
        var names = activeProviders
            .Select(provider => provider.Name?.Trim())
            .Where(name => !string.IsNullOrWhiteSpace(name))
            .Distinct(StringComparer.Ordinal)
            .ToArray();

        if (names.Length == 0)
        {
            return "当前没有启用的联网元数据来源，本地识别仍可正常使用。";
        }

        var coolingCount = activeProviders.Count(provider => provider.Status == "cooldown");
        var healthText = coolingCount > 0
            ? $"当前有 {coolingCount} 个来源正在冷却，其余来源和本地识别继续工作。"
            : "来源彼此隔离，部分不可用时仍会保留成功结果。";
        return $"当前来源：{string.Join("、", names)}。{healthText}";
    }
}
