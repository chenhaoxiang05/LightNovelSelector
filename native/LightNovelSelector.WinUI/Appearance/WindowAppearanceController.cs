using Microsoft.UI;
using Microsoft.UI.Composition.SystemBackdrops;
using Microsoft.UI.Dispatching;
using Microsoft.UI.Windowing;
using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Media;
using Windows.UI.ViewManagement;

namespace LightNovelSelector.WinUI.Appearance;

internal sealed class WindowAppearanceController : IDisposable
{
    private readonly Window _window;
    private readonly FrameworkElement _themeRoot;
    private readonly UIElement _solidBackdropLayer;
    private readonly UISettings _uiSettings = new();
    private readonly AccessibilitySettings _accessibilitySettings = new();
    private readonly DispatcherTimer _fallbackTimer = new();
    private WindowMaterial _requestedMaterial;
    private WindowMaterial? _effectiveMaterial;
    private bool _titleBarRefreshQueued;
    private bool _systemRefreshQueued;
    private bool _advancedEffectsEventSubscribed;
    private bool _highContrastEventSubscribed;
    private bool _disposed;

    public event EventHandler? StateChanged;

    public WindowMaterialState State { get; private set; }

    public WindowAppearanceController(
        Window window,
        FrameworkElement themeRoot,
        UIElement solidBackdropLayer,
        WindowMaterial initialMaterial
    )
    {
        _window = window;
        _themeRoot = themeRoot;
        _solidBackdropLayer = solidBackdropLayer;
        _requestedMaterial = initialMaterial;
        _themeRoot.ActualThemeChanged += OnActualThemeChanged;

        ConfigureTitleBar();
        ApplyEffectiveMaterial(notify: false);
        SubscribeToSystemAppearance();

        _fallbackTimer.Interval = TimeSpan.FromSeconds(2);
        _fallbackTimer.Tick += OnFallbackTimerTick;
        _fallbackTimer.Start();
    }

    public void ApplyTheme(string theme)
    {
        var requestedTheme = AppearancePreferences.ToElementTheme(theme);
        if (_themeRoot.RequestedTheme != requestedTheme)
        {
            _themeRoot.RequestedTheme = requestedTheme;
        }

        // SystemBackdrop follows the window theme itself. Replacing it from this callback
        // can re-enter Microsoft.UI.Xaml while theme resources are still resolving.
        QueueTitleBarRefresh();
    }

    public void ApplyMaterial(WindowMaterial material)
    {
        _requestedMaterial = material;
        ApplyEffectiveMaterial(notify: true);
    }

    public void Dispose()
    {
        if (_disposed)
        {
            return;
        }

        _disposed = true;
        _themeRoot.ActualThemeChanged -= OnActualThemeChanged;
        _fallbackTimer.Stop();
        _fallbackTimer.Tick -= OnFallbackTimerTick;
        if (_advancedEffectsEventSubscribed)
        {
            _uiSettings.AdvancedEffectsEnabledChanged -= OnSystemAppearanceChanged;
        }
        if (_highContrastEventSubscribed)
        {
            _accessibilitySettings.HighContrastChanged -= OnSystemAppearanceChanged;
        }
    }

    private void ApplyEffectiveMaterial(bool notify)
    {
        if (_disposed)
        {
            return;
        }

        var advancedEffectsEnabled = GetAdvancedEffectsEnabled();
        var highContrast = GetHighContrast();
        var effective = highContrast || !advancedEffectsEnabled
            ? WindowMaterial.Solid
            : _requestedMaterial;

        if (_effectiveMaterial != effective)
        {
            _window.SystemBackdrop = effective switch
            {
                WindowMaterial.Acrylic => new DesktopAcrylicBackdrop(),
                WindowMaterial.Mica => new MicaBackdrop { Kind = MicaKind.Base },
                _ => null,
            };
            _solidBackdropLayer.Visibility = effective == WindowMaterial.Solid
                ? Visibility.Visible
                : Visibility.Collapsed;
            _effectiveMaterial = effective;
        }

        var previousState = State;
        State = new WindowMaterialState(
            _requestedMaterial,
            effective,
            advancedEffectsEnabled,
            highContrast
        );
        if (notify && State != previousState)
        {
            StateChanged?.Invoke(this, EventArgs.Empty);
        }
    }

    private void OnActualThemeChanged(FrameworkElement sender, object args) =>
        QueueTitleBarRefresh();

    private void QueueTitleBarRefresh()
    {
        if (_disposed || _titleBarRefreshQueued)
        {
            return;
        }

        _titleBarRefreshQueued = true;
        if (
            !_themeRoot.DispatcherQueue.TryEnqueue(
                DispatcherQueuePriority.Low,
                () =>
                {
                    _titleBarRefreshQueued = false;
                    if (!_disposed)
                    {
                        ConfigureTitleBar();
                    }
                }
            )
        )
        {
            _titleBarRefreshQueued = false;
        }
    }

    private void OnSystemAppearanceChanged(object sender, object args) => QueueSystemRefresh();

    private void QueueSystemRefresh()
    {
        if (_disposed || _systemRefreshQueued)
        {
            return;
        }

        _systemRefreshQueued = true;
        if (
            !_themeRoot.DispatcherQueue.TryEnqueue(
                DispatcherQueuePriority.Low,
                () =>
                {
                    _systemRefreshQueued = false;
                    ApplyEffectiveMaterial(notify: true);
                }
            )
        )
        {
            _systemRefreshQueued = false;
        }
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

    private void OnFallbackTimerTick(object? sender, object e)
    {
        if (
            State.AdvancedEffectsEnabled != GetAdvancedEffectsEnabled()
            || State.HighContrast != GetHighContrast()
        )
        {
            ApplyEffectiveMaterial(notify: true);
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

    private void ConfigureTitleBar()
    {
        if (!AppWindowTitleBar.IsCustomizationSupported())
        {
            return;
        }

        _window.AppWindow.TitleBar.ButtonBackgroundColor = Colors.Transparent;
        _window.AppWindow.TitleBar.ButtonInactiveBackgroundColor = Colors.Transparent;
        var foreground = _themeRoot.ActualTheme == ElementTheme.Dark ? Colors.White : Colors.Black;
        _window.AppWindow.TitleBar.ButtonForegroundColor = foreground;
        _window.AppWindow.TitleBar.ButtonInactiveForegroundColor = ColorHelper.FromArgb(
            150,
            foreground.R,
            foreground.G,
            foreground.B
        );
        _window.AppWindow.TitleBar.ButtonHoverBackgroundColor = ColorHelper.FromArgb(18, 128, 128, 128);
        _window.AppWindow.TitleBar.ButtonPressedBackgroundColor = ColorHelper.FromArgb(30, 128, 128, 128);
    }
}
