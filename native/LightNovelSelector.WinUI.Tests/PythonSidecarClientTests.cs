using System.Diagnostics;
using LightNovelSelector.WinUI.Services;
using Microsoft.VisualStudio.TestTools.UnitTesting;

namespace LightNovelSelector.WinUI.Tests;

[TestClass]
[DoNotParallelize]
public sealed class PythonSidecarClientTests
{
    [TestMethod]
    [Timeout(30_000)]
    public async Task RestartAsyncRecoversAfterUnexpectedProcessExit()
    {
        var previousPython = Environment.GetEnvironmentVariable("LN_SELECTOR_PYTHON");
        var testPython = FindPythonExecutable();
        if (testPython is not null)
        {
            Environment.SetEnvironmentVariable("LN_SELECTOR_PYTHON", testPython);
        }
        try
        {
            await using var client = new PythonSidecarClient();
            var firstPing = await client.StartAsync();
            Assert.AreEqual(PythonSidecarClient.SupportedProtocolVersion, firstPing.ProtocolVersion);
            Assert.IsTrue(client.IsRunning);

            using (var process = Process.GetProcessById(firstPing.ProcessId))
            {
                process.Kill(entireProcessTree: true);
                await process.WaitForExitAsync();
            }

            await Assert.ThrowsExactlyAsync<SidecarUnavailableException>(
                async () => await client.PollAsync(0, -1)
            );

            var secondPing = await client.RestartAsync();
            Assert.AreEqual(PythonSidecarClient.SupportedProtocolVersion, secondPing.ProtocolVersion);
            Assert.AreNotEqual(firstPing.ProcessId, secondPing.ProcessId);
            Assert.IsTrue(client.IsRunning);
            Assert.IsNotNull(await client.BootstrapAsync());
        }
        finally
        {
            Environment.SetEnvironmentVariable("LN_SELECTOR_PYTHON", previousPython);
        }
    }

    private static string? FindPythonExecutable()
    {
        var configured = Environment.GetEnvironmentVariable("LN_SELECTOR_PYTHON");
        if (!string.IsNullOrWhiteSpace(configured) && File.Exists(configured))
        {
            return configured;
        }

        var pythonLocation = Environment.GetEnvironmentVariable("pythonLocation");
        if (!string.IsNullOrWhiteSpace(pythonLocation))
        {
            var actionPython = Path.Combine(pythonLocation, "python.exe");
            if (File.Exists(actionPython))
            {
                return actionPython;
            }
        }

        var root = FindRepositoryRoot();
        foreach (var relativePath in new[]
                 {
                     Path.Combine(".venv-build", "Scripts", "python.exe"),
                     Path.Combine(".venv", "Scripts", "python.exe"),
                 })
        {
            var candidate = Path.Combine(root, relativePath);
            if (File.Exists(candidate))
            {
                return candidate;
            }
        }

        return null;
    }

    private static string FindRepositoryRoot()
    {
        var directory = new DirectoryInfo(AppContext.BaseDirectory);
        for (var depth = 0; directory is not null && depth < 12; depth++, directory = directory.Parent)
        {
            if (File.Exists(Path.Combine(directory.FullName, "lightnovel_selector", "sidecar.py")))
            {
                return directory.FullName;
            }
        }

        throw new AssertFailedException("未找到项目根目录。");
    }
}
