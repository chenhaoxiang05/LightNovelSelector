using LightNovelSelector.WinUI.Helpers;
using LightNovelSelector.WinUI.Services;
using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Controls;
using Microsoft.UI.Xaml.Media;
using Windows.ApplicationModel.DataTransfer;
using Windows.Storage;
using Windows.Storage.Pickers;
using Windows.System;
using WinRT.Interop;

namespace LightNovelSelector.WinUI;

public sealed partial class MainPage
{
    private async void OnChooseFolderClick(object sender, RoutedEventArgs e)
    {
        try
        {
            var picker = new FolderPicker { SuggestedStartLocation = PickerLocationId.DocumentsLibrary };
            picker.FileTypeFilter.Add("*");
            var window = App.MainWindow ?? throw new InvalidOperationException("主窗口尚未准备好。");
            InitializeWithWindow.Initialize(picker, WindowNative.GetWindowHandle(window));
            var folder = await picker.PickSingleFolderAsync();
            if (folder is not null)
            {
                await SelectFolderAsync(folder.Path);
            }
        }
        catch (Exception exc)
        {
            ShowToast(exc.Message, ToastKind.Error);
        }
    }

    private void OnFolderDragEnter(object sender, DragEventArgs e)
    {
        var acceptsStorageItems = e.DataView.Contains(StandardDataFormats.StorageItems);
        SetFolderDragState(acceptsStorageItems);
        e.Handled = acceptsStorageItems;
    }

    private void OnFolderDragLeave(object sender, DragEventArgs e) => SetFolderDragState(false);

    private void OnFolderDragOver(object sender, DragEventArgs e)
    {
        if (!e.DataView.Contains(StandardDataFormats.StorageItems))
        {
            SetFolderDragState(false);
            return;
        }
        SetFolderDragState(true);
        e.AcceptedOperation = DataPackageOperation.Link;
        e.DragUIOverride.Caption = "使用此目录";
        e.DragUIOverride.IsContentVisible = true;
        e.Handled = true;
    }

    private async void OnFolderDrop(object sender, DragEventArgs e)
    {
        SetFolderDragState(false);
        try
        {
            var items = await e.DataView.GetStorageItemsAsync();
            var folders = items.OfType<StorageFolder>().ToList();
            string? path = null;
            if (folders.Count == 1 && items.Count == 1)
            {
                path = folders[0].Path;
            }
            else if (folders.Count == 0 && items.OfType<StorageFile>().Any())
            {
                var parents = items
                    .OfType<StorageFile>()
                    .Select(file => Path.GetDirectoryName(file.Path))
                    .Where(parent => !string.IsNullOrWhiteSpace(parent))
                    .Distinct(StringComparer.OrdinalIgnoreCase)
                    .ToList();
                if (parents.Count == 1)
                {
                    path = parents[0];
                }
            }

            if (string.IsNullOrWhiteSpace(path))
            {
                ShowToast("请拖入一个目录，或拖入同一目录中的一批小说文件。", ToastKind.Warning);
                return;
            }
            await SelectFolderAsync(path);
        }
        catch (Exception exc)
        {
            ShowToast(exc.Message, ToastKind.Error);
        }
        finally
        {
            SetFolderDragState(false);
        }
    }

    private void SetFolderDragState(bool active)
    {
        if (FolderCard.BackgroundTransition is BrushTransition transition)
        {
            transition.Duration = TimeSpan.FromMilliseconds(active ? 100 : 120);
        }
        FolderCard.Background = ResourceBrush(active ? "CardHoverBrush" : "ElevatedCardBackgroundBrush");
        FolderCard.BorderBrush = ResourceBrush(active ? "AppAccentBrush" : "CardBorderBrush");
        FolderCard.BorderThickness = new Thickness(active ? 2 : 1);
        Motion.SetEmphasis(FolderIconSurface, active);
    }

    private async Task SelectFolderAsync(string path)
    {
        var snapshot = await _sidecar.SetFolderAsync(path);
        ApplySnapshot(snapshot);
        ShowToast("目录已选择，可以开始扫描。", ToastKind.Success);
    }

    private async void OnScanClick(object sender, RoutedEventArgs e)
    {
        if (string.IsNullOrWhiteSpace(_snapshot.Folder))
        {
            ShowToast("请先选择轻小说目录。", ToastKind.Warning);
            return;
        }

        try
        {
            try
            {
                await SaveCurrentSettingsAsync(showResult: false);
            }
            catch (SidecarRemoteException exc)
            {
                ShowToast($"新设置未采用，将使用上次保存值：{exc.Message}", ToastKind.Warning, 5000);
            }
            var snapshot = await _sidecar.StartScanAsync();
            ApplySnapshot(snapshot);
            ShowToast("扫描已开始，原文件不会在预览阶段发生变化。", ToastKind.Info);
        }
        catch (Exception exc)
        {
            ShowToast(exc.Message, ToastKind.Error);
        }
    }

    private async void OnCancelClick(object sender, RoutedEventArgs e)
    {
        try
        {
            var result = await _sidecar.CancelOperationAsync();
            ApplySnapshot(result.State);
            if (result.Cancelled)
            {
                ShowToast("正在安全停止扫描。", ToastKind.Info);
            }
        }
        catch (Exception exc)
        {
            ShowToast(exc.Message, ToastKind.Error);
        }
    }

    private async void OnApplyClick(object sender, RoutedEventArgs e)
    {
        var movable = Plans.Count(plan => plan.WillMove);
        if (movable == 0)
        {
            ShowToast("当前预览没有可移动的文件。", ToastKind.Warning);
            return;
        }

        var dialog = new ContentDialog
        {
            XamlRoot = XamlRoot,
            Title = "确认整理这些文件？",
            Content = $"将移动 {movable} 个文件。分类报告会保存在所选目录中，请保留原位置，以便之后安全撤销。",
            PrimaryButtonText = "开始整理",
            CloseButtonText = "返回检查",
            DefaultButton = ContentDialogButton.Primary,
        };
        if (await dialog.ShowAsync() != ContentDialogResult.Primary)
        {
            return;
        }

        try
        {
            var snapshot = await _sidecar.StartApplyAsync();
            ApplySnapshot(snapshot);
            ShowToast("正在整理文件，请保持窗口开启。", ToastKind.Info);
        }
        catch (Exception exc)
        {
            ShowToast(exc.Message, ToastKind.Error);
        }
    }

    private async void OnUndoClick(object sender, RoutedEventArgs e)
    {
        var dialog = new ContentDialog
        {
            XamlRoot = XamlRoot,
            Title = "撤销上次分类？",
            Content = "软件会先校验最近报告的目录与路径边界，再恢复已移动文件；原位置已有同名文件时会安全跳过。",
            PrimaryButtonText = "开始撤销",
            CloseButtonText = "取消",
            DefaultButton = ContentDialogButton.Close,
        };
        if (await dialog.ShowAsync() != ContentDialogResult.Primary)
        {
            return;
        }

        try
        {
            var snapshot = await _sidecar.StartUndoAsync();
            ApplySnapshot(snapshot);
            ShowToast("正在按报告恢复文件，请保持窗口开启。", ToastKind.Info);
        }
        catch (Exception exc)
        {
            ShowToast(exc.Message, ToastKind.Error);
        }
    }

    private async void OnOpenFolderClick(object sender, RoutedEventArgs e)
    {
        if (!string.IsNullOrWhiteSpace(_snapshot.Folder))
        {
            await OpenInExplorerAsync(_snapshot.Folder);
        }
    }

    private async Task OpenInExplorerAsync(string path, bool selectFile = false)
    {
        try
        {
            bool launched;
            if (selectFile)
            {
                var file = await StorageFile.GetFileFromPathAsync(path);
                var folder = await file.GetParentAsync();
                if (folder is null)
                {
                    throw new DirectoryNotFoundException("无法定位文件所在目录。");
                }
                var options = new FolderLauncherOptions();
                options.ItemsToSelect.Add(file);
                launched = await Launcher.LaunchFolderAsync(folder, options);
            }
            else
            {
                var folder = await StorageFolder.GetFolderFromPathAsync(path);
                launched = await Launcher.LaunchFolderAsync(folder);
            }

            if (!launched)
            {
                ShowToast("Windows 未能打开该位置。", ToastKind.Warning);
            }
        }
        catch (Exception exc)
        {
            ShowToast(exc.Message, ToastKind.Error);
        }
    }
}
