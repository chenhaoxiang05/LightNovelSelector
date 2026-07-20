using System.Numerics;
using System.Runtime.CompilerServices;
using LightNovelSelector.WinUI.Appearance;
using Microsoft.UI.Composition;
using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Hosting;
using Microsoft.UI.Xaml.Input;
using Windows.UI.ViewManagement;

namespace LightNovelSelector.WinUI.Helpers;

public static class Motion
{
    private static readonly ConditionalWeakTable<FrameworkElement, object> PressTargets = new();

    public static bool ReducedMotion
    {
        get
        {
            var userPreference = AppearancePreferences.LoadReducedMotion();
            try
            {
                return userPreference || !new UISettings().AnimationsEnabled;
            }
            catch
            {
                return userPreference;
            }
        }
        set => AppearancePreferences.TrySaveReducedMotion(value);
    }

    public static bool TrySetReducedMotion(bool value) =>
        AppearancePreferences.TrySaveReducedMotion(value);

    public static void AttachPressFeedback(FrameworkElement element)
    {
        if (PressTargets.TryGetValue(element, out _))
        {
            return;
        }
        PressTargets.Add(element, new object());

        element.SizeChanged += (_, _) => CenterScale(element);
        element.AddHandler(
            UIElement.PointerPressedEvent,
            new PointerEventHandler((_, _) => AnimateScale(element, 0.975f, 100)),
            handledEventsToo: true
        );
        element.PointerReleased += (_, _) => AnimateScale(element, 1.0f, 160);
        element.PointerCanceled += (_, _) => AnimateScale(element, 1.0f, 160);
        element.PointerCaptureLost += (_, _) => AnimateScale(element, 1.0f, 160);
    }

    public static void Enter(UIElement element, int delayMilliseconds = 0)
    {
        var visual = ElementCompositionPreview.GetElementVisual(element);
        ElementCompositionPreview.SetIsTranslationEnabled(element, true);
        if (ReducedMotion)
        {
            visual.StopAnimation("Translation");
            element.Translation = Vector3.Zero;
            visual.Opacity = 1;
            return;
        }

        var compositor = visual.Compositor;
        var easing = EaseOut(compositor);

        visual.Opacity = 1;
        var opacity = compositor.CreateScalarKeyFrameAnimation();
        opacity.InsertKeyFrame(0, 0);
        opacity.InsertKeyFrame(1, 1, easing);
        opacity.Duration = TimeSpan.FromMilliseconds(180);
        opacity.DelayTime = TimeSpan.FromMilliseconds(delayMilliseconds);

        var translation = compositor.CreateVector3KeyFrameAnimation();
        translation.InsertKeyFrame(0, new Vector3(0, 8, 0));
        translation.InsertKeyFrame(1, Vector3.Zero, easing);
        translation.Duration = TimeSpan.FromMilliseconds(220);
        translation.DelayTime = TimeSpan.FromMilliseconds(delayMilliseconds);

        visual.StartAnimation(nameof(Visual.Opacity), opacity);
        visual.StartAnimation("Translation", translation);
    }

    public static void RevealPage(UIElement element)
    {
        var visual = ElementCompositionPreview.GetElementVisual(element);
        ElementCompositionPreview.SetIsTranslationEnabled(element, true);
        if (ReducedMotion)
        {
            visual.StopAnimation("Translation");
            element.Translation = Vector3.Zero;
            visual.Opacity = 1;
            return;
        }

        var compositor = visual.Compositor;
        var easing = EaseOut(compositor);
        var opacity = compositor.CreateScalarKeyFrameAnimation();
        opacity.InsertKeyFrame(0, 0.72f);
        opacity.InsertKeyFrame(1, 1, easing);
        opacity.Duration = TimeSpan.FromMilliseconds(130);

        var translation = compositor.CreateVector3KeyFrameAnimation();
        translation.InsertKeyFrame(0, new Vector3(0, 4, 0));
        translation.InsertKeyFrame(1, Vector3.Zero, easing);
        translation.Duration = TimeSpan.FromMilliseconds(160);

        visual.StartAnimation(nameof(Visual.Opacity), opacity);
        visual.StartAnimation("Translation", translation);
    }

    public static void SetEmphasis(UIElement element, bool emphasized)
    {
        AnimateScale(element, emphasized ? 1.04f : 1.0f, emphasized ? 100 : 120);
    }

    public static void ShowTransient(UIElement element, bool show)
    {
        var visual = ElementCompositionPreview.GetElementVisual(element);
        ElementCompositionPreview.SetIsTranslationEnabled(element, true);
        if (ReducedMotion)
        {
            visual.StopAnimation("Translation");
            element.Translation = Vector3.Zero;
            var fade = visual.Compositor.CreateScalarKeyFrameAnimation();
            fade.InsertKeyFrame(1, show ? 1 : 0, EaseOut(visual.Compositor));
            fade.Duration = TimeSpan.FromMilliseconds(90);
            fade.StopBehavior = AnimationStopBehavior.SetToFinalValue;
            visual.StartAnimation(nameof(Visual.Opacity), fade);
            return;
        }

        var compositor = visual.Compositor;
        var easing = EaseOut(compositor);
        visual.Opacity = show ? 1 : 0;
        var opacity = compositor.CreateScalarKeyFrameAnimation();
        opacity.InsertKeyFrame(0, show ? 0 : 1);
        opacity.InsertKeyFrame(1, show ? 1 : 0, easing);
        opacity.Duration = TimeSpan.FromMilliseconds(show ? 180 : 140);

        var translation = compositor.CreateVector3KeyFrameAnimation();
        translation.InsertKeyFrame(0, show ? new Vector3(0, -8, 0) : Vector3.Zero);
        translation.InsertKeyFrame(1, show ? Vector3.Zero : new Vector3(0, -8, 0), easing);
        translation.Duration = TimeSpan.FromMilliseconds(show ? 220 : 140);

        visual.StartAnimation(nameof(Visual.Opacity), opacity);
        visual.StartAnimation("Translation", translation);
    }

    private static void AnimateScale(UIElement element, float scale, int milliseconds)
    {
        var visual = ElementCompositionPreview.GetElementVisual(element);
        CenterScale(element);
        if (ReducedMotion)
        {
            visual.StopAnimation(nameof(Visual.Scale));
            visual.Scale = Vector3.One;
            return;
        }

        var animation = visual.Compositor.CreateVector3KeyFrameAnimation();
        animation.InsertKeyFrame(1, new Vector3(scale), EaseOut(visual.Compositor));
        animation.Duration = TimeSpan.FromMilliseconds(milliseconds);
        visual.StartAnimation(nameof(Visual.Scale), animation);
    }

    private static void CenterScale(UIElement element)
    {
        var visual = ElementCompositionPreview.GetElementVisual(element);
        visual.CenterPoint = new Vector3((float)element.RenderSize.Width / 2, (float)element.RenderSize.Height / 2, 0);
    }

    private static CubicBezierEasingFunction EaseOut(Compositor compositor) =>
        compositor.CreateCubicBezierEasingFunction(new Vector2(0.22f, 1), new Vector2(0.36f, 1));
}
