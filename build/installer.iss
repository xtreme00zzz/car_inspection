; eF Drift Car Scrutineer — Public Installer
; Build with: iscc.exe build\installer.iss /DAppVersion=1.0.0 /DDistRoot="..\dist" /DPayloadRoot="..\dist\release_payload"

#define AppName "eF Drift Car Scrutineer"
#ifndef AppVersion
#define AppVersion "0.1.0"
#endif

#ifndef DistRoot
#define DistRoot "..\dist"
#endif
#ifndef PayloadRoot
#define PayloadRoot "..\dist\release_payload"
#endif
#ifndef AppFolderName
#define AppFolderName "eF Drift Car Scrutineer"
#endif
#ifndef AppExeName
#define AppExeName "eF Drift Car Scrutineer.exe"
#endif
#ifndef OutputDir
#define OutputDir "..\dist"
#endif

[Setup]
AppId={{A8D7C6A5-4B32-4C43-8B6D-3F2A8B2B1D9C}
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher=eF Drift
AppPublisherURL=https://github.com/xtreme00zzz/car_inspection
DefaultDirName={autopf}\{#AppName}
DefaultGroupName={#AppName}
DisableDirPage=no
DisableProgramGroupPage=yes
OutputDir={#OutputDir}
OutputBaseFilename=efdrift-scrutineer-setup
; Allow overriding installer icon from command line via /DInstallerIcon="path\icon.ico"
#ifndef InstallerIcon
#define InstallerIcon "..\\icon.ico"
#endif
; Use the provided application icon for the installer EXE
SetupIconFile={#InstallerIcon}
; Show the installed app's icon in Apps & Features for uninstall
UninstallDisplayIcon={app}\{#AppExeName}
; Disable disk spanning to produce a single EXE
DiskSpanning=no
Compression=lzma
SolidCompression=yes
ArchitecturesInstallIn64BitMode=x64
PrivilegesRequired=admin
SetupLogging=yes

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "Create a &desktop shortcut"; GroupDescription: "Additional icons:"; Flags: unchecked

[Files]
; Onedir app folder
Source: "{#DistRoot}\{#AppFolderName}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
; Ensure main EXE is present at root (redundant but defensive)
Source: "{#DistRoot}\{#AppFolderName}\{#AppExeName}"; DestDir: "{app}"; Flags: ignoreversion
; Updater stub (if present)
Source: "{#DistRoot}\{#AppFolderName}\eF Drift Car Scrutineer Updater.exe"; DestDir: "{app}"; Flags: ignoreversion skipifsourcedoesntexist
; Docs and version
Source: "{#PayloadRoot}\docs\README.md"; DestDir: "{app}\docs"; Flags: ignoreversion skipifsourcedoesntexist
Source: "{#PayloadRoot}\VERSION.txt"; DestDir: "{app}"; Flags: ignoreversion skipifsourcedoesntexist

[Icons]
Name: "{autoprograms}\{#AppName}"; Filename: "{app}\{#AppExeName}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExeName}"; Tasks: desktopicon

[Run]
; Launch installed app directly with proper working dir
Filename: "{app}\{#AppExeName}"; WorkingDir: "{app}"; Description: "Launch {#AppName}"; Flags: nowait postinstall skipifsilent
