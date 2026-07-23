using System.Text;
using System.Text.Json;
using Microsoft.UI.Xaml;
using Windows.Storage;

namespace LightNovelSelector.WinUI.Appearance;

public enum WindowMaterial
{
    Acrylic,
    Mica,
    Solid,
}

public readonly record struct WindowMaterialState(
    WindowMaterial Requested,
    WindowMaterial Effective,
    bool AdvancedEffectsEnabled,
    bool HighContrast
)
{
    public bool IsFallback => Requested != Effective;

    public string StatusText => HighContrast
        ? "高对比度已启用，当前使用实色回退。"
        : !AdvancedEffectsEnabled && Requested != WindowMaterial.Solid
            ? "Windows 已关闭透明效果，当前使用实色回退。"
            : Effective switch
            {
                WindowMaterial.Acrylic => "透明亚克力正在运行。",
                WindowMaterial.Mica => "云母材质正在运行。",
                _ => "实色模式正在运行。",
            };
}

public static class AppearancePreferences
{
    private const int MaxFallbackFileBytes = 64 * 1024;
    private const string TestThemeEnvironmentVariable = "LN_SELECTOR_WINUI_TEST_THEME";
    private const string TestMaterialEnvironmentVariable = "LN_SELECTOR_WINUI_TEST_MATERIAL";
    private static readonly object FallbackFileLock = new();
    private static readonly string FallbackFilePath = Path.Combine(
        Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData),
        "LightNovelSelector",
        "appearance.json"
    );

    public const string ThemeSettingKey = "Theme";
    public const string WindowMaterialSettingKey = "WindowMaterial";
    public const string ReducedMotionSettingKey = "ReducedMotion";

    public static string LoadTheme()
    {
        var testValue = Environment.GetEnvironmentVariable(TestThemeEnvironmentVariable);
        if (testValue is "light" or "dark" or "system")
        {
            return testValue;
        }

        var value = ReadString(ThemeSettingKey);
        return value is "light" or "dark" ? value : "system";
    }

    public static WindowMaterial LoadMaterial()
    {
        var testValue = Environment.GetEnvironmentVariable(TestMaterialEnvironmentVariable);
        return (testValue ?? ReadString(WindowMaterialSettingKey)) switch
        {
            "mica" => WindowMaterial.Mica,
            "solid" => WindowMaterial.Solid,
            _ => WindowMaterial.Acrylic,
        };
    }

    public static bool TrySaveTheme(string theme) =>
        TryWrite(ThemeSettingKey, theme is "light" or "dark" ? theme : "system");

    public static bool TrySaveMaterial(WindowMaterial material) =>
        TryWrite(WindowMaterialSettingKey, ToSettingValue(material));

    public static bool LoadReducedMotion()
    {
        try
        {
            if (ApplicationData.Current.LocalSettings.Values[ReducedMotionSettingKey] is bool value)
            {
                return value;
            }
        }
        catch
        {
        }
        return bool.TryParse(ReadFallbackValue(ReducedMotionSettingKey), out var fallback) && fallback;
    }

    public static bool TrySaveReducedMotion(bool value)
    {
        var localSettingsSaved = false;
        try
        {
            ApplicationData.Current.LocalSettings.Values[ReducedMotionSettingKey] = value;
            localSettingsSaved = true;
        }
        catch
        {
        }
        return TryWriteFallbackValue(ReducedMotionSettingKey, value.ToString()) || localSettingsSaved;
    }

    public static ElementTheme ToElementTheme(string theme) => theme switch
    {
        "light" => ElementTheme.Light,
        "dark" => ElementTheme.Dark,
        _ => ElementTheme.Default,
    };

    public static string ToSettingValue(WindowMaterial material) => material switch
    {
        WindowMaterial.Mica => "mica",
        WindowMaterial.Solid => "solid",
        _ => "acrylic",
    };

    public static WindowMaterial FromSettingValue(string? value) => value switch
    {
        "mica" => WindowMaterial.Mica,
        "solid" => WindowMaterial.Solid,
        _ => WindowMaterial.Acrylic,
    };

    private static string? ReadString(string key)
    {
        try
        {
            if (ApplicationData.Current.LocalSettings.Values[key] is string value)
            {
                return value;
            }
        }
        catch
        {
        }
        return ReadFallbackValue(key);
    }

    private static bool TryWrite(string key, string value)
    {
        var localSettingsSaved = false;
        try
        {
            ApplicationData.Current.LocalSettings.Values[key] = value;
            localSettingsSaved = true;
        }
        catch
        {
        }
        return TryWriteFallbackValue(key, value) || localSettingsSaved;
    }

    private static string? ReadFallbackValue(string key)
    {
        lock (FallbackFileLock)
        {
            var values = ReadFallbackValues();
            return values.TryGetValue(key, out var value) ? value : null;
        }
    }

    private static bool TryWriteFallbackValue(string key, string value)
    {
        lock (FallbackFileLock)
        {
            var temporaryPath = $"{FallbackFilePath}.tmp";
            try
            {
                var values = ReadFallbackValues();
                values[key] = value;
                Directory.CreateDirectory(Path.GetDirectoryName(FallbackFilePath)!);
                File.WriteAllText(
                    temporaryPath,
                    JsonSerializer.Serialize(values, new JsonSerializerOptions { WriteIndented = true }),
                    new UTF8Encoding(encoderShouldEmitUTF8Identifier: false)
                );
                File.Move(temporaryPath, FallbackFilePath, overwrite: true);
                return true;
            }
            catch
            {
                try
                {
                    File.Delete(temporaryPath);
                }
                catch
                {
                }
                return false;
            }
        }
    }

    private static Dictionary<string, string> ReadFallbackValues()
    {
        try
        {
            if (!File.Exists(FallbackFilePath))
            {
                return [];
            }
            using var stream = new FileStream(
                FallbackFilePath,
                FileMode.Open,
                FileAccess.Read,
                FileShare.ReadWrite
            );
            if (stream.Length > MaxFallbackFileBytes)
            {
                return [];
            }
            using var reader = new StreamReader(
                stream,
                Encoding.UTF8,
                detectEncodingFromByteOrderMarks: true
            );
            return JsonSerializer.Deserialize<Dictionary<string, string>>(reader.ReadToEnd()) ?? [];
        }
        catch
        {
            return [];
        }
    }
}
