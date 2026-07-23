[CmdletBinding()]
param(
    [switch]$SkipDependencyInstall,
    [switch]$SkipTests,
    [switch]$KeepStaging
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$ProjectRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot "..\.."))
$BuildRoot = Join-Path $ProjectRoot "build"
$DistRoot = Join-Path $ProjectRoot "dist\winui"

function Invoke-External {
    param(
        [Parameter(Mandatory = $true)][string]$FilePath,
        [Parameter(Mandatory = $true)][string[]]$Arguments
    )

    & $FilePath @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "Command failed with exit code ${LASTEXITCODE}: $FilePath"
    }
}

function Assert-ChildPath {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)][string]$Parent
    )

    $fullPath = [IO.Path]::GetFullPath($Path).TrimEnd("\")
    $fullParent = [IO.Path]::GetFullPath($Parent).TrimEnd("\")
    $prefix = $fullParent + "\"
    if (-not $fullPath.StartsWith($prefix, [StringComparison]::OrdinalIgnoreCase)) {
        throw "Refusing to modify path outside the expected root: $fullPath"
    }
    return $fullPath
}

function Reset-SafeDirectory {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)][string]$Parent
    )

    $safePath = Assert-ChildPath -Path $Path -Parent $Parent
    if (Test-Path -LiteralPath $safePath) {
        Remove-Item -LiteralPath $safePath -Recurse -Force
    }
    New-Item -ItemType Directory -Path $safePath -Force | Out-Null
    return $safePath
}

function Find-CommandPath {
    param([Parameter(Mandatory = $true)][AllowEmptyString()][string[]]$Candidates)

    foreach ($candidate in $Candidates) {
        if ($candidate -and (Test-Path -LiteralPath $candidate -PathType Leaf)) {
            return [IO.Path]::GetFullPath($candidate)
        }
    }
    return $null
}

function Test-Python {
    param([Parameter(Mandatory = $true)][string]$Path)

    & $Path -c "import sys; raise SystemExit(sys.version_info < (3, 10))" *> $null
    return $LASTEXITCODE -eq 0
}

function Get-Sha256 {
    param([Parameter(Mandatory = $true)][string]$Path)

    $stream = [IO.File]::OpenRead($Path)
    $sha256 = [Security.Cryptography.SHA256]::Create()
    try {
        return ([BitConverter]::ToString($sha256.ComputeHash($stream))).Replace("-", "")
    }
    finally {
        $sha256.Dispose()
        $stream.Dispose()
    }
}

function Find-Python {
    $venvPath = Join-Path $ProjectRoot ".venv-build\Scripts\python.exe"
    if ((Test-Path -LiteralPath $venvPath -PathType Leaf) -and (Test-Python -Path $venvPath)) {
        return $venvPath
    }

    if (Test-Path -LiteralPath (Join-Path $ProjectRoot ".venv-build")) {
        $safeVenv = Assert-ChildPath -Path (Join-Path $ProjectRoot ".venv-build") -Parent $ProjectRoot
        Remove-Item -LiteralPath $safeVenv -Recurse -Force
    }

    $launcher = Get-Command py.exe -ErrorAction SilentlyContinue
    if ($launcher) {
        & $launcher.Source -3 -c "import sys; raise SystemExit(sys.version_info < (3, 10))" *> $null
        if ($LASTEXITCODE -eq 0) {
            Invoke-External -FilePath $launcher.Source -Arguments @("-3", "-m", "venv", (Join-Path $ProjectRoot ".venv-build"))
            return $venvPath
        }
    }

    $python = Get-Command python.exe -ErrorAction SilentlyContinue
    if ($python -and (Test-Python -Path $python.Source)) {
        Invoke-External -FilePath $python.Source -Arguments @("-m", "venv", (Join-Path $ProjectRoot ".venv-build"))
        return $venvPath
    }

    throw "Python 3.10 or newer was not found."
}

function Invoke-AppSmokeTest {
    param(
        [Parameter(Mandatory = $true)][string]$AppPath,
        [Parameter(Mandatory = $true)][string]$Mode
    )

    $env:LN_SELECTOR_WINUI_TEST_THEME = "dark"
    $env:LN_SELECTOR_WINUI_TEST_MATERIAL = "acrylic"
    if ($Mode -eq "startup") {
        $env:LN_SELECTOR_WINUI_SMOKE_TEST = "1"
    }
    else {
        $env:LN_SELECTOR_WINUI_APPEARANCE_SMOKE_TEST = "1"
    }

    try {
        $process = Start-Process -FilePath $AppPath -PassThru -Wait
        if ($process.ExitCode -ne 0) {
            throw "WinUI $Mode smoke test failed with exit code $($process.ExitCode)."
        }
    }
    finally {
        Remove-Item Env:LN_SELECTOR_WINUI_SMOKE_TEST -ErrorAction SilentlyContinue
        Remove-Item Env:LN_SELECTOR_WINUI_APPEARANCE_SMOKE_TEST -ErrorAction SilentlyContinue
        Remove-Item Env:LN_SELECTOR_WINUI_TEST_THEME -ErrorAction SilentlyContinue
        Remove-Item Env:LN_SELECTOR_WINUI_TEST_MATERIAL -ErrorAction SilentlyContinue
    }
}

Set-Location -LiteralPath $ProjectRoot

$dotnet = Find-CommandPath -Candidates @(
    (Join-Path $env:ProgramFiles "dotnet\dotnet.exe"),
    (Get-Command dotnet.exe -ErrorAction SilentlyContinue | Select-Object -ExpandProperty Source -First 1)
)
if (-not $dotnet) {
    throw ".NET 10 SDK was not found. Install Microsoft.DotNet.SDK.10 first."
}

$iscc = Find-CommandPath -Candidates @(
    (Join-Path ${env:ProgramFiles(x86)} "Inno Setup 7\ISCC.exe"),
    (Join-Path $env:ProgramFiles "Inno Setup 7\ISCC.exe"),
    (Join-Path $env:LOCALAPPDATA "Programs\Inno Setup 7\ISCC.exe"),
    (Join-Path ${env:ProgramFiles(x86)} "Inno Setup 6\ISCC.exe"),
    (Join-Path $env:ProgramFiles "Inno Setup 6\ISCC.exe"),
    (Join-Path $env:LOCALAPPDATA "Programs\Inno Setup 6\ISCC.exe"),
    (Get-Command ISCC.exe -ErrorAction SilentlyContinue | Select-Object -ExpandProperty Source -First 1)
)
if (-not $iscc) {
    throw "Inno Setup 6 or newer was not found. Install it with: winget install JRSoftware.InnoSetup"
}

$python = Find-Python
if (-not $SkipDependencyInstall) {
    Write-Host "[1/9] Installing build dependencies..."
    Invoke-External -FilePath $python -Arguments @("-m", "pip", "install", "--disable-pip-version-check", "-r", (Join-Path $ProjectRoot "requirements-dev.txt"))
}

Write-Host "[2/9] Generating native assets..."
Invoke-External -FilePath $python -Arguments @((Join-Path $ProjectRoot "tools\generate_native_assets.py"))

$sidecarOutput = Reset-SafeDirectory -Path (Join-Path $BuildRoot "native-sidecar") -Parent $BuildRoot
$pyInstallerWork = Reset-SafeDirectory -Path (Join-Path $BuildRoot "pyinstaller-sidecar") -Parent $BuildRoot
$specOutput = Reset-SafeDirectory -Path (Join-Path $BuildRoot "spec") -Parent $BuildRoot
$publishRoot = Reset-SafeDirectory -Path (Join-Path $BuildRoot "winui-package") -Parent $BuildRoot
$installerBuild = Reset-SafeDirectory -Path (Join-Path $BuildRoot "winui-installer") -Parent $BuildRoot

Write-Host "[3/9] Building the Python Sidecar..."
Invoke-External -FilePath $python -Arguments @(
    "-m", "PyInstaller", "--noconfirm", "--clean", "--onefile", "--console",
    "--workpath", $pyInstallerWork,
    "--specpath", $specOutput,
    "--distpath", $sidecarOutput,
    "--name", "LightNovelSelector.Sidecar",
    (Join-Path $ProjectRoot "lightnovel_sidecar.py")
)

$sidecarExe = Join-Path $sidecarOutput "LightNovelSelector.Sidecar.exe"
Write-Host "[4/9] Verifying the Sidecar protocol..."
Invoke-External -FilePath $python -Arguments @((Join-Path $ProjectRoot "tools\verify_sidecar.py"), $sidecarExe)

$versionOutput = & $python -c "from lightnovel_selector.constants import APP_VERSION; print(APP_VERSION)"
if ($LASTEXITCODE -ne 0) {
    throw "Unable to read the application version."
}
$appVersion = ($versionOutput | Select-Object -Last 1).Trim()
if ($appVersion -notmatch "^\d+\.\d+\.\d+([-.][0-9A-Za-z.-]+)?$") {
    throw "Invalid application version: $appVersion"
}
$numericVersion = ($appVersion -split "[-+]", 2)[0]

if (-not $SkipTests) {
    Write-Host "[5/9] Running Python checks..."
    Invoke-External -FilePath $python -Arguments @("-m", "pip", "check")
    Invoke-External -FilePath $python -Arguments @("-m", "py_compile", (Join-Path $ProjectRoot "lightnovel_classifier.py"), (Join-Path $ProjectRoot "lightnovel_sidecar.py"))
    Invoke-External -FilePath $python -Arguments @("-m", "pytest", "-q")
    Invoke-External -FilePath $python -Arguments @("-m", "ruff", "check", ".")
    Invoke-External -FilePath $python -Arguments @("-m", "mypy", "lightnovel_classifier.py", "lightnovel_sidecar.py", "lightnovel_selector", "tests")
    Invoke-External -FilePath $python -Arguments @("-m", "bandit", "-q", "-r", "lightnovel_selector", "lightnovel_classifier.py", "lightnovel_sidecar.py")
    Invoke-External -FilePath $python -Arguments @("-m", "vulture", "lightnovel_classifier.py", "lightnovel_selector", "tests", "--min-confidence", "80")
    Invoke-External -FilePath $python -Arguments @("-m", "pip_audit", "-r", "requirements-dev.txt", "--strict")

    Write-Host "[6/9] Running C# tests..."
    $testProject = Join-Path $ProjectRoot "native\LightNovelSelector.WinUI.Tests\LightNovelSelector.WinUI.Tests.csproj"
    Invoke-External -FilePath $dotnet -Arguments @("restore", $testProject, "--locked-mode")
    Invoke-External -FilePath $dotnet -Arguments @("test", $testProject, "-c", "Release", "--no-restore", "--logger", "console;verbosity=minimal")
}
else {
    Write-Host "[5/9] Python checks skipped."
    Write-Host "[6/9] C# tests skipped."
}

Write-Host "[7/9] Publishing the self-contained WinUI app to staging..."
$appProject = Join-Path $ProjectRoot "native\LightNovelSelector.WinUI\LightNovelSelector.WinUI.csproj"
Invoke-External -FilePath $dotnet -Arguments @("restore", $appProject, "--locked-mode", "-r", "win-x64", "-p:Platform=x64", "-p:WindowsPackageType=None")
Invoke-External -FilePath $dotnet -Arguments @(
    "publish", $appProject,
    "-c", "Release", "-r", "win-x64",
    "-p:Platform=x64", "-p:WindowsPackageType=None",
    "-p:WindowsAppSDKSelfContained=true", "-p:SelfContained=true", "-p:PublishTrimmed=false",
    "--no-restore", "--output", $publishRoot
)

$appExe = Join-Path $publishRoot "LightNovelSelector.exe"
$publishedSidecar = Join-Path $publishRoot "LightNovelSelector.Sidecar.exe"
if (-not (Test-Path -LiteralPath $appExe -PathType Leaf)) {
    throw "The WinUI executable was not published."
}
if (-not (Test-Path -LiteralPath $publishedSidecar -PathType Leaf)) {
    throw "The Python Sidecar was not copied into the publish staging directory."
}

Write-Host "[8/9] Running startup and appearance smoke tests..."
Invoke-AppSmokeTest -AppPath $appExe -Mode "startup"
Invoke-AppSmokeTest -AppPath $appExe -Mode "appearance"

Write-Host "[9/9] Compiling the single EXE installer..."
$installerScript = Join-Path $PSScriptRoot "LightNovelSelector.iss"
$installerBaseName = "LightNovelSelector-v${appVersion}-win-x64-setup"
Invoke-External -FilePath $iscc -Arguments @(
    "/Qp", "/DAppVersion=$appVersion", "/DSourceDir=$publishRoot",
    "/DAppNumericVersion=$numericVersion", "/DProjectRoot=$ProjectRoot",
    "/DOutputDir=$installerBuild", "/F$installerBaseName", $installerScript
)

$builtInstaller = Join-Path $installerBuild "${installerBaseName}.exe"
if (-not (Test-Path -LiteralPath $builtInstaller -PathType Leaf)) {
    throw "The installer compiler completed without producing the expected EXE."
}

$distParent = Join-Path $ProjectRoot "dist"
if (-not (Test-Path -LiteralPath $distParent)) {
    New-Item -ItemType Directory -Path $distParent -Force | Out-Null
}
$nextDist = Reset-SafeDirectory -Path (Join-Path $distParent ".winui-next") -Parent $distParent
$nextInstaller = Join-Path $nextDist "${installerBaseName}.exe"
Copy-Item -LiteralPath $builtInstaller -Destination $nextInstaller
$hash = Get-Sha256 -Path $nextInstaller

$finalDist = Assert-ChildPath -Path $DistRoot -Parent $distParent
$previousDist = Assert-ChildPath -Path (Join-Path $distParent ".winui-previous") -Parent $distParent
if (-not (Test-Path -LiteralPath $finalDist) -and (Test-Path -LiteralPath $previousDist)) {
    Move-Item -LiteralPath $previousDist -Destination $finalDist
}
if (Test-Path -LiteralPath $previousDist) {
    Remove-Item -LiteralPath $previousDist -Recurse -Force
}

$movedPrevious = $false
try {
    if (Test-Path -LiteralPath $finalDist) {
        Move-Item -LiteralPath $finalDist -Destination $previousDist
        $movedPrevious = $true
    }
    Move-Item -LiteralPath $nextDist -Destination $finalDist
}
catch {
    if ($movedPrevious -and -not (Test-Path -LiteralPath $finalDist)) {
        Move-Item -LiteralPath $previousDist -Destination $finalDist
    }
    throw
}
if (Test-Path -LiteralPath $previousDist) {
    Remove-Item -LiteralPath $previousDist -Recurse -Force
}
$finalInstaller = Join-Path $finalDist "${installerBaseName}.exe"

if (-not $KeepStaging) {
    foreach ($temporaryPath in @($publishRoot, $installerBuild, $sidecarOutput, $pyInstallerWork, $specOutput)) {
        Remove-Item -LiteralPath (Assert-ChildPath -Path $temporaryPath -Parent $BuildRoot) -Recurse -Force
    }
}

Write-Host ""
Write-Host "Build completed successfully."
Write-Host "Installer: $finalInstaller"
Write-Host "SHA-256: $hash"
