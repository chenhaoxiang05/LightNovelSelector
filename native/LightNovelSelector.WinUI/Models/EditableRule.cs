namespace LightNovelSelector.WinUI.Models;

public sealed class EditableRule
{
    public EditableRule()
    {
    }

    public EditableRule(string pattern, string series)
    {
        Pattern = pattern;
        Series = series;
    }

    public string Pattern { get; set; } = string.Empty;
    public string Series { get; set; } = string.Empty;
}
