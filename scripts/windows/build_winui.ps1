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

function Invoke-ExternalOutput {
    param(
        [Parameter(Mandatory = $true)][string]$FilePath,
        [Parameter(Mandatory = $true)][string[]]$Arguments
    )

    $output = & $FilePath @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "Command failed with exit code ${LASTEXITCODE}: $FilePath"
    }
    return (($output | Out-String).Trim())
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

function Copy-ReleaseFile {
    param(
        [Parameter(Mandatory = $true)][string]$Source,
        [Parameter(Mandatory = $true)][string]$Destination,
        [Parameter(Mandatory = $true)][string]$DestinationRoot
    )

    if (-not (Test-Path -LiteralPath $Source -PathType Leaf)) {
        throw "Required release file was not found: $Source"
    }
    $safeDestination = Assert-ChildPath -Path $Destination -Parent $DestinationRoot
    Copy-Item -LiteralPath $Source -Destination $safeDestination -Force
    if (-not (Test-Path -LiteralPath $safeDestination -PathType Leaf) -or
        (Get-Item -LiteralPath $safeDestination).Length -eq 0) {
        throw "Required release file was not copied correctly: $safeDestination"
    }
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
        $process = Start-Process -FilePath $AppPath -PassThru
        if (-not $process.WaitForExit(30000)) {
            try {
                $process.Kill($true)
                $process.WaitForExit(5000)
            }
            catch {
            }
            throw "WinUI $Mode smoke test timed out after 30 seconds."
        }
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
$assemblyVersion = "$numericVersion.0"

[xml]$nativeProjectXml = Get-Content -LiteralPath (
    Join-Path $ProjectRoot "native\LightNovelSelector.WinUI\LightNovelSelector.WinUI.csproj"
)
[xml]$appManifestXml = Get-Content -LiteralPath (
    Join-Path $ProjectRoot "native\LightNovelSelector.WinUI\app.manifest"
)
[xml]$packageManifestXml = Get-Content -LiteralPath (
    Join-Path $ProjectRoot "native\LightNovelSelector.WinUI\Package.appxmanifest"
)
$versionChecks = [ordered]@{
    "C# Version" = @(
        [string]$nativeProjectXml.SelectSingleNode("/Project/PropertyGroup/Version").InnerText,
        $appVersion
    )
    "C# AssemblyVersion" = @(
        [string]$nativeProjectXml.SelectSingleNode("/Project/PropertyGroup/AssemblyVersion").InnerText,
        $assemblyVersion
    )
    "C# FileVersion" = @(
        [string]$nativeProjectXml.SelectSingleNode("/Project/PropertyGroup/FileVersion").InnerText,
        $assemblyVersion
    )
    "C# InformationalVersion" = @(
        [string]$nativeProjectXml.SelectSingleNode("/Project/PropertyGroup/InformationalVersion").InnerText,
        $appVersion
    )
    "app.manifest version" = @(
        [string]$appManifestXml.SelectSingleNode(
            "/*[local-name()='assembly']/*[local-name()='assemblyIdentity']"
        ).GetAttribute("version"),
        $assemblyVersion
    )
    "Package.appxmanifest version" = @(
        [string]$packageManifestXml.SelectSingleNode(
            "/*[local-name()='Package']/*[local-name()='Identity']"
        ).GetAttribute("Version"),
        $assemblyVersion
    )
}
foreach ($entry in $versionChecks.GetEnumerator()) {
    if ($entry.Value[0] -ne $entry.Value[1]) {
        throw "$($entry.Key) is $($entry.Value[0]); expected $($entry.Value[1])."
    }
}
Write-Host "Version metadata verified: $appVersion"

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
    "-p:DebugType=None", "-p:DebugSymbols=false",
    "--no-restore", "--output", $publishRoot
)

$releaseOnlyArtifacts = @(
    Get-ChildItem -LiteralPath $publishRoot -Recurse -File |
        Where-Object {
            $_.Extension -ieq ".pdb" -or
            $_.Name -ilike "*.runtimeconfig.dev.json"
        }
)
foreach ($artifact in $releaseOnlyArtifacts) {
    $safeArtifact = Assert-ChildPath -Path $artifact.FullName -Parent $publishRoot
    Remove-Item -LiteralPath $safeArtifact -Force
}

$unexpectedReleaseArtifacts = @(
    $releaseOnlyArtifacts | Where-Object { Test-Path -LiteralPath $_.FullName }
)
if ($unexpectedReleaseArtifacts.Count -gt 0) {
    $artifactNames = ($unexpectedReleaseArtifacts | ForEach-Object { $_.FullName }) -join ", "
    throw "Release staging still contains development-only artifacts: $artifactNames"
}

$licenseOutput = Reset-SafeDirectory -Path (Join-Path $publishRoot "licenses") -Parent $publishRoot
$pythonBase = Invoke-ExternalOutput -FilePath $python -Arguments @(
    "-c", "import sys; print(sys.base_prefix)"
)
$sitePackages = Invoke-ExternalOutput -FilePath $python -Arguments @(
    "-c", "import sysconfig; print(sysconfig.get_path('purelib'))"
)
$pythonVersion = Invoke-ExternalOutput -FilePath $python -Arguments @(
    "-c", "import platform; print(platform.python_version())"
)
$pyInstallerVersion = Invoke-ExternalOutput -FilePath $python -Arguments @(
    "-c", "import importlib.metadata as metadata; print(metadata.version('pyinstaller'))"
)
$defusedXmlVersion = Invoke-ExternalOutput -FilePath $python -Arguments @(
    "-c", "import importlib.metadata as metadata; print(metadata.version('defusedxml'))"
)
$dotnetSdkVersion = Invoke-ExternalOutput -FilePath $dotnet -Arguments @("--version")

$defusedXmlLicenses = @(
    Get-ChildItem -LiteralPath $sitePackages -Directory -Filter "defusedxml-*.dist-info" |
        ForEach-Object { Join-Path $_.FullName "LICENSE" } |
        Where-Object { Test-Path -LiteralPath $_ -PathType Leaf }
)
if ($defusedXmlLicenses.Count -ne 1) {
    throw "Expected exactly one defusedxml license, found $($defusedXmlLicenses.Count)."
}

$pyInstallerLicenses = @(
    Get-ChildItem -LiteralPath $sitePackages -Directory -Filter "pyinstaller-*.dist-info" |
        ForEach-Object { Join-Path $_.FullName "licenses\COPYING.txt" } |
        Where-Object { Test-Path -LiteralPath $_ -PathType Leaf }
)
if ($pyInstallerLicenses.Count -ne 1) {
    throw "Expected exactly one PyInstaller license, found $($pyInstallerLicenses.Count)."
}

$packageLockPath = Join-Path $ProjectRoot "native\LightNovelSelector.WinUI\packages.lock.json"
$packageLock = Get-Content -LiteralPath $packageLockPath -Raw | ConvertFrom-Json
$frameworkEntries = @($packageLock.dependencies.PSObject.Properties)
$windowsAppSdkVersions = @(
    $frameworkEntries |
        ForEach-Object {
            $packageEntry = $_.Value.PSObject.Properties["Microsoft.WindowsAppSDK"]
            if ($null -ne $packageEntry) {
                $packageEntry.Value.resolved
            }
        } |
        Where-Object { $_ } |
        Select-Object -Unique
)
$webView2Versions = @(
    $frameworkEntries |
        ForEach-Object {
            $packageEntry = $_.Value.PSObject.Properties["Microsoft.Web.WebView2"]
            if ($null -ne $packageEntry) {
                $packageEntry.Value.resolved
            }
        } |
        Where-Object { $_ } |
        Select-Object -Unique
)
if ($windowsAppSdkVersions.Count -ne 1 -or $webView2Versions.Count -ne 1) {
    throw "Unable to resolve a single Windows App SDK and WebView2 version from packages.lock.json."
}

$nugetPackages = if ($env:NUGET_PACKAGES) {
    [IO.Path]::GetFullPath($env:NUGET_PACKAGES)
}
else {
    [IO.Path]::GetFullPath((Join-Path $env:USERPROFILE ".nuget\packages"))
}
$windowsAppSdkPackage = Join-Path (
    Join-Path $nugetPackages "microsoft.windowsappsdk"
) $windowsAppSdkVersions[0]
$webView2Package = Join-Path (
    Join-Path $nugetPackages "microsoft.web.webview2"
) $webView2Versions[0]
$dotnetRoot = Split-Path -Parent $dotnet
$innoSetupRoot = Split-Path -Parent $iscc

Copy-ReleaseFile -Source (Join-Path $ProjectRoot "LICENSE") `
    -Destination (Join-Path $publishRoot "LICENSE") -DestinationRoot $publishRoot
Copy-ReleaseFile -Source (Join-Path $ProjectRoot "THIRD_PARTY_NOTICES.md") `
    -Destination (Join-Path $publishRoot "THIRD_PARTY_NOTICES.md") -DestinationRoot $publishRoot
Copy-ReleaseFile -Source (Join-Path $pythonBase "LICENSE.txt") `
    -Destination (Join-Path $licenseOutput "Python-LICENSE.txt") -DestinationRoot $licenseOutput
Copy-ReleaseFile -Source $defusedXmlLicenses[0] `
    -Destination (Join-Path $licenseOutput "defusedxml-LICENSE.txt") -DestinationRoot $licenseOutput
Copy-ReleaseFile -Source $pyInstallerLicenses[0] `
    -Destination (Join-Path $licenseOutput "PyInstaller-COPYING.txt") -DestinationRoot $licenseOutput
Copy-ReleaseFile -Source (Join-Path $dotnetRoot "LICENSE.txt") `
    -Destination (Join-Path $licenseOutput "dotnet-LICENSE.txt") -DestinationRoot $licenseOutput
Copy-ReleaseFile -Source (Join-Path $dotnetRoot "ThirdPartyNotices.txt") `
    -Destination (Join-Path $licenseOutput "dotnet-ThirdPartyNotices.txt") -DestinationRoot $licenseOutput
Copy-ReleaseFile -Source (Join-Path $windowsAppSdkPackage "license.txt") `
    -Destination (Join-Path $licenseOutput "WindowsAppSDK-LICENSE.txt") -DestinationRoot $licenseOutput
Copy-ReleaseFile -Source (Join-Path $windowsAppSdkPackage "NOTICE.txt") `
    -Destination (Join-Path $licenseOutput "WindowsAppSDK-NOTICE.txt") -DestinationRoot $licenseOutput
Copy-ReleaseFile -Source (Join-Path $webView2Package "LICENSE.txt") `
    -Destination (Join-Path $licenseOutput "WebView2-LICENSE.txt") -DestinationRoot $licenseOutput
Copy-ReleaseFile -Source (Join-Path $webView2Package "NOTICE.txt") `
    -Destination (Join-Path $licenseOutput "WebView2-NOTICE.txt") -DestinationRoot $licenseOutput
Copy-ReleaseFile -Source (Join-Path $innoSetupRoot "license.txt") `
    -Destination (Join-Path $licenseOutput "InnoSetup-LICENSE.txt") -DestinationRoot $licenseOutput

$componentVersionsPath = Assert-ChildPath `
    -Path (Join-Path $licenseOutput "COMPONENT_VERSIONS.txt") -Parent $licenseOutput
$componentVersions = @(
    "LightNovelSelector=$appVersion",
    "Python=$pythonVersion",
    "PyInstaller=$pyInstallerVersion",
    "defusedxml=$defusedXmlVersion",
    "DotNetSdk=$dotnetSdkVersion",
    "WindowsAppSDK=$($windowsAppSdkVersions[0])",
    "WebView2=$($webView2Versions[0])",
    "InnoSetup=6"
)
[IO.File]::WriteAllLines(
    $componentVersionsPath,
    $componentVersions,
    [Text.UTF8Encoding]::new($false)
)
if ((Get-Item -LiteralPath $componentVersionsPath).Length -eq 0) {
    throw "Third-party component version manifest is empty."
}

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
