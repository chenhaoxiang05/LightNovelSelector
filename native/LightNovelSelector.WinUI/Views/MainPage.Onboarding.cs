using LightNovelSelector.WinUI.Appearance;
using LightNovelSelector.WinUI.Helpers;
using LightNovelSelector.WinUI.ViewModels;
using Microsoft.UI.Xaml;

namespace LightNovelSelector.WinUI;

public sealed partial class MainPage
{
    private void InitializeOnboarding()
    {
        UsageTip.Target = ChooseFolderButton;
        UsageTip.ActionButtonClick += async (_, _) =>
        {
            UsageTip.IsOpen = false;
            await ChooseFolderAsync();
        };
        UsageTip.Closed += (_, _) =>
        {
            ExperiencePreferences.TrySaveOnboardingVersion(
                FirstRunOnboardingController.CurrentVersion
            );
        };
    }

    private async Task ShowFirstRunTipAsync()
    {
        var automatedRun = App.IsSmokeTest || App.IsAppearanceSmokeTest;
        if (
            !FirstRunOnboardingController.ShouldShow(
                ExperiencePreferences.LoadOnboardingVersion(),
                automatedRun
            )
        )
        {
            return;
        }

        if (!Motion.ReducedMotion)
        {
            await Task.Delay(260);
        }
        if (!_disposing)
        {
            OpenUsageTip();
        }
    }

    private void OnShowUsageTipClick(object sender, RoutedEventArgs e) => OpenUsageTip();

    private void OpenUsageTip()
    {
        UsageTip.Target = ChooseFolderButton;
        UsageTip.IsOpen = true;
    }
}
