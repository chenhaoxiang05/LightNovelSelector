using System.Collections.Concurrent;
using System.Diagnostics;
using System.Text;
using System.Text.Json;
using LightNovelSelector.WinUI.Models;

namespace LightNovelSelector.WinUI.Services;

public sealed class PythonSidecarClient : IAsyncDisposable
{
    public const int SupportedProtocolVersion = 1;

    private static readonly JsonSerializerOptions JsonOptions = new(JsonSerializerDefaults.Web)
    {
        PropertyNameCaseInsensitive = true,
        PropertyNamingPolicy = JsonNamingPolicy.SnakeCaseLower,
    };

    private readonly ConcurrentDictionary<long, TaskCompletionSource<JsonElement>> _pending = new();
    private readonly ConcurrentQueue<string> _diagnostics = new();
    private readonly SemaphoreSlim _lifecycleLock = new(1, 1);
    private readonly SemaphoreSlim _writeLock = new(1, 1);
    private Process? _process;
    private Task? _stdoutTask;
    private Task? _stderrTask;
    private long _requestId;
    private bool _disposed;

    public event Action<string>? DiagnosticReceived;

    public bool IsRunning => _process is { HasExited: false };

    public async Task<SidecarPing> StartAsync(CancellationToken cancellationToken = default)
    {
        await _lifecycleLock.WaitAsync(cancellationToken).ConfigureAwait(false);
        try
        {
            ObjectDisposedException.ThrowIf(_disposed, this);
            return await StartCoreAsync(cancellationToken).ConfigureAwait(false);
        }
        finally
        {
            _lifecycleLock.Release();
        }
    }

    public async Task<SidecarPing> RestartAsync(CancellationToken cancellationToken = default)
    {
        await _lifecycleLock.WaitAsync(cancellationToken).ConfigureAwait(false);
        try
        {
            ObjectDisposedException.ThrowIf(_disposed, this);
            FailPending(new SidecarUnavailableException("Python 服务正在重新启动。"));
            TerminateProcess();
            return await StartCoreAsync(cancellationToken).ConfigureAwait(false);
        }
        finally
        {
            _lifecycleLock.Release();
        }
    }

    private async Task<SidecarPing> StartCoreAsync(CancellationToken cancellationToken)
    {
        if (IsRunning)
        {
            return await CallAsync<SidecarPing>("ping", cancellationToken: cancellationToken).ConfigureAwait(false);
        }

        try
        {
            var launch = ResolveLaunchCommand();
            var startInfo = new ProcessStartInfo
            {
                FileName = launch.Executable,
                WorkingDirectory = launch.WorkingDirectory,
                RedirectStandardInput = true,
                RedirectStandardOutput = true,
                RedirectStandardError = true,
                StandardInputEncoding = new UTF8Encoding(false),
                StandardOutputEncoding = Encoding.UTF8,
                StandardErrorEncoding = Encoding.UTF8,
                UseShellExecute = false,
                CreateNoWindow = true,
            };
            foreach (var argument in launch.Arguments)
            {
                startInfo.ArgumentList.Add(argument);
            }
            startInfo.Environment["PYTHONUTF8"] = "1";
            startInfo.Environment["PYTHONUNBUFFERED"] = "1";

            var process = new Process { StartInfo = startInfo };
            _process = process;
            if (!process.Start())
            {
                throw new SidecarUnavailableException("Python 服务进程未能启动。");
            }

            _stdoutTask = ReadStandardOutputAsync(process);
            _stderrTask = ReadStandardErrorAsync(process);
            _ = MonitorExitAsync(process);

            var ping = await CallAsync<SidecarPing>(
                "ping",
                timeout: TimeSpan.FromSeconds(15),
                cancellationToken: cancellationToken
            ).ConfigureAwait(false);
            if (ping.ProtocolVersion != SupportedProtocolVersion)
            {
                throw new SidecarUnavailableException(
                    $"Python 服务协议版本不兼容：需要 {SupportedProtocolVersion}，实际为 {ping.ProtocolVersion}。"
                );
            }
            return ping;
        }
        catch (Exception exc)
        {
            AddDiagnostic($"启动 Python 服务失败：{exc.Message}");
            FailPending(new SidecarUnavailableException("Python 服务启动失败。" + DiagnosticSuffix()));
            TerminateProcess();
            if (exc is SidecarException or TimeoutException or OperationCanceledException)
            {
                throw;
            }
            throw new SidecarUnavailableException(
                "无法启动 Python 服务。请检查 Python 路径与执行权限，或重新构建便携包。"
            );
        }
    }

    public Task<AppSnapshot> BootstrapAsync(CancellationToken cancellationToken = default) =>
        CallAsync<AppSnapshot>("bootstrap", cancellationToken: cancellationToken);

    public Task<AppSnapshot> PollAsync(
        int logCursor,
        int plansRevision,
        CancellationToken cancellationToken = default
    ) => CallAsync<AppSnapshot>(
        "poll",
        new { logCursor, plansRevision },
        timeout: TimeSpan.FromSeconds(10),
        cancellationToken: cancellationToken
    );

    public Task<AppSnapshot> SetFolderAsync(string path, CancellationToken cancellationToken = default) =>
        CallAsync<AppSnapshot>("set_folder", new { path }, cancellationToken: cancellationToken);

    public Task<SaveSettingsResult> SaveSettingsAsync(
        AppSettings settings,
        CancellationToken cancellationToken = default
    ) => CallAsync<SaveSettingsResult>("save_settings", new { settings }, cancellationToken: cancellationToken);

    public Task<AppSnapshot> StartScanAsync(CancellationToken cancellationToken = default) =>
        CallAsync<AppSnapshot>("start_scan", cancellationToken: cancellationToken);

    public Task<CancelResult> CancelOperationAsync(CancellationToken cancellationToken = default) =>
        CallAsync<CancelResult>("cancel_operation", cancellationToken: cancellationToken);

    public Task<AppSnapshot> StartApplyAsync(CancellationToken cancellationToken = default) =>
        CallAsync<AppSnapshot>("start_apply", cancellationToken: cancellationToken);

    public Task<AppSnapshot> StartUndoAsync(CancellationToken cancellationToken = default) =>
        CallAsync<AppSnapshot>("start_undo", cancellationToken: cancellationToken);

    public Task<AppSnapshot> EditPlanAsync(
        int index,
        string seriesName,
        CancellationToken cancellationToken = default
    ) => CallAsync<AppSnapshot>("edit_plan", new { index, seriesName }, cancellationToken: cancellationToken);

    public Task<BookDetail> GetDetailAsync(int index, CancellationToken cancellationToken = default) =>
        CallAsync<BookDetail>(
            "get_detail",
            new { index },
            timeout: TimeSpan.FromSeconds(30),
            cancellationToken: cancellationToken
        );

    public Task<ReportSummary> GetReportAsync(CancellationToken cancellationToken = default) =>
        CallAsync<ReportSummary>("get_report", cancellationToken: cancellationToken);

    public async Task<T> CallAsync<T>(
        string method,
        object? parameters = null,
        TimeSpan? timeout = null,
        CancellationToken cancellationToken = default
    )
    {
        ObjectDisposedException.ThrowIf(_disposed, this);
        var process = _process;
        if (process is null || process.HasExited)
        {
            throw new SidecarUnavailableException("Python 服务尚未启动或已经退出。" + DiagnosticSuffix());
        }

        var requestId = Interlocked.Increment(ref _requestId);
        var completion = new TaskCompletionSource<JsonElement>(TaskCreationOptions.RunContinuationsAsynchronously);
        if (!_pending.TryAdd(requestId, completion))
        {
            throw new InvalidOperationException("请求编号发生冲突。");
        }

        try
        {
            var payload = JsonSerializer.Serialize(
                new { id = requestId, method, @params = parameters ?? new { } },
                JsonOptions
            );
            await _writeLock.WaitAsync(cancellationToken).ConfigureAwait(false);
            try
            {
                await process.StandardInput.WriteLineAsync(payload.AsMemory(), cancellationToken).ConfigureAwait(false);
                await process.StandardInput.FlushAsync(cancellationToken).ConfigureAwait(false);
            }
            finally
            {
                _writeLock.Release();
            }

            using var timeoutSource = CancellationTokenSource.CreateLinkedTokenSource(cancellationToken);
            timeoutSource.CancelAfter(timeout ?? TimeSpan.FromSeconds(20));
            JsonElement result;
            try
            {
                result = await completion.Task.WaitAsync(timeoutSource.Token).ConfigureAwait(false);
            }
            catch (OperationCanceledException) when (!cancellationToken.IsCancellationRequested)
            {
                throw new TimeoutException($"Python 服务调用超时：{method}");
            }

            return result.Deserialize<T>(JsonOptions)
                ?? throw new SidecarProtocolException($"Python 服务返回了空结果：{method}");
        }
        finally
        {
            _pending.TryRemove(requestId, out _);
        }
    }

    private async Task ReadStandardOutputAsync(Process process)
    {
        try
        {
            while (await process.StandardOutput.ReadLineAsync().ConfigureAwait(false) is { } line)
            {
                HandleResponse(line);
            }
        }
        catch (Exception exc) when (exc is IOException or ObjectDisposedException or InvalidOperationException)
        {
            AddDiagnostic($"读取 Python 服务输出失败：{exc.Message}");
        }
    }

    private void HandleResponse(string line)
    {
        long? responseId = null;
        try
        {
            using var document = JsonDocument.Parse(line);
            var root = document.RootElement;
            if (!root.TryGetProperty("id", out var idElement) || !idElement.TryGetInt64(out var id))
            {
                throw new SidecarProtocolException("响应缺少有效请求编号。");
            }
            responseId = id;
            if (!_pending.TryGetValue(id, out var completion))
            {
                return;
            }

            if (root.TryGetProperty("ok", out var okElement) && okElement.GetBoolean())
            {
                completion.TrySetResult(root.GetProperty("result").Clone());
                return;
            }

            var error = root.TryGetProperty("error", out var errorElement) ? errorElement : default;
            var errorType = error.ValueKind == JsonValueKind.Object && error.TryGetProperty("type", out var typeElement)
                ? typeElement.GetString()
                : null;
            var message = error.ValueKind == JsonValueKind.Object && error.TryGetProperty("message", out var messageElement)
                ? messageElement.GetString()
                : null;
            completion.TrySetException(
                new SidecarRemoteException(errorType ?? "RemoteError", message ?? "Python 服务返回未知错误。")
            );
        }
        catch (Exception exc) when (exc is JsonException or InvalidOperationException or SidecarProtocolException)
        {
            AddDiagnostic($"忽略无效的 Python 服务响应：{exc.Message}");
            if (responseId is long id && _pending.TryGetValue(id, out var completion))
            {
                completion.TrySetException(new SidecarProtocolException($"Python 服务响应格式无效：{exc.Message}"));
            }
        }
    }

    private async Task ReadStandardErrorAsync(Process process)
    {
        try
        {
            while (await process.StandardError.ReadLineAsync().ConfigureAwait(false) is { } line)
            {
                AddDiagnostic(line);
            }
        }
        catch (Exception exc) when (exc is IOException or ObjectDisposedException or InvalidOperationException)
        {
            AddDiagnostic($"读取 Python 服务诊断失败：{exc.Message}");
        }
    }

    private async Task MonitorExitAsync(Process process)
    {
        try
        {
            await process.WaitForExitAsync().ConfigureAwait(false);
        }
        catch (Exception exc) when (exc is InvalidOperationException or ObjectDisposedException)
        {
            return;
        }

        if (!_disposed && ReferenceEquals(_process, process))
        {
            var exception = new SidecarUnavailableException(
                $"Python 服务意外退出，退出码 {process.ExitCode}。" + DiagnosticSuffix()
            );
            FailPending(exception);
        }
    }

    private void FailPending(Exception exception)
    {
        foreach (var pending in _pending.Values)
        {
            pending.TrySetException(exception);
        }
    }

    private void AddDiagnostic(string message)
    {
        if (string.IsNullOrWhiteSpace(message))
        {
            return;
        }
        _diagnostics.Enqueue(message.Trim());
        while (_diagnostics.Count > 20)
        {
            _diagnostics.TryDequeue(out _);
        }
        DiagnosticReceived?.Invoke(message.Trim());
    }

    private string DiagnosticSuffix()
    {
        var recent = _diagnostics.ToArray();
        return recent.Length == 0 ? string.Empty : $" 最近诊断：{recent[^1]}";
    }

    private static LaunchCommand ResolveLaunchCommand()
    {
        var packagedSidecar = Path.Combine(AppContext.BaseDirectory, "LightNovelSelector.Sidecar.exe");
        if (File.Exists(packagedSidecar))
        {
            return new LaunchCommand(packagedSidecar, AppContext.BaseDirectory, []);
        }

        var root = FindRepositoryRoot()
            ?? throw new SidecarUnavailableException("未找到 Python 核心目录。请重新运行构建脚本。");
        var configuredPython = Environment.GetEnvironmentVariable("LN_SELECTOR_PYTHON");
        var candidates = new List<string?>
        {
            configuredPython,
            Path.Combine(root, ".venv-build", "Scripts", "python.exe"),
            Path.Combine(root, ".venv", "Scripts", "python.exe"),
        };
        var localPrograms = Path.Combine(
            Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData),
            "Programs",
            "Python"
        );
        for (var minor = 19; minor >= 10; minor--)
        {
            candidates.Add(Path.Combine(localPrograms, $"Python3{minor}", "python.exe"));
        }
        var python = candidates.FirstOrDefault(path => !string.IsNullOrWhiteSpace(path) && File.Exists(path));
        if (python is not null)
        {
            return new LaunchCommand(python, root, ["-u", "-m", "lightnovel_selector.sidecar"]);
        }

        var windowsDirectory = Directory.GetParent(Environment.SystemDirectory)?.FullName;
        var launcher = windowsDirectory is null ? null : Path.Combine(windowsDirectory, "py.exe");
        if (launcher is not null && File.Exists(launcher))
        {
            return new LaunchCommand(launcher, root, ["-3", "-u", "-m", "lightnovel_selector.sidecar"]);
        }
        throw new SidecarUnavailableException(
            "未找到可用的 Python。请设置 LN_SELECTOR_PYTHON，或运行项目环境安装脚本。"
        );
    }

    private static string? FindRepositoryRoot()
    {
        var directory = new DirectoryInfo(AppContext.BaseDirectory);
        for (var depth = 0; directory is not null && depth < 12; depth++, directory = directory.Parent)
        {
            if (File.Exists(Path.Combine(directory.FullName, "lightnovel_selector", "sidecar.py")))
            {
                return directory.FullName;
            }
        }
        return null;
    }

    private void TerminateProcess()
    {
        var process = Interlocked.Exchange(ref _process, null);
        if (process is null)
        {
            return;
        }
        try
        {
            if (!process.HasExited)
            {
                process.Kill(entireProcessTree: true);
                process.WaitForExit(3000);
            }
        }
        catch (InvalidOperationException)
        {
        }
        finally
        {
            process.Dispose();
        }
    }

    public async ValueTask DisposeAsync()
    {
        if (_disposed)
        {
            return;
        }
        await _lifecycleLock.WaitAsync().ConfigureAwait(false);
        try
        {
            if (_disposed)
            {
                return;
            }
            _disposed = true;

            var process = _process;
            if (process is { HasExited: false })
            {
                try
                {
                    var payload = JsonSerializer.Serialize(
                        new { id = Interlocked.Increment(ref _requestId), method = "shutdown", @params = new { } },
                        JsonOptions
                    );
                    await process.StandardInput.WriteLineAsync(payload).ConfigureAwait(false);
                    await process.StandardInput.FlushAsync().ConfigureAwait(false);
                    using var timeout = new CancellationTokenSource(TimeSpan.FromSeconds(2));
                    await process.WaitForExitAsync(timeout.Token).ConfigureAwait(false);
                }
                catch (Exception exc) when (exc is IOException or InvalidOperationException or OperationCanceledException)
                {
                    TerminateProcess();
                }
            }

            if (_stdoutTask is not null || _stderrTask is not null)
            {
                try
                {
                    await Task.WhenAll(_stdoutTask ?? Task.CompletedTask, _stderrTask ?? Task.CompletedTask)
                        .ConfigureAwait(false);
                }
                catch (Exception exc) when (exc is IOException or ObjectDisposedException or InvalidOperationException)
                {
                }
            }
            FailPending(new ObjectDisposedException(nameof(PythonSidecarClient)));
            TerminateProcess();
        }
        finally
        {
            _lifecycleLock.Release();
        }
    }

    private sealed record LaunchCommand(string Executable, string WorkingDirectory, IReadOnlyList<string> Arguments);
}

public class SidecarException(string message) : Exception(message);

public sealed class SidecarUnavailableException(string message) : SidecarException(message);

public sealed class SidecarProtocolException(string message) : SidecarException(message);

public sealed class SidecarRemoteException(string remoteType, string message) : SidecarException(message)
{
    public string RemoteType { get; } = remoteType;
}
