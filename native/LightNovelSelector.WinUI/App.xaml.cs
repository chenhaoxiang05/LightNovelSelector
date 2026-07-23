using Microsoft.UI.Dispatching;
using Microsoft.UI.Xaml;
using Microsoft.Windows.AppLifecycle;

namespace LightNovelSelector.WinUI;

public partial class App : Application
{
    private const string MainInstanceKey = "LightNovelSelector.Main";
    private AppInstance? _mainInstance;
    private DispatcherQueue? _dispatcherQueue;

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

    protected override async void OnLaunched(Microsoft.UI.Xaml.LaunchActivatedEventArgs args)
    {
        LaunchArguments = args.Arguments ?? string.Empty;
        if (!IsAutomatedSmokeTest)
        {
            var currentInstance = AppInstance.GetCurrent();
            _mainInstance = AppInstance.FindOrRegisterForKey(MainInstanceKey);
            if (!_mainInstance.IsCurrent)
            {
                try
                {
                    await _mainInstance.RedirectActivationToAsync(currentInstance.GetActivatedEventArgs());
                }
                catch (Exception)
                {
                    // Do not create a competing file-operation process when activation redirection races with shutdown.
                }
                finally
                {
                    Exit();
                }
                return;
            }

            _dispatcherQueue = DispatcherQueue.GetForCurrentThread();
            _mainInstance.Activated += OnInstanceActivated;
        }

        MainWindow = new MainWindow();
        MainWindow.Activate();
    }

    private void OnInstanceActivated(object? sender, AppActivationArguments args)
    {
        _dispatcherQueue?.TryEnqueue(() => MainWindow?.ActivateExistingInstance());
    }
}
