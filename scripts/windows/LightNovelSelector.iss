#ifndef AppVersion
  #error AppVersion is required
#endif
#ifndef AppNumericVersion
  #error AppNumericVersion is required
#endif
#ifndef SourceDir
  #error SourceDir is required
#endif
#ifndef OutputDir
  #error OutputDir is required
#endif
#ifndef ProjectRoot
  #error ProjectRoot is required
#endif

#define AppName "LightNovelSelector"
#define AppExeName "LightNovelSelector.exe"
#define AppPublisher "chenhaoxiang05"
#define AppUrl "https://github.com/chenhaoxiang05/LightNovelSelector"

[Setup]
AppId={{2BC7D233-A3F2-4E65-9F3A-43E7AA9493C9}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
AppPublisher={#AppPublisher}
AppPublisherURL={#AppUrl}
AppSupportURL={#AppUrl}/issues
AppUpdatesURL={#AppUrl}/releases
LicenseFile={#ProjectRoot}\LICENSE
DefaultDirName={localappdata}\Programs\{#AppName}
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0.17763
OutputDir={#OutputDir}
OutputBaseFilename={#AppName}-v{#AppVersion}-win-x64-setup
SetupIconFile={#ProjectRoot}\native\LightNovelSelector.WinUI\Assets\AppIcon.ico
UninstallDisplayIcon={app}\{#AppExeName}
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
CloseApplications=yes
RestartApplications=no
VersionInfoVersion={#AppNumericVersion}.0
VersionInfoCompany={#AppPublisher}
VersionInfoDescription=LightNovelSelector WinUI 3 Installer
VersionInfoProductName={#AppName}
VersionInfoProductVersion={#AppNumericVersion}.0

[Files]
Source: "{#SourceDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; GroupDescription: "Additional shortcuts:"; Flags: unchecked

[Icons]
Name: "{group}\{#AppName}"; Filename: "{app}\{#AppExeName}"; WorkingDir: "{app}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExeName}"; WorkingDir: "{app}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#AppExeName}"; Description: "Launch {#AppName}"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
Type: dirifempty; Name: "{app}"
