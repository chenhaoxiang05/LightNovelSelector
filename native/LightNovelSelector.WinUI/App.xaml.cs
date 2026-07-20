using Microsoft.UI.Xaml;

namespace LightNovelSelector.WinUI;

public partial class App : Application
{
    public static MainWindow? MainWindow { get; private set; }
    public static string LaunchArguments { get; private set; } = string.Empty;
    public static bool IsSmokeTest =>
        LaunchArguments.Split(' ', StringSplitOptions.RemoveEmptyEntries).Contains("--smoke-test")
        || Environment.GetCommandLineArgs().Contains("--smoke-test")
        || Environment.GetEnvironmentVariable("LN_SELECTOR_WINUI_SMOKE_TEST") == "1";
    public static bool IsAppearanceSmokeTest =>
        LaunchArguments.Split(' ', StringSplitOptions.RemoveEmptyEntries)
            .Contains("--appearance-smoke-test")
        || Environment.GetCommandLineArgs().Contains("--appearance-smoke-test")
        || Environment.GetEnvironmentVariable("LN_SELECTOR_WINUI_APPEARANCE_SMOKE_TEST") == "1";
    public static bool IsAutomatedSmokeTest => IsSmokeTest || IsAppearanceSmokeTest;

    public App()
    {
        InitializeComponent();
    }

    protected override void OnLaunched(Microsoft.UI.Xaml.LaunchActivatedEventArgs args)
    {
        LaunchArguments = args.Arguments ?? string.Empty;
        MainWindow = new MainWindow();
        MainWindow.Activate();
    }
}
