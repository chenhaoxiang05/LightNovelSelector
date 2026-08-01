namespace LightNovelSelector.WinUI.ViewModels;

public static class FirstRunOnboardingController
{
    public const int CurrentVersion = 1;

    public static bool ShouldShow(int acknowledgedVersion, bool isAutomatedRun) =>
        !isAutomatedRun && acknowledgedVersion < CurrentVersion;
}
