namespace LightNovelSelector.WinUI.ViewModels;

public static class FocusCycleController
{
    public static int NextIndex(int currentIndex, int count, bool reverse)
    {
        if (count <= 0)
        {
            return -1;
        }

        if (currentIndex < 0 || currentIndex >= count)
        {
            return reverse ? count - 1 : 0;
        }

        var offset = reverse ? -1 : 1;
        return (currentIndex + offset + count) % count;
    }
}
