using System.ComponentModel;
using System.Runtime.CompilerServices;

namespace LightNovelSelector.WinUI.Models;

public sealed class EditableMetadataProvider : INotifyPropertyChanged
{
    private string _statusLabel = "尚未请求";
    private string _statusDetail = string.Empty;

    public EditableMetadataProvider(MetadataProviderInfo info)
    {
        Id = info.Id;
        Name = info.Name;
        Enabled = info.Enabled;
        Priority = info.Priority;
        DefaultPriority = info.DefaultPriority;
        UpdateHealth(info);
    }

    public string Id { get; }
    public string Name { get; }
    public bool Enabled { get; set; }
    public double Priority { get; set; }
    public int DefaultPriority { get; }
    public string StatusLabel
    {
        get => _statusLabel;
        private set => SetField(ref _statusLabel, value);
    }

    public string StatusDetail
    {
        get => _statusDetail;
        private set => SetField(ref _statusDetail, value);
    }

    public event PropertyChangedEventHandler? PropertyChanged;

    public void UpdateHealth(MetadataProviderInfo info)
    {
        StatusLabel = info.StatusLabel;
        StatusDetail = info.Status switch
        {
            "disabled" => "不会发起联网请求",
            "cooldown" when info.CooldownRemainingSeconds > 0 =>
                $"{info.CooldownRemainingSeconds} 秒后可重试"
                + ErrorSuffix(info.LastError),
            "degraded" => "最近一次请求失败" + ErrorSuffix(info.LastError),
            "healthy" => $"成功 {info.Successes} 次，失败 {info.Failures} 次",
            _ => "尚无运行数据",
        };
    }

    private static string ErrorSuffix(string? error) =>
        string.IsNullOrWhiteSpace(error) ? string.Empty : $" · {error}";

    private void SetField(ref string field, string value, [CallerMemberName] string? propertyName = null)
    {
        if (field == value)
        {
            return;
        }
        field = value;
        PropertyChanged?.Invoke(this, new PropertyChangedEventArgs(propertyName));
    }
}
