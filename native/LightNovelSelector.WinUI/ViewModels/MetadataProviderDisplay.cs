using LightNovelSelector.WinUI.Models;

namespace LightNovelSelector.WinUI.ViewModels;

public static class MetadataProviderDisplay
{
    public static string BuildDescription(
        IEnumerable<MetadataProviderInfo>? providers
    )
    {
        var names = (providers ?? [])
            .Select(provider => provider.Name?.Trim())
            .Where(name => !string.IsNullOrWhiteSpace(name))
            .Distinct(StringComparer.Ordinal)
            .ToArray();

        return names.Length > 0
            ? $"当前来源：{string.Join("、", names)}。来源彼此隔离，部分不可用时仍会保留成功结果。"
            : "当前没有可用的联网元数据来源，本地识别仍可正常使用。";
    }
}
