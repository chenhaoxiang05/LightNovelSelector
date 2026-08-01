namespace LightNovelSelector.WinUI.ViewModels;

public readonly record struct WindowLaunchSize(int Width, int Height);

public static class WindowLaunchSizeController
{
    public static bool TryParse(string? value, out WindowLaunchSize size)
    {
        size = default;
        if (string.IsNullOrWhiteSpace(value))
        {
            return false;
        }

        var dimensions = value.Split(['x', 'X'], StringSplitOptions.TrimEntries);
        if (
            dimensions.Length != 2
            || !int.TryParse(dimensions[0], out var width)
            || !int.TryParse(dimensions[1], out var height)
            || width is < 640 or > 3840
            || height is < 480 or > 2160
        )
        {
            return false;
        }

        size = new WindowLaunchSize(width, height);
        return true;
    }

    public static WindowLaunchSize ScaleForDpi(WindowLaunchSize size, uint dpi)
    {
        var scale = Math.Clamp(dpi / 96.0, 1.0, 3.0);
        return new WindowLaunchSize(
            (int)Math.Round(size.Width * scale),
            (int)Math.Round(size.Height * scale)
        );
    }
}
