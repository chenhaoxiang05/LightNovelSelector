using System.Runtime.InteropServices;
using Microsoft.UI;
using Microsoft.UI.Windowing;
using Microsoft.UI.Xaml;
using Windows.Graphics;
using WinRT.Interop;

namespace LightNovelSelector.WinUI;

public sealed partial class MainWindow : Window
{
    public MainWindow()
    {
        InitializeComponent();

        ExtendsContentIntoTitleBar = true;
        SetTitleBar(AppTitleBar);
        AppWindow.SetIcon("Assets/AppIcon.ico");
        ConfigureTitleBar();
        SizeAndCenterWindow();
        AppWindow.Closing += OnAppWindowClosing;
        RootFrame.Navigate(typeof(MainPage));
    }

    private void ConfigureTitleBar()
    {
        if (!AppWindowTitleBar.IsCustomizationSupported())
        {
            return;
        }
        AppWindow.TitleBar.ButtonBackgroundColor = Colors.Transparent;
        AppWindow.TitleBar.ButtonInactiveBackgroundColor = Colors.Transparent;
        AppWindow.TitleBar.ButtonHoverBackgroundColor = ColorHelper.FromArgb(18, 128, 128, 128);
        AppWindow.TitleBar.ButtonPressedBackgroundColor = ColorHelper.FromArgb(30, 128, 128, 128);
    }

    private void SizeAndCenterWindow()
    {
        var displayArea = DisplayArea.GetFromWindowId(AppWindow.Id, DisplayAreaFallback.Primary);
        if (displayArea is null)
        {
            AppWindow.Resize(new SizeInt32(1360, 840));
            return;
        }

        var workArea = displayArea.WorkArea;
        var dpi = GetDpiForWindow(WindowNative.GetWindowHandle(this));
        var scale = Math.Clamp(dpi / 96.0, 1.0, 3.0);
        var margin = (int)Math.Round(40 * scale);
        var width = Math.Max(800, Math.Min((int)Math.Round(1440 * scale), workArea.Width - margin));
        var height = Math.Max(600, Math.Min((int)Math.Round(900 * scale), workArea.Height - margin));
        var x = workArea.X + Math.Max(0, (workArea.Width - width) / 2);
        var y = workArea.Y + Math.Max(0, (workArea.Height - height) / 2);
        AppWindow.MoveAndResize(new RectInt32(x, y, width, height));
    }

    [DllImport("user32.dll")]
    private static extern uint GetDpiForWindow(nint windowHandle);

    private void OnAppWindowClosing(AppWindow sender, AppWindowClosingEventArgs args)
    {
        if (RootFrame.Content is not MainPage { IsCriticalOperation: true } page)
        {
            return;
        }
        args.Cancel = true;
        page.NotifyCriticalClose();
    }
}
