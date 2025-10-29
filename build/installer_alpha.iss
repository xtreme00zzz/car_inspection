#define AppName "eF Drift Car Scrutineer Alpha"
#define AppVersion "ALPHA-0.1.0"
#define AppPublisher "eF Drift"
#define AppExeName "eF Drift Car Scrutineer Alpha.exe"
#define AppFolderName "eF Drift Car Scrutineer Alpha"
#define PayloadRoot "..\\dist\\alpha_payload"
#define DistRoot "..\\dist"

[Setup]
AppId={{C2A0E21B-1308-4BB8-8D07-2A914306C7D7}}
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher={#AppPublisher}
DefaultDirName={autopf}\eF Drift Car Scrutineer Alpha
DefaultGroupName=eF Drift Car Scrutineer Alpha
DisableProgramGroupPage=yes
UninstallDisplayIcon={app}\{#AppExeName}
OutputDir={#DistRoot}
OutputBaseFilename=eF-Car-Scrutineer-Alpha-Setup-{#AppVersion}
Compression=lzma
SolidCompression=yes
ArchitecturesInstallIn64BitMode=x64compatible
WizardStyle=modern
AppVerName={#AppName} {#AppVersion}
SetupIconFile=..\\icon.ico
InfoBeforeFile=alpha_release_notes.txt
UsePreviousAppDir=yes
UsePreviousLanguage=yes
UsePreviousTasks=yes

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Files]
Source: "{#DistRoot}\{#AppFolderName}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "{#DistRoot}\{#AppExeName}"; DestDir: "{app}"; Flags: ignoreversion
Source: "{#PayloadRoot}\docs\alpha_release_notes.txt"; DestDir: "{app}\docs"; Flags: ignoreversion
Source: "{#PayloadRoot}\docs\README.md"; DestDir: "{app}\docs"; Flags: ignoreversion
Source: "{#PayloadRoot}\VERSION.txt"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{autoprograms}\eF Drift Car Scrutineer Alpha"; Filename: "{app}\{#AppExeName}"
Name: "{autoprograms}\Release Notes"; Filename: "{app}\docs\alpha_release_notes.txt"
Name: "{autodesktop}\eF Drift Car Scrutineer Alpha"; Filename: "{app}\{#AppExeName}"; Tasks: desktopicon
Name: "{autoprograms}\Uninstall eF Drift Car Scrutineer Alpha"; Filename: "{uninstallexe}"

[Tasks]
Name: "desktopicon"; Description: "Create a &desktop shortcut"; GroupDescription: "Additional shortcuts:"

[Run]
Filename: "{app}\{#AppExeName}"; Description: "Launch eF Drift Car Scrutineer"; Flags: nowait postinstall skipifsilent
