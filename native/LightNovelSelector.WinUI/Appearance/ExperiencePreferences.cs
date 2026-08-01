namespace LightNovelSelector.WinUI.Appearance;

public static class ExperiencePreferences
{
    private const string OnboardingVersionSettingKey = "OnboardingVersion";

    public static int LoadOnboardingVersion() =>
        int.TryParse(
            AppearancePreferences.ReadPreference(OnboardingVersionSettingKey),
            out var version
        ) && version >= 0
            ? version
            : 0;

    public static bool TrySaveOnboardingVersion(int version) =>
        AppearancePreferences.TryWritePreference(
            OnboardingVersionSettingKey,
            Math.Max(0, version).ToString(System.Globalization.CultureInfo.InvariantCulture)
        );
}
