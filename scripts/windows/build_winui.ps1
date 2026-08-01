[CmdletBinding()]
[Diagnostics.CodeAnalysis.SuppressMessageAttribute(
    "PSAvoidUsingWriteHost",
    "",
    Justification = "This interactive build entry point intentionally prints numbered progress and final artifact paths."
)]
[Diagnostics.CodeAnalysis.SuppressMessageAttribute(
    "PSAvoidUsingConvertToSecureStringWithPlainText",
    "",
    Justification = "The secret arrives through an environment variable and is converted immediately; it is never persisted or logged."
)]
param(
    [switch]$SkipDependencyInstall,
    [switch]$SkipTests,
    [switch]$KeepStaging,
    [string]$SigningCertificatePath = $env:WINDOWS_SIGNING_PFX_PATH,
    [Security.SecureString]$SigningCertificatePassword = $(
        if ($env:WINDOWS_SIGNING_PFX_PASSWORD) {
            ConvertTo-SecureString -String $env:WINDOWS_SIGNING_PFX_PASSWORD -AsPlainText -Force
        }
        else {
            $null
        }
    ),
    [string]$TimestampUrl = "https://timestamp.digicert.com",
    [switch]$RequireSignature,
    [switch]$RequireCleanSource
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

function New-SafeBuildDirectory {
    [CmdletBinding(SupportsShouldProcess = $true, ConfirmImpact = "Low")]
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)][string]$Parent
    )

    $safePath = Assert-ChildPath -Path $Path -Parent $Parent
    if (-not $PSCmdlet.ShouldProcess($safePath, "Reset build staging directory")) {
        return $safePath
    }
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

function Find-SignTool {
    $candidates = @(
        (Get-Command signtool.exe -ErrorAction SilentlyContinue |
            Select-Object -ExpandProperty Source -First 1)
    )
    foreach ($kitsRoot in @(
        (Join-Path ${env:ProgramFiles(x86)} "Windows Kits\10\bin"),
        (Join-Path $env:ProgramFiles "Windows Kits\10\bin")
    )) {
        if (-not (Test-Path -LiteralPath $kitsRoot -PathType Container)) {
            continue
        }
        $candidates += @(
            Get-ChildItem -LiteralPath $kitsRoot -Directory |
                Sort-Object -Property Name -Descending |
                ForEach-Object { Join-Path $_.FullName "x64\signtool.exe" }
        )
    }
    return Find-CommandPath -Candidates $candidates
}

function Invoke-AuthenticodeSign {
    param(
        [Parameter(Mandatory = $true)][string]$SignTool,
        [Parameter(Mandatory = $true)][string]$CertificatePath,
        [Security.SecureString]$CertificatePassword,
        [Parameter(Mandatory = $true)][string]$TimestampServer,
        [Parameter(Mandatory = $true)][string]$Path
    )

    $arguments = @(
        "sign", "/v",
        "/fd", "SHA256",
        "/tr", $TimestampServer,
        "/td", "SHA256",
        "/d", "LightNovelSelector",
        "/du", "https://github.com/chenhaoxiang05/LightNovelSelector",
        "/f", $CertificatePath
    )
    $passwordPointer = [IntPtr]::Zero
    try {
        if ($null -ne $CertificatePassword -and $CertificatePassword.Length -gt 0) {
            $passwordPointer = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($CertificatePassword)
            $plainText = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($passwordPointer)
            $arguments += @("/p", $plainText)
        }
        $arguments += $Path

        & $SignTool @arguments | Out-Host
        if ($LASTEXITCODE -ne 0) {
            throw "Authenticode signing failed with exit code ${LASTEXITCODE}: $Path"
        }
    }
    finally {
        $arguments = @()
        $plainText = $null
        if ($passwordPointer -ne [IntPtr]::Zero) {
            [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($passwordPointer)
        }
    }
    & $SignTool verify /pa /all /tw $Path | Out-Host
    if ($LASTEXITCODE -ne 0) {
        throw "Authenticode verification failed with exit code ${LASTEXITCODE}: $Path"
    }
    $signature = Get-AuthenticodeSignature -LiteralPath $Path
    if ($signature.Status -ne [Management.Automation.SignatureStatus]::Valid -or
        $null -eq $signature.SignerCertificate) {
        throw "PowerShell did not accept the Authenticode signature for: $Path"
    }
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

    $python = Get-Command python.exe -ErrorAction SilentlyContinue
    if ($python -and (Test-Python -Path $python.Source)) {
        Invoke-External -FilePath $python.Source -Arguments @("-m", "venv", (Join-Path $ProjectRoot ".venv-build"))
        return $venvPath
    }

    $launcher = Get-Command py.exe -ErrorAction SilentlyContinue
    if ($launcher) {
        & $launcher.Source -3 -c "import sys; raise SystemExit(sys.version_info < (3, 10))" *> $null
        if ($LASTEXITCODE -eq 0) {
            Invoke-External -FilePath $launcher.Source -Arguments @("-3", "-m", "venv", (Join-Path $ProjectRoot ".venv-build"))
            return $venvPath
        }
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
                Write-Verbose "The timed-out smoke-test process had already exited."
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
$dotnetRuntimes = Invoke-ExternalOutput -FilePath $dotnet -Arguments @("--list-runtimes")
if ($dotnetRuntimes -notmatch "(?m)^Microsoft\.NETCore\.App 8\.") {
    throw ".NET 8 Runtime is required by the pinned SBOM tool. Install it with: winget install Microsoft.DotNet.Runtime.8"
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

$signingEnabled = -not [string]::IsNullOrWhiteSpace($SigningCertificatePath)
if ($RequireSignature -and -not $signingEnabled) {
    throw "A signing certificate is required, but WINDOWS_SIGNING_PFX_PATH or -SigningCertificatePath was not provided."
}
$signTool = $null
$signingCertificate = $null
if ($signingEnabled) {
    $signingCertificate = [IO.Path]::GetFullPath($SigningCertificatePath)
    if (-not (Test-Path -LiteralPath $signingCertificate -PathType Leaf)) {
        throw "The Authenticode signing certificate was not found: $signingCertificate"
    }
    if (-not [Uri]::IsWellFormedUriString($TimestampUrl, [UriKind]::Absolute) -or
        -not $TimestampUrl.StartsWith("https://", [StringComparison]::OrdinalIgnoreCase)) {
        throw "The Authenticode timestamp URL must be an absolute HTTPS URL."
    }
    $signTool = Find-SignTool
    if (-not $signTool) {
        throw "SignTool was not found. Install the Windows SDK before requesting Authenticode signing."
    }
    Write-Host "Authenticode signing is enabled."
}
else {
    Write-Warning "No code-signing certificate was configured. Release metadata will mark this build as unsigned."
}

$python = Find-Python
if (-not $SkipDependencyInstall) {
    Write-Host "[1/11] Installing build dependencies..."
    Invoke-External -FilePath $python -Arguments @("-m", "pip", "install", "--disable-pip-version-check", "-r", (Join-Path $ProjectRoot "requirements-dev.txt"))
}

Write-Host "[2/11] Restoring release tools and generating native assets..."
Invoke-External -FilePath $dotnet -Arguments @("tool", "restore")
Invoke-External -FilePath $python -Arguments @((Join-Path $ProjectRoot "tools\generate_native_assets.py"))

$sidecarOutput = New-SafeBuildDirectory -Path (Join-Path $BuildRoot "native-sidecar") -Parent $BuildRoot
$pyInstallerWork = New-SafeBuildDirectory -Path (Join-Path $BuildRoot "pyinstaller-sidecar") -Parent $BuildRoot
$specOutput = New-SafeBuildDirectory -Path (Join-Path $BuildRoot "spec") -Parent $BuildRoot
$publishRoot = New-SafeBuildDirectory -Path (Join-Path $BuildRoot "winui-package") -Parent $BuildRoot
$installerBuild = New-SafeBuildDirectory -Path (Join-Path $BuildRoot "winui-installer") -Parent $BuildRoot
$sbomComponentRoot = New-SafeBuildDirectory -Path (Join-Path $BuildRoot "sbom-components") -Parent $BuildRoot
$sbomManifestRoot = New-SafeBuildDirectory -Path (Join-Path $BuildRoot "sbom-manifest") -Parent $BuildRoot
$sbomValidationDrop = New-SafeBuildDirectory -Path (Join-Path $BuildRoot "sbom-validation-drop") -Parent $BuildRoot

Write-Host "[3/11] Building the Python Sidecar..."
Invoke-External -FilePath $python -Arguments @(
    "-m", "PyInstaller", "--noconfirm", "--clean", "--onefile", "--console",
    "--workpath", $pyInstallerWork,
    "--specpath", $specOutput,
    "--distpath", $sidecarOutput,
    "--name", "LightNovelSelector.Sidecar",
    (Join-Path $ProjectRoot "lightnovel_sidecar.py")
)

$sidecarExe = Join-Path $sidecarOutput "LightNovelSelector.Sidecar.exe"
Write-Host "[4/11] Verifying the Sidecar protocol..."
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
    Write-Host "[5/11] Running Python checks..."
    Invoke-External -FilePath $python -Arguments @("-m", "pip", "check")
    Invoke-External -FilePath $python -Arguments @("-m", "py_compile", (Join-Path $ProjectRoot "lightnovel_classifier.py"), (Join-Path $ProjectRoot "lightnovel_sidecar.py"))
    Invoke-External -FilePath $python -Arguments @("-m", "pytest", "-q")
    Invoke-External -FilePath $python -Arguments @("-m", "ruff", "check", ".")
    Invoke-External -FilePath $python -Arguments @("-m", "ruff", "format", "--check", ".")
    Invoke-External -FilePath $python -Arguments @("-m", "mypy", "lightnovel_classifier.py", "lightnovel_sidecar.py", "lightnovel_selector", "tests", "tools")
    Invoke-External -FilePath $python -Arguments @("-m", "bandit", "-q", "-r", "lightnovel_selector", "lightnovel_classifier.py", "lightnovel_sidecar.py", "tools")
    Invoke-External -FilePath $python -Arguments @("-m", "vulture", "lightnovel_classifier.py", "lightnovel_selector", "tests", "tools", "--min-confidence", "80")
    Invoke-External -FilePath $python -Arguments @(
        "-m", "pip_audit", "-r", "requirements-dev.txt", "--strict",
        "--cache-dir", (Join-Path $BuildRoot "pip-audit-cache"),
        "--progress-spinner", "off"
    )

    Write-Host "[6/11] Running C# tests..."
    $testProject = Join-Path $ProjectRoot "native\LightNovelSelector.WinUI.Tests\LightNovelSelector.WinUI.Tests.csproj"
    Invoke-External -FilePath $dotnet -Arguments @("restore", $testProject, "--locked-mode")
    Invoke-External -FilePath $dotnet -Arguments @("test", $testProject, "-c", "Release", "--no-restore", "--logger", "console;verbosity=minimal")
}
else {
    Write-Host "[5/11] Python checks skipped."
    Write-Host "[6/11] C# tests skipped."
}

Write-Host "[7/11] Publishing the self-contained WinUI app to staging..."
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

$licenseOutput = New-SafeBuildDirectory -Path (Join-Path $publishRoot "licenses") -Parent $publishRoot
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
$innoSetupVersion = [Diagnostics.FileVersionInfo]::GetVersionInfo($iscc).ProductVersion
if ([string]::IsNullOrWhiteSpace($innoSetupVersion) -or $innoSetupVersion -eq "0.0.0.0") {
    $innoUninstaller = Join-Path $innoSetupRoot "unins000.exe"
    if (Test-Path -LiteralPath $innoUninstaller -PathType Leaf) {
        $innoSetupVersion = [Diagnostics.FileVersionInfo]::GetVersionInfo($innoUninstaller).ProductVersion
    }
}
if ([string]::IsNullOrWhiteSpace($innoSetupVersion) -or $innoSetupVersion -notmatch "\d+\.\d+") {
    throw "Unable to read the Inno Setup version."
}
$innoSetupVersion = [regex]::Match($innoSetupVersion, "\d+(?:\.\d+)+").Value

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
    "InnoSetup=$innoSetupVersion"
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
$appDll = Join-Path $publishRoot "LightNovelSelector.dll"
$publishedSidecar = Join-Path $publishRoot "LightNovelSelector.Sidecar.exe"
if (-not (Test-Path -LiteralPath $appExe -PathType Leaf)) {
    throw "The WinUI executable was not published."
}
if (-not (Test-Path -LiteralPath $appDll -PathType Leaf)) {
    throw "The WinUI application assembly was not published."
}
if (-not (Test-Path -LiteralPath $publishedSidecar -PathType Leaf)) {
    throw "The Python Sidecar was not copied into the publish staging directory."
}

Write-Host "[8/11] Applying and verifying project Authenticode signatures..."
$signerSubject = $null
if ($signingEnabled) {
    foreach ($ownedBinary in @($appExe, $appDll, $publishedSidecar)) {
        Invoke-AuthenticodeSign `
            -SignTool $signTool `
            -CertificatePath $signingCertificate `
            -CertificatePassword $SigningCertificatePassword `
            -TimestampServer $TimestampUrl `
            -Path $ownedBinary
    }
}
else {
    Write-Host "Project binaries remain unsigned for this development build."
}

Write-Host "[9/11] Running startup and appearance smoke tests..."
Invoke-AppSmokeTest -AppPath $appExe -Mode "startup"
Invoke-AppSmokeTest -AppPath $appExe -Mode "appearance"

Write-Host "[10/11] Compiling the single EXE installer..."
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
if ($signingEnabled) {
    Invoke-AuthenticodeSign `
        -SignTool $signTool `
        -CertificatePath $signingCertificate `
        -CertificatePassword $SigningCertificatePassword `
        -TimestampServer $TimestampUrl `
        -Path $builtInstaller
    $installerSignature = Get-AuthenticodeSignature -LiteralPath $builtInstaller
    $signerSubject = $installerSignature.SignerCertificate.Subject
}

$distParent = Join-Path $ProjectRoot "dist"
if (-not (Test-Path -LiteralPath $distParent)) {
    New-Item -ItemType Directory -Path $distParent -Force | Out-Null
}
$nextDist = New-SafeBuildDirectory -Path (Join-Path $distParent ".winui-next") -Parent $distParent
$nextInstaller = Join-Path $nextDist "${installerBaseName}.exe"
Copy-Item -LiteralPath $builtInstaller -Destination $nextInstaller

Write-Host "[11/11] Generating and verifying release metadata..."
$sbomNativeRoot = Join-Path $sbomComponentRoot "native\LightNovelSelector.WinUI"
$sbomNativeObj = Join-Path $sbomNativeRoot "obj"
New-Item -ItemType Directory -Path $sbomNativeObj -Force | Out-Null
Copy-ReleaseFile `
    -Source (Join-Path $ProjectRoot "native\LightNovelSelector.WinUI\LightNovelSelector.WinUI.csproj") `
    -Destination (Join-Path $sbomNativeRoot "LightNovelSelector.WinUI.csproj") `
    -DestinationRoot $sbomComponentRoot
Copy-ReleaseFile `
    -Source (Join-Path $ProjectRoot "native\LightNovelSelector.WinUI\packages.lock.json") `
    -Destination (Join-Path $sbomNativeRoot "packages.lock.json") `
    -DestinationRoot $sbomComponentRoot
Copy-ReleaseFile `
    -Source (Join-Path $ProjectRoot "native\LightNovelSelector.WinUI\obj\project.assets.json") `
    -Destination (Join-Path $sbomNativeObj "project.assets.json") `
    -DestinationRoot $sbomComponentRoot
Copy-ReleaseFile `
    -Source (Join-Path $ProjectRoot "native\LightNovelSelector.WinUI\obj\LightNovelSelector.WinUI.csproj.nuget.dgspec.json") `
    -Destination (Join-Path $sbomNativeObj "LightNovelSelector.WinUI.csproj.nuget.dgspec.json") `
    -DestinationRoot $sbomComponentRoot

foreach ($packageVersion in @($appVersion, $defusedXmlVersion, $pyInstallerVersion)) {
    if ($packageVersion -notmatch "^[0-9A-Za-z.+-]+$") {
        throw "Unsafe package version in SBOM component metadata: $packageVersion"
    }
}
$pep440Version = $appVersion -replace "-dev\.", ".dev"
$sbomSetupPath = Assert-ChildPath -Path (Join-Path $sbomComponentRoot "setup.py") -Parent $sbomComponentRoot
$sbomSetup = @(
    "from setuptools import setup",
    "",
    "setup(",
    "    name='lightnovelselector-sidecar',",
    "    version='$pep440Version',",
    "    install_requires=[",
    "        'defusedxml==$defusedXmlVersion',",
    "        'pyinstaller==$pyInstallerVersion',",
    "    ],",
    ")"
)
[IO.File]::WriteAllLines($sbomSetupPath, $sbomSetup, [Text.UTF8Encoding]::new($false))

$git = Get-Command git.exe -ErrorAction SilentlyContinue
$sourceCommit = "unknown"
$sourceRef = if ($env:GITHUB_REF_NAME) { $env:GITHUB_REF_NAME } else { "unknown" }
$sourceDirty = $true
if ($git) {
    try {
        $sourceCommit = Invoke-ExternalOutput -FilePath $git.Source -Arguments @("-C", $ProjectRoot, "rev-parse", "HEAD")
        $gitStatus = Invoke-ExternalOutput -FilePath $git.Source -Arguments @(
            "-C", $ProjectRoot, "status", "--porcelain=v1", "--untracked-files=normal"
        )
        $sourceDirty = -not [string]::IsNullOrWhiteSpace($gitStatus)
        if (-not $env:GITHUB_REF_NAME) {
            $branchName = Invoke-ExternalOutput -FilePath $git.Source -Arguments @(
                "-C", $ProjectRoot, "branch", "--show-current"
            )
            if ($branchName) {
                $sourceRef = $branchName
            }
        }
    }
    catch {
        Write-Warning "Unable to record Git source metadata; using 'unknown'."
        $sourceCommit = "unknown"
        $sourceRef = "unknown"
    }
}
if ($RequireCleanSource -and $sourceDirty) {
    throw "A clean Git worktree is required for this build, but tracked or untracked source changes were found."
}

$sbomNamespacePart = "${appVersion}-win-x64-${sourceCommit}"
Invoke-External -FilePath $dotnet -Arguments @(
    "tool", "run", "sbom-tool", "--", "generate",
    "-b", $nextDist,
    "-bc", $sbomComponentRoot,
    "-m", $sbomManifestRoot,
    "-pn", "LightNovelSelector",
    "-pv", $appVersion,
    "-ps", "LightNovelSelector contributors",
    "-nsb", "https://github.com/chenhaoxiang05/LightNovelSelector",
    "-nsu", $sbomNamespacePart,
    "-mi", "SPDX:2.2",
    "-D", "true",
    "-F", "false",
    "-pm", "true",
    "-V", "Warning"
)
$generatedSbom = Join-Path $sbomManifestRoot "_manifest\spdx_2.2\manifest.spdx.json"
if (-not (Test-Path -LiteralPath $generatedSbom -PathType Leaf)) {
    throw "The SBOM tool did not produce the expected SPDX 2.2 manifest."
}
$sbomValidationPath = Join-Path $sbomManifestRoot "validation.json"
Invoke-External -FilePath $dotnet -Arguments @(
    "tool", "run", "sbom-tool", "--", "validate",
    "-b", $nextDist,
    "-m", (Join-Path $sbomManifestRoot "_manifest"),
    "-o", $sbomValidationPath,
    "-mi", "SPDX:2.2",
    "-F", "false",
    "-n", "true",
    "-V", "Warning"
)

$signatureStatus = if ($signingEnabled) { "verified" } else { "unsigned" }
$finalizeArguments = @(
    (Join-Path $ProjectRoot "tools\release_assets.py"), "finalize",
    "--dist", $nextDist,
    "--installer", "${installerBaseName}.exe",
    "--sbom-source", $generatedSbom,
    "--version", $appVersion,
    "--signature-status", $signatureStatus,
    "--source-commit", $sourceCommit,
    "--source-ref", $sourceRef,
    "--python-version", $pythonVersion,
    "--inno-version", $innoSetupVersion
)
if ($signerSubject) {
    $finalizeArguments += @("--signer-subject", $signerSubject)
}
if ($sourceDirty) {
    $finalizeArguments += "--source-dirty"
}
Invoke-External -FilePath $python -Arguments $finalizeArguments
$finalSbomFiles = @(Get-ChildItem -LiteralPath $nextDist -Filter "*-sbom.spdx.json" -File)
if ($finalSbomFiles.Count -ne 1) {
    throw "Expected exactly one finalized SPDX SBOM, found $($finalSbomFiles.Count)."
}
Copy-Item -LiteralPath $finalSbomFiles[0].FullName -Destination $generatedSbom -Force
$generatedSbomChecksum = "${generatedSbom}.sha256"
[IO.File]::WriteAllText(
    $generatedSbomChecksum,
    (Get-Sha256 -Path $generatedSbom).ToLowerInvariant(),
    [Text.UTF8Encoding]::new($false)
)
Copy-ReleaseFile `
    -Source $nextInstaller `
    -Destination (Join-Path $sbomValidationDrop "${installerBaseName}.exe") `
    -DestinationRoot $sbomValidationDrop
$finalSbomValidationPath = Join-Path $sbomManifestRoot "final-validation.json"
Invoke-External -FilePath $dotnet -Arguments @(
    "tool", "run", "sbom-tool", "--", "validate",
    "-b", $sbomValidationDrop,
    "-m", (Join-Path $sbomManifestRoot "_manifest"),
    "-o", $finalSbomValidationPath,
    "-mi", "SPDX:2.2",
    "-F", "false",
    "-n", "true",
    "-V", "Warning"
)
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
    Invoke-External -FilePath $python -Arguments @(
        (Join-Path $ProjectRoot "tools\release_assets.py"), "verify",
        "--dist", $finalDist
    )
}
catch {
    if (Test-Path -LiteralPath $finalDist) {
        Remove-Item -LiteralPath $finalDist -Recurse -Force
    }
    if ($movedPrevious) {
        Move-Item -LiteralPath $previousDist -Destination $finalDist
    }
    throw
}
if (Test-Path -LiteralPath $previousDist) {
    Remove-Item -LiteralPath $previousDist -Recurse -Force
}
$finalInstaller = Join-Path $finalDist "${installerBaseName}.exe"

if (-not $KeepStaging) {
    foreach ($temporaryPath in @(
        $publishRoot,
        $installerBuild,
        $sidecarOutput,
        $pyInstallerWork,
        $specOutput,
        $sbomComponentRoot,
        $sbomManifestRoot,
        $sbomValidationDrop
    )) {
        Remove-Item -LiteralPath (Assert-ChildPath -Path $temporaryPath -Parent $BuildRoot) -Recurse -Force
    }
}

Write-Host ""
Write-Host "Build completed successfully."
Write-Host "Installer: $finalInstaller"
Write-Host "SHA-256: $hash"
Write-Host "Authenticode: $signatureStatus"
Write-Host "Release assets:"
Get-ChildItem -LiteralPath $finalDist -File |
    Sort-Object -Property Name |
    ForEach-Object { Write-Host "  $($_.Name)" }
