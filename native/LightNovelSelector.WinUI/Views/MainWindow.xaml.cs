using System.Runtime.InteropServices;
using LightNovelSelector.WinUI.Appearance;
using Microsoft.UI.Windowing;
using Microsoft.UI.Xaml;
using Windows.Graphics;
using WinRT.Interop;

namespace LightNovelSelector.WinUI;

public sealed partial class MainWindow : Window
{
    private readonly WindowAppearanceController _appearance;

    public event EventHandler? ActualThemeChanged;

    public event EventHandler? MaterialStateChanged
    {
        add => _appearance.StateChanged += value;
        remove => _appearance.StateChanged -= value;
    }

    public WindowMaterialState MaterialState => _appearance.State;

    public ElementTheme ActualTheme => WindowRoot.ActualTheme;

    public MainWindow()
    {
        InitializeComponent();
        WindowRoot.RequestedTheme = AppearancePreferences.ToElementTheme(
            AppearancePreferences.LoadTheme()
        );
        ExtendsContentIntoTitleBar = true;
        SetTitleBar(AppTitleBar);
        AppWindow.SetIcon(Path.Combine(AppContext.BaseDirectory, "Assets", "AppIcon.ico"));
        SizeAndCenterWindow();
        _appearance = new WindowAppearanceController(
            this,
            WindowRoot,
            SolidBackdropLayer,
            AppearancePreferences.LoadMaterial()
        );
        WindowRoot.ActualThemeChanged += OnWindowRootActualThemeChanged;
        AppWindow.Closing += OnAppWindowClosing;
        Closed += OnClosed;
        RootFrame.Navigate(typeof(MainPage));
    }

    public void ApplyTheme(string theme) => _appearance.ApplyTheme(theme);

    public void ApplyMaterial(WindowMaterial material) => _appearance.ApplyMaterial(material);

    public void ActivateExistingInstance()
    {
        if (AppWindow.Presenter is OverlappedPresenter
            {
                State: OverlappedPresenterState.Minimized,
            } presenter)
        {
            presenter.Restore();
        }
        AppWindow.Show();
        Activate();
    }

    private void OnClosed(object sender, WindowEventArgs args)
    {
        WindowRoot.ActualThemeChanged -= OnWindowRootActualThemeChanged;
        _appearance.Dispose();
    }

    private void OnWindowRootActualThemeChanged(FrameworkElement sender, object args) =>
        ActualThemeChanged?.Invoke(this, EventArgs.Empty);

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
