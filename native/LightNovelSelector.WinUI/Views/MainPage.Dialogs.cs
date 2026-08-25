using Microsoft.UI.Xaml.Controls;

namespace LightNovelSelector.WinUI;

public sealed partial class MainPage
{
    private bool _dialogOpen;
    private bool _closePromptActive;

    public bool HasUnsavedSettings => _settingsDirty;

    public bool IsDialogOpen => _dialogOpen || _closePromptActive;

    public void NotifyActiveDialogClose()
    {
        ShowToast("请先完成或取消当前确认对话框，再关闭窗口。", ToastKind.Warning, 4000);
    }

    public void RequestUnsavedSettingsClose()
    {
        if (_closePromptActive || _disposing)
        {
            return;
        }
        _ = ConfirmUnsavedSettingsCloseAsync();
    }

    private async Task<ContentDialogResult> ShowManagedDialogAsync(ContentDialog dialog)
    {
        if (_dialogOpen)
        {
            ShowToast("请先完成当前确认操作。", ToastKind.Warning, 3500);
            return ContentDialogResult.None;
        }

        _dialogOpen = true;
        try
        {
            return await dialog.ShowAsync();
        }
        finally
        {
            _dialogOpen = false;
        }
    }

    private async Task ConfirmUnsavedSettingsCloseAsync()
    {
        _closePromptActive = true;
        try
        {
            var dialog = new ContentDialog
            {
                XamlRoot = XamlRoot,
                Title = "保存设置后退出？",
                Content = "识别设置还有未保存的更改。你可以先写入磁盘，也可以放弃这些更改。",
                PrimaryButtonText = "保存并退出",
                SecondaryButtonText = "放弃更改",
                CloseButtonText = "继续编辑",
                DefaultButton = ContentDialogButton.Primary,
            };
            var choice = await ShowManagedDialogAsync(dialog);
            if (choice == ContentDialogResult.None)
            {
                return;
            }
            if (choice == ContentDialogResult.Secondary)
            {
                App.MainWindow?.CloseAfterConfirmation();
                return;
            }

            try
            {
                var result = await SaveCurrentSettingsAsync(showResult: false);
                if (!result.Saved)
                {
                    await NavigateToSettingsAsync();
                    ShowToast(
                        $"设置尚未写入磁盘：{result.Warning ?? "请检查设置目录权限后重试。"}",
                        ToastKind.Warning,
                        6000
                    );
                    return;
                }
            }
            catch (Exception exc)
            {
                await NavigateToSettingsAsync();
                ShowToast(exc.Message, ToastKind.Error, 6000);
                return;
            }

            App.MainWindow?.CloseAfterConfirmation();
        }
        catch (Exception exc)
        {
            ShowToast($"无法打开退出确认：{exc.Message}", ToastKind.Error, 6000);
        }
        finally
        {
            _closePromptActive = false;
        }
    }

    private async Task NavigateToSettingsAsync()
    {
        if (ShellNavigation.SettingsItem is NavigationViewItem settingsItem)
        {
            await SelectNavigationItemAsync(
                settingsItem,
                ShortcutFocusTarget.SettingsPrimary
            );
        }
    }
}
