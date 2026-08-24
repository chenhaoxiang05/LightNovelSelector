namespace LightNovelSelector.WinUI.ViewModels;

public enum WindowCloseAction
{
    Allow,
    BlockCriticalOperation,
    BlockActiveDialog,
    ConfirmUnsavedSettings,
}

public static class WindowCloseGuardController
{
    public static WindowCloseAction Describe(
        bool confirmedClose,
        bool criticalOperation,
        bool activeDialog,
        bool unsavedSettings
    )
    {
        if (confirmedClose)
        {
            return WindowCloseAction.Allow;
        }
        if (criticalOperation)
        {
            return WindowCloseAction.BlockCriticalOperation;
        }
        if (activeDialog)
        {
            return WindowCloseAction.BlockActiveDialog;
        }
        return unsavedSettings
            ? WindowCloseAction.ConfirmUnsavedSettings
            : WindowCloseAction.Allow;
    }
}
