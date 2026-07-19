using Microsoft.UI.Xaml.Controls;
using LightNovelSelector.WinUI.Services;

// To learn more about WinUI, the WinUI project structure,
// and more about our project templates, see: http://aka.ms/winui-project-info.

namespace LightNovelSelector.WinUI;

/// <summary>
/// The main content page displayed inside the application window.
/// Add your UI logic, event handlers, and data binding here.
/// </summary>
public sealed partial class MainPage : Page
{
    private readonly PythonSidecarClient _sidecar = new();

    public MainPage()
    {
        InitializeComponent();
        Loaded += OnLoaded;
        Unloaded += OnUnloaded;
    }

    private async void OnLoaded(object sender, Microsoft.UI.Xaml.RoutedEventArgs e)
    {
        Loaded -= OnLoaded;
        try
        {
            var ping = await _sidecar.StartAsync();
            var snapshot = await _sidecar.BootstrapAsync();
            StartupProgress.IsActive = false;
            StartupTitle.Text = "原生界面已连接";
            StartupMessage.Text = $"{ping.AppName} {snapshot.App.Version} · Python 服务进程 {ping.ProcessId}";
        }
        catch (Exception exc)
        {
            StartupProgress.IsActive = false;
            StartupTitle.Text = "分类核心启动失败";
            StartupMessage.Text = exc.Message;
        }
    }

    private async void OnUnloaded(object sender, Microsoft.UI.Xaml.RoutedEventArgs e)
    {
        Unloaded -= OnUnloaded;
        await _sidecar.DisposeAsync();
    }
}
