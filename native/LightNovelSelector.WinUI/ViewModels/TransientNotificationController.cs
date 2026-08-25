namespace LightNovelSelector.WinUI.ViewModels;

public sealed class TransientNotificationController
{
    private long _revision;

    public long CurrentRevision => Volatile.Read(ref _revision);

    public long Begin() => Interlocked.Increment(ref _revision);

    public void Invalidate() => Interlocked.Increment(ref _revision);

    public bool IsCurrent(long revision) =>
        revision > 0 && revision == CurrentRevision;

    public static int HideSettleDelayMilliseconds(bool reducedMotion) =>
        reducedMotion ? 90 : 150;
}
