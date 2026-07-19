using System.Numerics;
using System.Runtime.CompilerServices;
using Microsoft.UI.Composition;
using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Hosting;
using Microsoft.UI.Xaml.Input;
using Windows.Storage;
using Windows.UI.ViewManagement;

namespace LightNovelSelector.WinUI.Helpers;

public static class Motion
{
    private const string ReducedMotionKey = "ReducedMotion";
    private static readonly ConditionalWeakTable<FrameworkElement, object> PressTargets = new();

    public static bool ReducedMotion
    {
        get
        {
            try
            {
                var localValue = ApplicationData.Current.LocalSettings.Values[ReducedMotionKey];
                return localValue is true || !new UISettings().AnimationsEnabled;
            }
            catch
            {
                return false;
            }
        }
        set
        {
            try
            {
                ApplicationData.Current.LocalSettings.Values[ReducedMotionKey] = value;
            }
            catch
            {
            }
        }
    }

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
            new PointerEventHandler((_, _) => AnimateScale(element, 0.975f, 110)),
            handledEventsToo: true
        );
        element.PointerReleased += (_, _) => AnimateScale(element, 1.0f, 180);
        element.PointerCanceled += (_, _) => AnimateScale(element, 1.0f, 180);
        element.PointerCaptureLost += (_, _) => AnimateScale(element, 1.0f, 180);
    }

    public static void Enter(UIElement element, int delayMilliseconds = 0)
    {
        var visual = ElementCompositionPreview.GetElementVisual(element);
        if (ReducedMotion)
        {
            visual.Opacity = 1;
            return;
        }

        ElementCompositionPreview.SetIsTranslationEnabled(element, true);
        var compositor = visual.Compositor;
        var easing = EaseOut(compositor);

        visual.Opacity = 1;
        var opacity = compositor.CreateScalarKeyFrameAnimation();
        opacity.InsertKeyFrame(0, 0);
        opacity.InsertKeyFrame(1, 1, easing);
        opacity.Duration = TimeSpan.FromMilliseconds(240);
        opacity.DelayTime = TimeSpan.FromMilliseconds(delayMilliseconds);

        var translation = compositor.CreateVector3KeyFrameAnimation();
        translation.InsertKeyFrame(0, new Vector3(0, 12, 0));
        translation.InsertKeyFrame(1, Vector3.Zero, easing);
        translation.Duration = TimeSpan.FromMilliseconds(280);
        translation.DelayTime = TimeSpan.FromMilliseconds(delayMilliseconds);

        visual.StartAnimation(nameof(Visual.Opacity), opacity);
        visual.StartAnimation("Translation", translation);
    }

    public static void ShowTransient(UIElement element, bool show)
    {
        var visual = ElementCompositionPreview.GetElementVisual(element);
        ElementCompositionPreview.SetIsTranslationEnabled(element, true);
        if (ReducedMotion)
        {
            visual.Opacity = show ? 1 : 0;
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

    public static void Pulse(UIElement element)
    {
        if (ReducedMotion)
        {
            return;
        }
        CenterScale(element);
        var visual = ElementCompositionPreview.GetElementVisual(element);
        var animation = visual.Compositor.CreateVector3KeyFrameAnimation();
        animation.InsertKeyFrame(0, new Vector3(0.96f));
        animation.InsertKeyFrame(1, Vector3.One, EaseOut(visual.Compositor));
        animation.Duration = TimeSpan.FromMilliseconds(220);
        visual.StartAnimation(nameof(Visual.Scale), animation);
    }

    private static void AnimateScale(UIElement element, float scale, int milliseconds)
    {
        var visual = ElementCompositionPreview.GetElementVisual(element);
        CenterScale(element);
        if (ReducedMotion)
        {
            visual.Scale = new Vector3(scale);
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
