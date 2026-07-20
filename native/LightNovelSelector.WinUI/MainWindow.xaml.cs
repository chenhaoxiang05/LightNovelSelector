using System.Runtime.InteropServices;
using LightNovelSelector.WinUI.Helpers;
using Microsoft.UI;
using Microsoft.UI.Composition.SystemBackdrops;
using Microsoft.UI.Windowing;
using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Media;
using Windows.Graphics;
using Windows.UI.ViewManagement;
using WinRT.Interop;

namespace LightNovelSelector.WinUI;

public sealed partial class MainWindow : Window
{
    private readonly UISettings _uiSettings = new();
    private readonly AccessibilitySettings _accessibilitySettings = new();
    private readonly DispatcherTimer _appearanceFallbackTimer = new();
    private WindowMaterial _requestedMaterial;
    private WindowMaterial? _effectiveMaterial;
    private bool _windowChromeReady;
    private bool _advancedEffectsEventSubscribed;
    private bool _highContrastEventSubscribed;

    public event EventHandler? MaterialStateChanged;

    public WindowMaterialState MaterialState { get; private set; }

    public MainWindow()
    {
        InitializeComponent();
        WindowRoot.ActualThemeChanged += OnActualThemeChanged;

        ApplyTheme(AppearancePreferences.LoadTheme());
        ExtendsContentIntoTitleBar = true;
        SetTitleBar(AppTitleBar);
        _windowChromeReady = true;
        AppWindow.SetIcon("Assets/AppIcon.ico");
        ConfigureTitleBar();
        SizeAndCenterWindow();
        _requestedMaterial = AppearancePreferences.LoadMaterial();
        ApplyEffectiveMaterial(notify: false);
        AppWindow.Closing += OnAppWindowClosing;
        SubscribeToSystemAppearance();
        _appearanceFallbackTimer.Interval = TimeSpan.FromSeconds(2);
        _appearanceFallbackTimer.Tick += OnAppearanceFallbackTimerTick;
        _appearanceFallbackTimer.Start();
        Closed += OnClosed;
        RootFrame.Navigate(typeof(MainPage));
    }

    public void ApplyTheme(string theme)
    {
        WindowRoot.RequestedTheme = AppearancePreferences.ToElementTheme(theme);
        if (_windowChromeReady)
        {
            ConfigureTitleBar();
            _effectiveMaterial = null;
            ApplyEffectiveMaterial(notify: false);
        }
    }

    public void ApplyMaterial(WindowMaterial material)
    {
        _requestedMaterial = material;
        ApplyEffectiveMaterial(notify: true);
    }

    private void ApplyEffectiveMaterial(bool notify)
    {
        var highContrast = GetHighContrast();
        var advancedEffectsEnabled = GetAdvancedEffectsEnabled();
        var effective = highContrast || !advancedEffectsEnabled
            ? WindowMaterial.Solid
            : _requestedMaterial;

        if (_effectiveMaterial != effective)
        {
            SystemBackdrop = effective switch
            {
                WindowMaterial.Acrylic => new DesktopAcrylicBackdrop(),
                WindowMaterial.Mica => new MicaBackdrop { Kind = MicaKind.Base },
                _ => null,
            };
            SolidBackdropLayer.Visibility = effective == WindowMaterial.Solid
                ? Visibility.Visible
                : Visibility.Collapsed;
            _effectiveMaterial = effective;
        }

        MaterialState = new WindowMaterialState(
            _requestedMaterial,
            effective,
            advancedEffectsEnabled,
            highContrast
        );
        if (notify)
        {
            MaterialStateChanged?.Invoke(this, EventArgs.Empty);
        }
    }

    private bool GetAdvancedEffectsEnabled()
    {
        try
        {
            return _uiSettings.AdvancedEffectsEnabled;
        }
        catch
        {
            return false;
        }
    }

    private bool GetHighContrast()
    {
        try
        {
            return _accessibilitySettings.HighContrast;
        }
        catch
        {
            return false;
        }
    }

    private void OnSystemAppearanceChanged(object sender, object args)
    {
        DispatcherQueue.TryEnqueue(() => ApplyEffectiveMaterial(notify: true));
    }

    private void SubscribeToSystemAppearance()
    {
        try
        {
            _uiSettings.AdvancedEffectsEnabledChanged += OnSystemAppearanceChanged;
            _advancedEffectsEventSubscribed = true;
        }
        catch
        {
        }

        try
        {
            _accessibilitySettings.HighContrastChanged += OnSystemAppearanceChanged;
            _highContrastEventSubscribed = true;
        }
        catch
        {
        }
    }

    private void OnAppearanceFallbackTimerTick(object? sender, object e)
    {
        var advancedEffectsEnabled = GetAdvancedEffectsEnabled();
        var highContrast = GetHighContrast();
        if (
            MaterialState.AdvancedEffectsEnabled != advancedEffectsEnabled
            || MaterialState.HighContrast != highContrast
        )
        {
            ApplyEffectiveMaterial(notify: true);
        }
    }

    private void OnActualThemeChanged(FrameworkElement sender, object args)
    {
        if (!_windowChromeReady)
        {
            return;
        }
        ConfigureTitleBar();
        _effectiveMaterial = null;
        ApplyEffectiveMaterial(notify: false);
    }

    private void OnClosed(object sender, WindowEventArgs args)
    {
        WindowRoot.ActualThemeChanged -= OnActualThemeChanged;
        _appearanceFallbackTimer.Stop();
        _appearanceFallbackTimer.Tick -= OnAppearanceFallbackTimerTick;
        if (_advancedEffectsEventSubscribed)
        {
            _uiSettings.AdvancedEffectsEnabledChanged -= OnSystemAppearanceChanged;
        }
        if (_highContrastEventSubscribed)
        {
            _accessibilitySettings.HighContrastChanged -= OnSystemAppearanceChanged;
        }
    }

    private void ConfigureTitleBar()
    {
        if (!AppWindowTitleBar.IsCustomizationSupported())
        {
            return;
        }
        AppWindow.TitleBar.ButtonBackgroundColor = Colors.Transparent;
        AppWindow.TitleBar.ButtonInactiveBackgroundColor = Colors.Transparent;
        var foreground = WindowRoot.ActualTheme == ElementTheme.Dark ? Colors.White : Colors.Black;
        AppWindow.TitleBar.ButtonForegroundColor = foreground;
        AppWindow.TitleBar.ButtonInactiveForegroundColor = ColorHelper.FromArgb(
            150,
            foreground.R,
            foreground.G,
            foreground.B
        );
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
