using LightNovelSelector.WinUI.ViewModels;
using Microsoft.VisualStudio.TestTools.UnitTesting;

namespace LightNovelSelector.WinUI.Tests;

[TestClass]
public sealed class FirstRunOnboardingControllerTests
{
    [TestMethod]
    public void FirstLaunchShowsCurrentOnboarding()
    {
        Assert.IsTrue(FirstRunOnboardingController.ShouldShow(0, isAutomatedRun: false));
    }

    [TestMethod]
    public void AcknowledgedVersionDoesNotRepeat()
    {
        Assert.IsFalse(
            FirstRunOnboardingController.ShouldShow(
                FirstRunOnboardingController.CurrentVersion,
                isAutomatedRun: false
            )
        );
    }

    [TestMethod]
    public void AutomatedRunsNeverShowOnboarding()
    {
        Assert.IsFalse(FirstRunOnboardingController.ShouldShow(0, isAutomatedRun: true));
    }
}
